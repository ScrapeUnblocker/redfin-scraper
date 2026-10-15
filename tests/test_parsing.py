from __future__ import annotations

import pytest
from conftest import fixture_html, load_fixture, page_html

from redfin_scraper import (
    HomeDetails,
    RedfinNotFoundError,
    RedfinParseError,
    RentalDetails,
    parse_home_page,
    parse_market,
    parse_rentals_page,
    parse_search_page,
)
from redfin_scraper.parsing import (
    clean_amenity,
    epoch_date,
    epoch_iso,
    is_search_page,
    parse_count,
    parse_money,
    parse_percent,
)
from redfin_scraper.state import PageData, extract_data_cache

# -- state -----------------------------------------------------------------------------


def test_extract_data_cache_strips_json_guard():
    cache = extract_data_cache(page_html({"/stingray/api/x": {"payload": {"a": 1}}}))
    assert cache == {"/stingray/api/x": {"payload": {"a": 1}}}


def test_extract_data_cache_without_state_raises():
    with pytest.raises(RedfinParseError):
        extract_data_cache("<html><body>Access denied</body></html>")


def test_payload_returns_none_for_empty_envelope():
    page = PageData({"/stingray/api/gis-aggregates?x": {"version": 1, "errorMessage": "Success"}})
    assert page.payload("/stingray/api/gis-aggregates") is None


# -- search pages ------------------------------------------------------------------------


def test_for_sale_search_page():
    page = parse_search_page(fixture_html("search_sale.json"), "https://example")
    assert page.region.name == "Austin"
    assert page.region.type == "city"
    assert page.region.id == 30818
    assert page.region.url == "https://www.redfin.com/city/30818/TX/Austin"
    assert page.applied_filters == "property-type=house,min-price=400k,max-price=800k,min-beds=3"
    assert page.total == 1505
    assert len(page.homes) == 3
    assert page.capped is False  # only 3 homes in the trimmed fixture

    home = page.homes[0]
    assert home.property_id == 31695242
    assert home.url == "https://www.redfin.com/TX/Austin/2506-East-Side-Dr-78704/home/31695242"
    assert home.status == "Active"
    assert home.price == 699000
    assert home.price_per_sqft == 639
    assert (home.beds, home.baths, home.sqft, home.lot_sqft) == (3.0, 2.0, 1094, 7840)
    assert home.year_built == 1961
    assert home.property_type == "house"
    assert home.address == "2506 East Side Dr"
    assert (home.city, home.state, home.zip) == ("Austin", "TX", "78704")
    assert home.latitude == pytest.approx(30.2346477)
    assert home.open_house == "Oct 18, 1:00PM"
    assert home.open_house_start == "2026-10-18T18:00:00Z"
    assert home.badges == ["Open House"]
    assert "Hardwood floors" in home.key_facts
    assert home.last_sold_date == "2014-04-11"
    assert home.sale_price_hidden is False

    coming_soon = page.homes[2]
    assert coming_soon.status == "Coming Soon"
    assert "EARLY ACCESS" in coming_soon.badges


def test_sold_search_page():
    page = parse_search_page(fixture_html("search_sold.json"))
    assert page.applied_filters == "include=sold-3mo"
    assert page.total == 2444
    condo = page.homes[1]
    assert condo.status == "Closed"
    assert condo.property_type == "condo"
    assert condo.unit == "#304"
    assert condo.hoa_monthly == 458
    assert condo.last_sold_date == "2026-08-12"
    # Texas does not disclose sale prices; Redfin flags it.
    assert condo.sale_price_hidden is True


def test_zip_search_page_without_aggregates():
    page = parse_search_page(fixture_html("search_zip.json"))
    assert page.region.type == "zipcode"
    assert page.region.name == "78704"
    assert page.total is None
    assert page.applied_filters is None
    assert [h.property_type for h in page.homes] == ["house", "condo"]


def test_search_page_capped_flag():
    entries = load_fixture("search_sold.json")
    gis = next(k for k in entries if k.startswith("/stingray/api/gis?"))
    homes = entries[gis]["payload"]["homes"]
    entries[gis]["payload"]["homes"] = [dict(homes[0], propertyId=i) for i in range(350)]
    page = parse_search_page(page_html(entries))
    assert len(page.homes) == 350
    assert page.capped is True  # 2444 match, 350 returned


def test_rentals_page_uses_the_full_filter_search():
    page = parse_rentals_page(fixture_html("rentals.json"))
    assert page.total == 847  # the list search, not the 1074 of the map-pin search
    assert page.total_units == 735
    assert page.applied_filters.startswith("sort=lo-price,property-type=house")
    rental = page.rentals[0]
    assert rental.property_id == 31030999
    assert rental.rental_id == "286209c7-790a-4ed9-8830-59cfe18bfadb"
    assert rental.property_type == "house"
    assert (rental.rent_min, rental.rent_max) == (450, 450)
    assert (rental.beds_min, rental.baths_min, rental.sqft_min) == (4.0, 2.0, 2780)
    assert rental.available_units == 1
    assert rental.key_facts == ["Pets welcome", "Laundry in unit", "A/C"]
    assert rental.phone == "555-010-0100"


def test_search_parser_rejects_rentals_page():
    with pytest.raises(RedfinParseError, match="rentals"):
        parse_search_page(fixture_html("rentals.json"))


def test_search_parser_rejects_page_without_results():
    with pytest.raises(RedfinParseError):
        parse_search_page(page_html({"/stingray/api/region?region_id=1": {"version": 1}}))


def test_is_search_page():
    assert is_search_page(fixture_html("search_zip.json"))
    assert is_search_page(fixture_html("rentals.json"))
    assert not is_search_page(fixture_html("home_active.json"))
    assert not is_search_page("<html>blocked</html>")


# -- market ------------------------------------------------------------------------------


def test_market_stats():
    market = parse_market(fixture_html("search_sale.json"))
    assert market.region.name == "Austin"
    assert market.median_list_price == 500_000
    assert market.median_sale_price == 526_000
    assert market.sale_to_list_percent == 96.7
    assert market.homes_on_market == 4657
    assert market.avg_days_on_market == 85
    assert market.sale_price_yoy_percent == 4.2
    assert market.compete_score == 41
    assert market.listings_by_beds[0] == {
        "beds": "studio",
        "active_listings": 43,
        "median_list_price": 350000,
    }
    assert [row["month"] for row in market.history] == ["2026-07", "2026-08", "2026-09"]
    september = market.history[-1]
    assert september["median_sale_price"] == 537244
    assert september["median_sale_price_yoy_percent"] == -0.51
    assert september["median_days_on_market"] == 65
    assert september["median_days_on_market_yoy_change"] == -9.0


# -- home pages --------------------------------------------------------------------------


def test_home_details():
    home = parse_home_page(fixture_html("home_active.json"))
    assert isinstance(home, HomeDetails)
    assert home.property_id == 32797952
    assert home.status == "Active"
    assert home.price == 650000
    assert home.redfin_estimate == 650963
    assert home.rent_estimate == {"value": 3535, "low": 3442, "high": 3592}
    assert (home.beds, home.baths, home.full_baths, home.half_baths) == (6.0, 3.5, 3, 1)
    assert home.lot_sqft == 9930
    assert home.property_type == "Single Family Residential"
    assert home.county == "Williamson County"
    assert home.apn == "R086227"
    assert home.mls_id == "8307015"
    assert home.description.startswith("A stunning home")
    assert home.key_details["Parking"] == "2 car garage"
    covered = next(a for a in home.amenities if a["name"] == "# of Covered Spaces")
    assert covered["category"] == covered["group"] == "Parking"
    assert covered["values"] == ["2"]
    assert home.listing_agent == {"name": "Agent B", "phone": "555-010-0100"}
    assert home.listing_broker["name"] == "Christies Intl Real Estate Lone Star"
    assert home.property_history[0] == {
        "date": "2026-10-15",
        "event": "Listed",
        "price": 650000,
        "source": "Unlock MLS",
        "mls_id": "8307015",
    }
    assert home.property_history[1]["price"] is None  # sale price not disclosed
    assert home.tax_history[0] == {
        "year": 2026,
        "tax": 11188.75,
        "land_value": 100500,
        "improvement_value": 472902,
        "assessed_value": 573402,
    }
    assert home.schools[0]["name"] == "Pond Springs Elementary School"
    assert home.schools[0]["rating"] == 8
    assert home.schools[0]["distance_miles"] == 0.4
    assert (home.walk_score, home.transit_score, home.bike_score) == (46, 24, 41)
    assert home.climate_risk == {"flood": 1, "fire": 3, "heat": 7, "wind": 6, "air": 2}
    assert home.photos[0] == "https://ssl.cdn-redfin.com/photo/92/bigphoto/015/8307015_0.jpg"
    assert home.last_updated == "2026-10-15T14:45:47Z"


def test_condo_details_open_house_and_hidden_estimate():
    home = parse_home_page(fixture_html("home_condo.json"))
    assert home.open_house == "OPEN SAT, 2PM TO 3PM"
    assert home.redfin_estimate is None
    assert home.days_on_market == 194
    assert home.property_type == "Condo/Co-op"


def test_rental_details():
    rental = parse_home_page(fixture_html("home_rental.json"))
    assert isinstance(rental, RentalDetails)
    assert rental.name == "Alexan St. Elmo"
    assert rental.rental_id == "bfec2395-8335-4a01-abfe-e29550b43b1c"
    assert rental.management_company == "RPM Living"
    assert rental.office_hours[0] == "Sunday 1:00 PM-5:00 PM"
    plan = rental.floor_plans[0]
    assert plan["name"] == "S2"
    assert (plan["beds"], plan["baths"]) == (0.0, 1.0)
    assert (plan["rent_min"], plan["rent_max"]) == (1726, 1766)
    assert plan["units"][0] == {
        "unit": "457",
        "rent": 1766,
        "sqft": 630,
        "available_date": "2027-01-06",
        "status": "upcoming",
    }
    assert "Washer" in rental.unit_amenities
    assert rental.pet_policies[1] == {
        "pet": "dogs",
        "rent": 25,
        "deposit": None,
        "fee": None,
        "note": "Dog",
    }
    assert rental.climate_risk["heat"] == 8


def test_home_page_not_found():
    html = page_html({"/stingray/api/home/details/initialInfo": {"payload": {"responseCode": 404}}})
    with pytest.raises(RedfinNotFoundError):
        parse_home_page(html)


def test_home_page_without_details_raises():
    with pytest.raises(RedfinParseError):
        parse_home_page(fixture_html("search_zip.json"))


# -- helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [("$526K", 526_000), ("$1.25M", 1_250_000), ("$318", 318), ("$1,050", 1050), ("n/a", None)],
)
def test_parse_money(text, expected):
    assert parse_money(text) == expected


def test_parse_percent_and_count():
    assert parse_percent("96.7%") == 96.7
    assert parse_percent("+4.2%") == 4.2
    assert parse_percent("-6.5%") == -6.5
    assert parse_percent("") is None
    assert parse_count("2,429") == 2429
    assert parse_count("65.06") == 65
    assert parse_count(None) is None


def test_epoch_helpers():
    # 2026-08-12 00:00 US/Pacific
    assert epoch_date(1786518000000) == "2026-08-12"
    assert epoch_date(None) is None
    assert epoch_iso(1792260000000) == "2026-10-17T18:00:00Z"


def test_clean_amenity():
    link = "<a href='https://tours.example/1' target='_blank'>Virtual Tour (External Link)</a>"
    assert clean_amenity(link) == "https://tours.example/1"
    assert clean_amenity("<b>Gas</b>  Log") == "Gas Log"
    assert clean_amenity("Has Garage") == "Has Garage"
