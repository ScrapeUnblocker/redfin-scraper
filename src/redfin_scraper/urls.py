"""Build Redfin search URLs from a location and a set of filters.

Redfin keeps every search in the URL path::

    https://www.redfin.com/city/30818/TX/Austin/filter/property-type=house,min-beds=3
    https://www.redfin.com/zipcode/78704/apartments-for-rent/filter/max-price=2500

so a search is just a region path, an optional rentals segment and a comma-separated
list of filter tokens. :class:`Filters` turns keyword arguments into those tokens.
Every token below was checked against what Redfin echoes back for it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from urllib.parse import quote, urlsplit

BASE_URL = "https://www.redfin.com"

#: Property types for sale searches (``property-type=`` tokens).
PROPERTY_TYPES = (
    "house",
    "condo",
    "townhouse",
    "multifamily",
    "land",
    "manufactured",
    "co-op",
    "other",
)
#: Property types rental searches accept. Apartments are ``multifamily``.
RENTAL_PROPERTY_TYPES = ("house", "condo", "townhouse", "multifamily")
TYPE_ALIASES = {
    "apartment": "multifamily",
    "apartments": "multifamily",
    "single-family": "house",
    "coop": "co-op",
    "mobile": "manufactured",
}
#: Listing statuses for sale searches (``status=`` tokens).
STATUSES = ("active", "comingsoon", "contingent", "pending")
#: Look-back windows for sold searches (``include=sold-<window>``).
SOLD_WINDOWS = ("1wk", "1mo", "3mo", "6mo", "1yr", "2yr", "3yr", "5yr")
#: Sort names this package exposes -> Redfin ``sort=`` tokens (``None`` = Redfin's default).
SORTS = {
    "recommended": None,
    "newest": "lo-days",
    "price-asc": "lo-price",
    "price-desc": "hi-price",
    "sqft-desc": "hi-sqft",
    "recently-sold": "hi-sale-date",
}
RENTAL_SORTS = {
    "recommended": None,
    "newest": "lo-days",
    "price-asc": "lo-price",
    "price-desc": "hi-price",
}

_ZIP = re.compile(r"^\d{5}$")
_DAYS_ON_MARKET = re.compile(r"^\d+(d|wk|mo|yr)$")
_HOME_PATH = re.compile(r"/home/\d+")
_REGION_PATH = re.compile(r"^/(city|zipcode|neighborhood|county|school|state|metro)/", re.I)
_RENTAL_SEGMENT = re.compile(r"/[a-z-]+-for-rent$")
_PAGE_SEGMENT = re.compile(r"/page-\d+$")


@dataclass
class SearchTarget:
    """A search area path, plus the rentals segment and filters a pasted URL carried."""

    region_path: str
    rental_segment: str = ""
    tokens: list[str] = field(default_factory=list)

    @property
    def rentals(self) -> bool:
        return bool(self.rental_segment)


def _redfin_path(value: str) -> str | None:
    """The path of a Redfin URL, or of a bare ``/city/...`` style path; else ``None``."""
    text = value.strip()
    if text.startswith(("http://", "https://")):
        parts = urlsplit(text)
        if not parts.netloc.lower().endswith("redfin.com"):
            return None
        return parts.path or "/"
    if text.startswith("/"):
        return text
    return None


def parse_location(value: str) -> SearchTarget | None:
    """Turn a Redfin search URL/path or a 5-digit ZIP code into a :class:`SearchTarget`.

    Returns ``None`` for free text such as ``"Austin, TX"``, which has to be looked
    up on Redfin first (see :meth:`RedfinScraper.locate`).
    """
    text = (value or "").strip()
    if _ZIP.match(text):
        return SearchTarget(region_path=f"/zipcode/{text}")
    path = _redfin_path(text)
    if path is None:
        return None
    if _HOME_PATH.search(path):
        raise ValueError(f"{value!r} is a home page, not a search area - use home() for it")
    tokens: list[str] = []
    if "/filter/" in path:
        path, _, raw = path.partition("/filter/")
        raw = _PAGE_SEGMENT.sub("", raw.rstrip("/"))
        tokens = [token for token in raw.split(",") if token]
    path = _PAGE_SEGMENT.sub("", path.rstrip("/"))
    rental_segment = ""
    match = _RENTAL_SEGMENT.search(path)
    if match:
        rental_segment = match.group(0)
        path = path[: match.start()]
    if not _REGION_PATH.match(path):
        raise ValueError(f"{value!r} is not a Redfin search area URL (e.g. /city/30818/TX/Austin)")
    return SearchTarget(region_path=path, rental_segment=rental_segment, tokens=tokens)


def home_url(value: str) -> str:
    """Full URL of a home page from a URL or a ``/TX/Austin/.../home/123`` path."""
    path = _redfin_path(value)
    if path is None or not _HOME_PATH.search(path):
        raise ValueError(f"{value!r} is not a Redfin home URL (expected .../home/<property id>)")
    return BASE_URL + path.rstrip("/")


def _number(value: float) -> str:
    return f"{value:g}"


def _types(values: list[str], allowed: tuple[str, ...]) -> list[str]:
    out = []
    for value in values:
        name = TYPE_ALIASES.get(value.strip().lower(), value.strip().lower())
        if name not in allowed:
            raise ValueError(f"unknown property type {value!r}; choose from {', '.join(allowed)}")
        if name not in out:
            out.append(name)
    return out


@dataclass
class Filters:
    """Search filters. Leave a field at its default to not filter on it."""

    min_price: int | None = None
    max_price: int | None = None
    min_beds: int | None = None
    max_beds: int | None = None
    min_baths: float | None = None
    min_sqft: int | None = None
    max_sqft: int | None = None
    min_lot_acres: float | None = None
    max_lot_acres: float | None = None
    min_year_built: int | None = None
    max_year_built: int | None = None
    max_hoa: int | None = None
    min_stories: int | None = None
    property_types: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    sold: str | None = None
    keyword: str | None = None
    garage: bool = False
    max_days_on_market: str | None = None
    dogs_allowed: bool = False
    cats_allowed: bool = False
    sort: str = "recommended"
    extra: list[str] = field(default_factory=list)

    def with_price(self, low: int | None, high: int | None) -> Filters:
        """A copy restricted to a price band (used to page past Redfin's result cap)."""
        return replace(self, min_price=low, max_price=high)

    def tokens(self, rentals: bool = False) -> list[str]:
        """The Redfin filter tokens for these filters, in a stable order."""
        out: list[str] = []
        if rentals:
            if self.sold or self.statuses:
                raise ValueError("sold/status filters only apply to homes for sale")
            types = _types(self.property_types, RENTAL_PROPERTY_TYPES)
            sorts = RENTAL_SORTS
        else:
            if self.dogs_allowed or self.cats_allowed:
                raise ValueError("pet filters only apply to rentals")
            types = _types(self.property_types, PROPERTY_TYPES)
            sorts = SORTS
        if types:
            out.append("property-type=" + "+".join(types))
        if self.min_price is not None:
            out.append(f"min-price={int(self.min_price)}")
        if self.max_price is not None:
            out.append(f"max-price={int(self.max_price)}")
        if self.min_beds is not None:
            out.append(f"min-beds={int(self.min_beds)}")
        if self.max_beds is not None:
            out.append(f"max-beds={int(self.max_beds)}")
        if self.min_baths is not None:
            out.append(f"min-baths={_number(self.min_baths)}")
        if self.min_sqft is not None:
            out.append(f"min-sqft={int(self.min_sqft)}-sqft")
        if self.max_sqft is not None:
            out.append(f"max-sqft={int(self.max_sqft)}-sqft")
        if self.min_lot_acres is not None:
            out.append(f"min-lot-size={_number(self.min_lot_acres)}-acre")
        if self.max_lot_acres is not None:
            out.append(f"max-lot-size={_number(self.max_lot_acres)}-acre")
        if self.min_year_built is not None:
            out.append(f"min-year-built={int(self.min_year_built)}")
        if self.max_year_built is not None:
            out.append(f"max-year-built={int(self.max_year_built)}")
        if self.max_hoa is not None:
            out.append(f"hoa={int(self.max_hoa)}")
        if self.min_stories is not None:
            out.append(f"min-stories={int(self.min_stories)}")
        if self.statuses:
            bad = [s for s in self.statuses if s not in STATUSES]
            if bad:
                raise ValueError(f"unknown status {bad[0]!r}; choose from {', '.join(STATUSES)}")
            out.append("status=" + "+".join(self.statuses))
        if self.sold:
            if self.sold not in SOLD_WINDOWS:
                raise ValueError(
                    f"unknown sold window {self.sold!r}; choose from {', '.join(SOLD_WINDOWS)}"
                )
            out.append(f"include=sold-{self.sold}")
        if self.keyword:
            out.append("remarks=" + quote(self.keyword.strip(), safe=""))
        if self.garage:
            out.append("has-garage")
        if self.max_days_on_market:
            if not _DAYS_ON_MARKET.match(self.max_days_on_market):
                raise ValueError("max_days_on_market looks like 3d, 1wk, 2wk, 1mo, 3mo, 1yr")
            out.append(f"max-days-on-market={self.max_days_on_market}")
        if self.dogs_allowed:
            out.append("dogs-allowed")
        if self.cats_allowed:
            out.append("cats-allowed")
        if self.sort not in sorts:
            raise ValueError(f"unknown sort {self.sort!r}; choose from {', '.join(sorts)}")
        if sorts[self.sort]:
            out.append(f"sort={sorts[self.sort]}")
        out.extend(token.strip() for token in self.extra if token.strip())
        return out


def _token_key(token: str) -> str:
    return token.split("=", 1)[0]


def merge_tokens(base: list[str], overrides: list[str]) -> list[str]:
    """Combine filter tokens; a token in ``overrides`` replaces one with the same key."""
    keys = {_token_key(token) for token in overrides}
    return [token for token in base if _token_key(token) not in keys] + list(overrides)


def search_url(target: SearchTarget, filters: Filters | None = None, rentals: bool = False) -> str:
    """The Redfin URL for a search area plus filters (``rentals`` for rental listings)."""
    rentals = rentals or target.rentals
    segment = target.rental_segment or ("/apartments-for-rent" if rentals else "")
    tokens = merge_tokens(target.tokens, (filters or Filters()).tokens(rentals=rentals))
    url = BASE_URL + target.region_path + segment
    if tokens:
        url += "/filter/" + ",".join(tokens)
    return url
