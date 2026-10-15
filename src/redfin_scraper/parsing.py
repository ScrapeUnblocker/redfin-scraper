"""Turn the data embedded in Redfin pages into the models in :mod:`redfin_scraper.models`.

Each ``parse_*`` function takes the HTML of one Redfin page. The work happens on the
API responses the page carries (see :mod:`redfin_scraper.state`):

* search pages: ``/stingray/api/gis`` (homes for sale / sold, up to 350 per search),
  ``/stingray/api/v1/search/rentals`` (rentals), ``/stingray/api/gis-aggregates``
  (match count), the region breadcrumbs, and the market trends.
* home pages: the ``/stingray/api/home/details/*`` sections (above/below the fold,
  estimates, schools, climate risk) or, for rentals, ``/stingray/api/v1/rentals/*``.

Redfin wraps many values as ``{"value": ..., "level": n}`` where ``level`` says who
may see them; a value hidden from signed-out visitors simply has no ``value``.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from .models import (
    Home,
    HomeDetails,
    Market,
    Region,
    Rental,
    RentalDetails,
    RentalPage,
    SearchPage,
)
from .state import PageData, RedfinNotFoundError, RedfinParseError
from .urls import BASE_URL

#: The most homes (or rental listings) Redfin returns for one search.
MAX_RESULTS = 350

#: ``uiPropertyType`` codes - the same numbering as the ``property-type`` filter.
UI_PROPERTY_TYPES = {
    1: "house",
    2: "condo",
    3: "townhouse",
    4: "multifamily",
    5: "land",
    6: "other",
    7: "manufactured",
    8: "co-op",
}
#: ``propertyType`` codes seen on rental listings.
RENTAL_PROPERTY_TYPES = {6: "house", 3: "condo", 13: "townhouse", 4: "multifamily", 5: "apartment"}
_CLIMATE_RISKS = ("flood", "fire", "heat", "wind", "air")
_GIS = "/stingray/api/gis?"
_RENTALS = "/stingray/api/v1/search/rentals?"


# -- small value helpers ----------------------------------------------------------


def _value(obj: Any) -> Any:
    """Unwrap Redfin's ``{"value": x, "level": n}`` wrapper (``None`` when hidden)."""
    if isinstance(obj, dict):
        return obj.get("value")
    return obj


def _int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _abs_url(path: Any) -> str | None:
    if not isinstance(path, str) or not path:
        return None
    return BASE_URL + path if path.startswith("/") else path


def epoch_date(ms: Any) -> str | None:
    """``YYYY-MM-DD`` for a Redfin date timestamp (epoch milliseconds).

    Redfin stores calendar dates as local midnight, which is morning UTC for every
    US time zone; reading the UTC date half a day later lands on the right day.
    """
    value = _float(ms)
    if value is None:
        return None
    moment = dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=value, hours=12)
    return moment.date().isoformat()


def epoch_iso(ms: Any) -> str | None:
    """ISO-8601 UTC timestamp for epoch milliseconds."""
    value = _float(ms)
    if value is None:
        return None
    moment = dt.datetime(1970, 1, 1) + dt.timedelta(milliseconds=value)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


_MONEY = re.compile(r"^\$?([\d,.]+)\s*([KMB])?$", re.I)
_SCALE = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


def parse_money(text: Any) -> int | None:
    """``"$526K"`` -> 526000, ``"$1.25M"`` -> 1250000, ``"$318"`` -> 318."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return int(text)
    match = _MONEY.match(str(text or "").strip().replace(" ", ""))
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    return int(round(number * _SCALE.get((match.group(2) or "").upper(), 1)))


def parse_percent(text: Any) -> float | None:
    """``"96.7%"`` -> 96.7, ``"+4.2%"`` -> 4.2, ``"-6.5%"`` -> -6.5."""
    match = re.match(r"^([+-]?[\d.]+)\s*%?$", str(text or "").strip())
    return float(match.group(1)) if match else None


def parse_count(text: Any) -> int | None:
    """``"2,429"`` -> 2429, ``"65.06"`` -> 65."""
    return _int(str(text or "").replace(",", "").strip())


# -- search pages -----------------------------------------------------------------


def _query(key: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(key).query).items()}


def parse_region(page: PageData) -> Region | None:
    """The search area of a search page (from its breadcrumbs and API calls)."""
    crumbs = page.payload("/stingray/api/region/", contains="region-breadcrumbs") or {}
    items = [c for c in crumbs.get("breadcrumbs") or [] if c.get("linkType") != "HOME"]
    region = Region()
    if items:
        last = items[-1]
        region.name = last.get("name")
        region.url = last.get("url")
        path = urlsplit(region.url or "").path.strip("/").split("/")
        region.type = path[0] if path and path[0] else None
    for prefix in (_GIS, _RENTALS, "/stingray/api/region?"):
        keys = page.keys(prefix)
        if keys:
            region.id = _int(_query(keys[0]).get("region_id"))
            break
    if region == Region():
        return None
    return region


def applied_filters(page: PageData) -> str | None:
    """The filter string Redfin applied, as it echoes it back (``None`` if none).

    Redfin normalizes what it accepted (``min-price=412500`` comes back as
    ``min-price=412.5k``) and drops the whole string when any token is invalid.
    """
    for key in page.keys("/stingray/api/region?"):
        value = _query(key).get("f")
        if value:
            return unquote(value)
    return None


def _home_search_payload(page: PageData) -> dict | None:
    payload = page.payload(_GIS)
    if isinstance(payload, dict) and isinstance(payload.get("homes"), list):
        return payload
    return None


def _rental_search_payload(page: PageData) -> dict | None:
    keys = page.keys(_RENTALS)
    if not keys:
        return None
    # The page caches two rental searches; the list one (includeKeyFacts=true) is
    # the one built from the full filter set.
    keys.sort(key=lambda key: "includeKeyFacts=true" not in key)
    data = page.cache[keys[0]]
    if isinstance(data, dict) and isinstance(data.get("homes"), list):
        return data
    return None


def parse_home(raw: dict) -> Home:
    """One home from Redfin's map-search data."""
    lat_long = _value(raw.get("latLong")) or {}
    broker = raw.get("listingBroker") or {}
    agent = raw.get("listingAgent") or {}
    return Home(
        property_id=_int(raw.get("propertyId")),
        listing_id=_int(raw.get("listingId")),
        mls_id=_value(raw.get("mlsId")),
        url=_abs_url(raw.get("url")),
        status=raw.get("mlsStatus"),
        price=_int(_value(raw.get("price"))),
        sale_price_hidden=bool(raw.get("hideSalePrice")) and raw.get("mlsStatus") == "Closed",
        price_per_sqft=_int(_value(raw.get("pricePerSqFt"))),
        hoa_monthly=_int(_value(raw.get("hoa"))),
        beds=_float(raw.get("beds")),
        baths=_float(raw.get("baths")),
        full_baths=_int(raw.get("fullBaths")),
        partial_baths=_int(raw.get("partialBaths")),
        sqft=_int(_value(raw.get("sqFt"))),
        lot_sqft=_int(_value(raw.get("lotSize"))),
        year_built=_int(_value(raw.get("yearBuilt"))),
        stories=_float(raw.get("stories")),
        property_type=UI_PROPERTY_TYPES.get(raw.get("uiPropertyType")),
        days_on_market=_int(_value(raw.get("dom"))),
        last_sold_date=epoch_date(raw.get("soldDate")),
        address=_value(raw.get("streetLine")),
        unit=_value(raw.get("unitNumber")),
        city=raw.get("city"),
        state=raw.get("state"),
        zip=raw.get("zip") or _value(raw.get("postalCode")),
        latitude=_float(lat_long.get("latitude")),
        longitude=_float(lat_long.get("longitude")),
        location=_value(raw.get("location")),
        listing_broker=broker.get("name"),
        listing_agent=agent.get("name"),
        open_house=raw.get("openHouseStartFormatted"),
        open_house_start=epoch_iso(raw.get("openHouseStart")),
        badges=[s["sashTypeName"] for s in raw.get("sashes") or [] if s.get("sashTypeName")],
        key_facts=[k["description"] for k in raw.get("keyFacts") or [] if k.get("description")],
        tags=list(raw.get("listingTags") or []),
        remarks=raw.get("listingRemarks"),
        photo_count=_int(raw.get("numPictures")),
        has_3d_tour=bool(raw.get("has3DTour")),
        has_video_tour=bool(raw.get("hasVideoTour")),
        is_new_construction=bool(raw.get("isNewConstruction")),
        is_hot=bool(raw.get("isHot")),
    )


def _range(obj: Any, cast=_int) -> tuple:
    obj = obj or {}
    return cast(obj.get("min")), cast(obj.get("max"))


def parse_rental(raw: dict) -> Rental:
    """One listing from Redfin's rental-search data."""
    home = raw.get("homeData") or {}
    ext = raw.get("rentalExtension") or {}
    address = home.get("addressInfo") or {}
    centroid = (address.get("centroid") or {}).get("centroid") or {}
    rent_min, rent_max = _range(ext.get("rentPriceRange"))
    beds_min, beds_max = _range(ext.get("bedRange"), _float)
    baths_min, baths_max = _range(ext.get("bathRange"), _float)
    sqft_min, sqft_max = _range(ext.get("sqftRange"))
    return Rental(
        property_id=_int(home.get("propertyId")),
        rental_id=ext.get("rentalId"),
        name=ext.get("propertyName"),
        url=_abs_url(home.get("url")),
        property_type=RENTAL_PROPERTY_TYPES.get(home.get("propertyType")),
        rent_min=rent_min,
        rent_max=rent_max,
        beds_min=beds_min,
        beds_max=beds_max,
        baths_min=baths_min,
        baths_max=baths_max,
        sqft_min=sqft_min,
        sqft_max=sqft_max,
        available_units=_int(ext.get("numAvailableUnits")),
        address=address.get("formattedStreetLine"),
        city=address.get("city"),
        state=address.get("state"),
        zip=address.get("zip"),
        latitude=_float(centroid.get("latitude")),
        longitude=_float(centroid.get("longitude")),
        specials=[s["sashTypeName"] for s in home.get("sashes") or [] if s.get("sashTypeName")],
        key_facts=[k["description"] for k in ext.get("keyFacts") or [] if k.get("description")],
        description=ext.get("description"),
        phone=ext.get("desktopPhone"),
        last_updated=ext.get("lastUpdated"),
        income_restricted=bool(ext.get("isIncomeRestricted")),
        senior_living=bool(ext.get("isSeniorLiving")),
        student_housing=bool(ext.get("isStudent")),
    )


def is_search_page(html: str) -> bool:
    """True when the HTML is a Redfin search page with results data."""
    try:
        page = PageData.from_html(html)
    except RedfinParseError:
        return False
    return _home_search_payload(page) is not None or _rental_search_payload(page) is not None


def parse_search_page(html: str, url: str = "") -> SearchPage:
    """A for-sale or sold search page."""
    page = PageData.from_html(html)
    payload = _home_search_payload(page)
    if payload is None:
        if _rental_search_payload(page) is not None:
            raise RedfinParseError("this is a rentals search page - use parse_rentals_page()")
        raise RedfinParseError("no search results data on the page")
    homes = [parse_home(raw) for raw in payload["homes"] if isinstance(raw, dict)]
    aggregates = page.payload("/stingray/api/gis-aggregates") or {}
    total = _int(aggregates.get("numProperties"))
    return SearchPage(
        url=url,
        region=parse_region(page),
        applied_filters=applied_filters(page),
        total=total,
        homes=homes,
        capped=len(homes) >= MAX_RESULTS and (total is None or total > len(homes)),
    )


def parse_rentals_page(html: str, url: str = "") -> RentalPage:
    """A rentals search page."""
    page = PageData.from_html(html)
    payload = _rental_search_payload(page)
    if payload is None:
        raise RedfinParseError("no rental results data on the page")
    rentals = [parse_rental(raw) for raw in payload["homes"] if isinstance(raw, dict)]
    total = _int(payload.get("numMatchedHomes"))
    return RentalPage(
        url=url,
        region=parse_region(page),
        applied_filters=applied_filters(page),
        total=total,
        total_units=_int(payload.get("numMatchedUnits")),
        rentals=rentals,
        capped=len(rentals) >= MAX_RESULTS and (total is None or total > len(rentals)),
    )


# -- market -----------------------------------------------------------------------


def _beds_label(search_url: str) -> str | None:
    match = re.search(r"min-beds=(\d+)(?:,max-beds=(\d+))?", search_url or "")
    if not match:
        return None
    low, high = match.group(1), match.group(2)
    if high is None:
        return f"{low}+"
    return "studio" if low == high == "0" else (low if low == high else f"{low}-{high}")


def parse_market(html: str) -> Market:
    """Housing-market stats from a search page of the area."""
    page = PageData.from_html(html)
    trends = page.payload("/stingray/api/region/", contains="/trends") or {}
    market = Market(
        region=parse_region(page),
        median_list_price=parse_money(trends.get("medianListPrice")),
        median_sale_price=parse_money(trends.get("medianSalePrice")),
        median_list_price_per_sqft=parse_money(trends.get("medianListPerSqFt")),
        median_sale_price_per_sqft=parse_money(trends.get("medianSalePerSqFt")),
        sale_to_list_percent=parse_percent(trends.get("medianSalePerList")),
        homes_sold=parse_count(trends.get("numHomesSold")),
        homes_on_market=parse_count(trends.get("numHomesOnMarket")),
        avg_days_on_market=parse_count(trends.get("avgDaysOnMarket")),
        avg_offers=_float(trends.get("avgNumOffers")),
        avg_down_payment_percent=parse_percent(trends.get("avgDownPayment")),
        sale_price_yoy_percent=parse_percent(trends.get("yoySalePrice")),
        sale_price_per_sqft_yoy_percent=parse_percent(trends.get("yoySalePerSqft")),
    )
    compete = page.payload("/stingray/api/region/", contains="compete-score") or {}
    scores = compete.get("scoreAggs") or []
    if scores:
        market.compete_score = _int(scores[0].get("score"))
    afford = page.payload("/stingray/api/region/", contains="/affordability") or {}
    for item in afford.get("bedroomAggregates") or []:
        agg = item.get("aggregate") or {}
        market.listings_by_beds.append(
            {
                "beds": _beds_label(item.get("searchUrl", "")),
                "active_listings": _int(agg.get("activeListingsCount")),
                "median_list_price": _int(agg.get("listPriceMedian")),
            }
        )
    graph = page.payload("/stingray/api/graph/") or {}
    by_month: dict[str, dict[str, Any]] = {}
    names = {
        "Median Sale Price": ("median_sale_price", parse_money),
        "# of Homes Sold": ("homes_sold", parse_count),
        "Median Days on Market": ("median_days_on_market", parse_count),
    }
    for metric in graph.get("metrics") or []:
        name, cast = names.get(metric.get("label"), (None, None))
        if not name:
            continue
        for point in metric.get("aggregateData") or []:
            month = (point.get("date") or "")[:7]
            if month:
                row = by_month.setdefault(month, {"month": month})
                row[name] = cast(point.get("value"))
                yoy = str(point.get("yoy") or "")
                # Prices and counts change by a percentage; days on market by days.
                if yoy.endswith("%"):
                    row[f"{name}_yoy_percent"] = parse_percent(yoy)
                else:
                    row[f"{name}_yoy_change"] = _float(yoy)
    market.history = [by_month[m] for m in sorted(by_month)]
    return market


# -- home pages -------------------------------------------------------------------


def _scores(page: PageData) -> tuple:
    section = page.payload("/stingray/api/home/details/aroundThisHomeSectionInfo") or {}
    data = section.get("walkScoreData") or {}
    if not data:
        stats = page.payload("/stingray/api/home/details/neighborhoodStats") or {}
        data = (stats.get("walkScoreInfo") or {}).get("walkScoreData") or {}
    return tuple(
        _int((data.get(name) or {}).get("value"))
        for name in ("walkScore", "transitScore", "bikeScore")
    )


def _climate_risk(page: PageData) -> dict[str, int]:
    """First Street climate-risk factors (1 = minimal ... 10 = extreme)."""
    data = page.payload("/stingray/api/v1/home/details/belowTheFold/riskFactorData") or {}
    out: dict[str, int] = {}
    for risk in _CLIMATE_RISKS:
        section = data.get(f"{risk}Data") or data.get(f"{risk}DataV2") or {}
        score = section.get(f"{risk}Factor", section.get("riskFactorScore"))
        if _int(score) is not None:
            out[risk] = _int(score)
    return out


def _is_rental_page(page: PageData) -> bool:
    return any(
        key.split("?")[0].endswith("/floorPlans") for key in page.keys("/stingray/api/v1/rentals/")
    )


def _check_found(page: PageData) -> None:
    info = page.payload("/stingray/api/home/details/initialInfo")
    if isinstance(info, dict) and _int(info.get("responseCode")) not in (None, 200):
        raise RedfinNotFoundError(f"Redfin has no such home (response code {info['responseCode']})")
    if not page.keys("/stingray/api/home/details/aboveTheFold") and not _is_rental_page(page):
        raise RedfinParseError("no home details data on the page")


def parse_home_page(html: str, url: str = ""):
    """A home's page: :class:`HomeDetails`, or :class:`RentalDetails` for a rental."""
    page = PageData.from_html(html)
    _check_found(page)
    if _is_rental_page(page):
        return _rental_details(page, url)
    return _home_details(page, url)


_LINK = re.compile(r"""<a\s[^>]*href=['"]([^'"]+)['"]""", re.I)
_TAG = re.compile(r"<[^>]+>")


def clean_amenity(value: Any) -> str:
    """An amenity value as plain text; an embedded link (e.g. a virtual tour) becomes its URL."""
    text = str(value)
    link = _LINK.search(text)
    if link:
        return link.group(1)
    return " ".join(_TAG.sub(" ", text).split())


def _amenities(below: dict) -> list[dict[str, Any]]:
    out = []
    for group in (below.get("amenitiesInfo") or {}).get("superGroups") or []:
        category = group.get("titleString")
        for sub in group.get("amenityGroups") or []:
            for entry in sub.get("amenityEntries") or []:
                values = [
                    clean_amenity(v)
                    for v in entry.get("amenityValues") or []
                    if v not in (None, "")
                ]
                if not values:
                    continue
                out.append(
                    {
                        "category": category,
                        "group": sub.get("groupTitle"),
                        "name": entry.get("amenityName"),
                        "values": values,
                    }
                )
    return out


def _history(below: dict) -> list[dict[str, Any]]:
    events = (below.get("propertyHistoryInfo") or {}).get("events") or []
    out = []
    for event in events:
        if event.get("isEventAdminOnly"):
            continue
        out.append(
            {
                "date": epoch_date(event.get("eventDate")),
                "event": event.get("eventDescription"),
                "price": None if event.get("isPriceAdminOnly") else _int(event.get("price")),
                "source": event.get("source"),
                "mls_id": event.get("sourceId"),
            }
        )
    return out


def _taxes(records: dict) -> list[dict[str, Any]]:
    out = []
    for row in records.get("allTaxInfo") or []:
        land = _int(row.get("taxableLandValue"))
        improvements = _int(row.get("taxableImprovementValue"))
        out.append(
            {
                "year": _int(row.get("rollYear")),
                "tax": _float(row.get("taxesDue")),
                "land_value": land,
                "improvement_value": improvements,
                "assessed_value": land + improvements
                if land is not None and improvements is not None
                else None,
            }
        )
    return out


def _schools(page: PageData) -> list[dict[str, Any]]:
    data = page.payload("/stingray/api/v1/home/details/belowTheFold/schoolsAndDistrictsInfo") or {}
    schools = data.get("servingThisHomeSchools") or data.get("schoolsToShowOnDP") or []
    out = []
    for school in schools:
        out.append(
            {
                "name": school.get("name"),
                "type": school.get("institutionType"),
                "grades": school.get("gradeRanges"),
                "rating": _int(school.get("greatSchoolsRating")),
                "parent_rating": _int(school.get("parentRating")),
                "distance_miles": _float(school.get("distanceInMiles")),
                "students": _int(school.get("numberOfStudents")),
                "student_teacher_ratio": _int(school.get("studentToTeacherRatio")),
                "serves_home": bool(school.get("servesHome")),
                "url": _abs_url(school.get("schoolUrl")),
            }
        )
    return out


def _person(name: Any, phone: Any) -> dict[str, Any] | None:
    if not name:
        return None
    return {"name": name, "phone": phone or None}


def _home_details(page: PageData, url: str) -> HomeDetails:
    above = page.payload("/stingray/api/home/details/aboveTheFold") or {}
    info = above.get("addressSectionInfo") or {}
    media = above.get("mediaBrowserInfo") or {}
    below = page.payload("/stingray/api/v1/home/details/belowTheFold") or {}
    records = below.get("publicRecordsInfo") or {}
    basic = records.get("basicInfo") or {}
    panel = page.payload("/stingray/api/home/details/mainHouseInfoPanelInfo") or {}
    main = panel.get("mainHouseInfo") or {}
    avm = page.payload("/stingray/api/home/details/avm") or {}
    rent = (page.payload("/stingray/api/home/details/rental-estimate") or {}).get(
        "rentalEstimateInfo"
    ) or {}
    initial = page.payload("/stingray/api/home/details/initialInfo") or {}
    disclaimer = (below.get("amenitiesInfo") or {}).get("mlsDisclaimerInfo") or {}
    agents = main.get("listingAgents") or []
    lat_long = info.get("latLong") or {}
    price = info.get("priceInfo") or {}
    remarks = [r.get("marketingRemark") for r in main.get("marketingRemarks") or []]
    key_details = {
        item["header"]: item["content"]
        for item in main.get("selectedAmenities") or []
        if item.get("header") and item.get("content")
    }
    estimate = avm.get("predictedValue") or (info.get("avmInfo") or {}).get("predictedValue")
    walk, transit, bike = _scores(page)
    agent = _person(disclaimer.get("listingAgentName"), disclaimer.get("listingAgentNumber"))
    if agent is None and agents:
        agent = _person((agents[0].get("agentInfo") or {}).get("agentName"), None)
    broker = _person(disclaimer.get("listingBrokerName"), disclaimer.get("listingBrokerNumber"))
    if broker is None and agents:
        broker = _person(agents[0].get("brokerName"), None)
    open_house = next(
        (s.get("openHouseText") for s in media.get("sashes") or [] if s.get("openHouseText")),
        None,
    )
    return HomeDetails(
        property_id=_int(
            initial.get("propertyId") or (info.get("avmInfo") or {}).get("propertyId")
        ),
        listing_id=_int(initial.get("listingId") or main.get("listingId")),
        url=_abs_url(info.get("url")) or url or None,
        status=(info.get("status") or {}).get("displayValue")
        or (main.get("mlsStatusDisplay") or {}).get("displayValue"),
        price=_int(price.get("amount")),
        price_label=price.get("label"),
        price_per_sqft=_int(info.get("pricePerSqFt")),
        redfin_estimate=_int(estimate),
        rent_estimate={
            "value": _int(rent.get("predictedValue")),
            "low": _int(rent.get("predictedValueLow")),
            "high": _int(rent.get("predictedValueHigh")),
        }
        if rent.get("predictedValue")
        else None,
        beds=_float(info.get("beds")),
        baths=_float(info.get("baths")),
        full_baths=_int(info.get("numFullBaths")),
        half_baths=_int(info.get("rawHalfBaths")),
        sqft=_int(_value(info.get("sqFt"))),
        lot_sqft=_int(basic.get("lotSqFt") or info.get("lotSize")),
        year_built=_int(info.get("yearBuilt") or basic.get("yearBuilt")),
        stories=_float(basic.get("numStories")),
        property_type=basic.get("propertyTypeName") or key_details.get("Property Type"),
        days_on_market=_int(info.get("cumulativeDaysOnMarket")),
        address=(info.get("streetAddress") or {}).get("assembledAddress"),
        city=info.get("city"),
        state=info.get("state"),
        zip=info.get("zip"),
        county=records.get("countyName"),
        latitude=_float(lat_long.get("latitude")),
        longitude=_float(lat_long.get("longitude")),
        apn=basic.get("apn") or info.get("apn"),
        mls_id=main.get("mlsId") or key_details.get("MLS#"),
        listing_source=(main.get("source") or {}).get("dataSourceName"),
        description=next((r for r in remarks if r), None),
        key_details=key_details,
        amenities=_amenities(below),
        listing_agent=agent,
        listing_broker=broker,
        property_history=_history(below),
        tax_history=_taxes(records),
        schools=_schools(page),
        walk_score=walk,
        transit_score=transit,
        bike_score=bike,
        climate_risk=_climate_risk(page),
        open_house=open_house,
        photos=[
            (p.get("photoUrls") or {}).get("fullScreenPhotoUrl")
            for p in media.get("photos") or []
            if (p.get("photoUrls") or {}).get("fullScreenPhotoUrl")
        ],
        last_updated=epoch_iso(main.get("lastUpdatedDate")),
    )


def _rental_section(page: PageData, name: str) -> dict:
    for key in page.keys("/stingray/api/v1/rentals/"):
        if key.split("?")[0].endswith("/" + name):
            data = page.cache[key]
            return data if isinstance(data, dict) else {}
    return {}


def _floor_plans(data: dict) -> list[dict[str, Any]]:
    groups = data.get("unitTypesByBedroom") or []
    group = next((g for g in groups if g.get("bedroomTitle") == "All"), groups[0] if groups else {})
    out = []
    for unit_type in (group.get("availableUnitTypes") or []) + (
        group.get("unavailableUnitTypes") or []
    ):
        full, half = _int(unit_type.get("fullBaths")) or 0, _int(unit_type.get("halfBaths")) or 0
        out.append(
            {
                "name": unit_type.get("name"),
                "beds": _float(unit_type.get("bedrooms")),
                "baths": full + 0.5 * half if full or half else None,
                "sqft_min": _int(unit_type.get("sqftMin")),
                "sqft_max": _int(unit_type.get("sqftMax")),
                "rent_min": _int(unit_type.get("rentPriceMin")),
                "rent_max": _int(unit_type.get("rentPriceMax")),
                "available_units": _int(unit_type.get("availableUnits")),
                "available_date": (unit_type.get("dateAvailable") or "")[:10] or None,
                "status": unit_type.get("status"),
                "units": [
                    {
                        "unit": unit.get("name"),
                        "rent": _int(unit.get("rentPrice")),
                        "sqft": _int(unit.get("sqft")),
                        "available_date": (unit.get("dateAvailable") or "")[:10] or None,
                        "status": unit.get("status"),
                    }
                    for unit in unit_type.get("units") or []
                ],
            }
        )
    return out


def _rental_details(page: PageData, url: str) -> RentalDetails:
    above = page.payload("/stingray/api/home/details/aboveTheFold") or {}
    info = above.get("addressSectionInfo") or {}
    initial = page.payload("/stingray/api/home/details/initialInfo") or {}
    about = _rental_section(page, "about")
    contacts = _rental_section(page, "contacts")
    amenities = _rental_section(page, "amenities")
    fees = _rental_section(page, "feesAndPolicies")
    plans = _rental_section(page, "floorPlans")
    lat_long = info.get("latLong") or {}
    walk, transit, bike = _scores(page)
    hours = about.get("leasingOfficeSchedules") or contacts.get("leasingOfficeSchedules") or []
    return RentalDetails(
        property_id=_int(initial.get("propertyId")),
        rental_id=plans.get("rentalId") or about.get("rentalId") or contacts.get("rentalId"),
        name=contacts.get("propertyName"),
        url=_abs_url(info.get("url")) or url or None,
        address=(info.get("streetAddress") or {}).get("assembledAddress"),
        city=info.get("city"),
        state=info.get("state"),
        zip=info.get("zip"),
        latitude=_float(lat_long.get("latitude")),
        longitude=_float(lat_long.get("longitude")),
        year_built=_int(info.get("yearBuilt")),
        description=about.get("description"),
        management_company=(about.get("managementCompany") or {}).get("name"),
        phone=contacts.get("desktopPhone"),
        office_hours=[
            f"{h.get('day')} {h.get('open')}-{h.get('close')}"
            for h in hours
            if h.get("day") and h.get("open")
        ],
        floor_plans=_floor_plans(plans),
        unit_amenities=list(amenities.get("unitAmenities") or []),
        community_amenities=list(amenities.get("communityAmenities") or []),
        pet_policies=[
            {
                "pet": p.get("policyName"),
                "rent": _int(p.get("petRent")),
                "deposit": _int(p.get("petDeposit")),
                "fee": _int(p.get("petFee")),
                "note": p.get("petPolicyComment"),
            }
            for p in fees.get("petPolicies") or []
        ],
        parking=[
            {
                "type": p.get("parkingTypeName"),
                "fee": _int(p.get("parkingFee")),
                "assigned": p.get("isAssigned"),
            }
            for p in fees.get("parkingTypes") or []
        ],
        walk_score=walk,
        transit_score=transit,
        bike_score=bike,
        climate_risk=_climate_risk(page),
    )
