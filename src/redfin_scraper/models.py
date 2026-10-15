"""Plain dataclasses for everything the scraper returns.

Every model has ``to_dict()`` so results serialize straight to JSON; the flat ones
(:class:`Home`, :class:`Rental`) are also what the CSV exporter writes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class _Model:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Region(_Model):
    """A Redfin search area: a city, ZIP code, neighborhood, county, ..."""

    name: str | None = None
    type: str | None = None
    id: int | None = None
    url: str | None = None


@dataclass
class Home(_Model):
    """One home from a for-sale or sold search."""

    property_id: int | None = None
    listing_id: int | None = None
    mls_id: str | None = None
    url: str | None = None
    status: str | None = None
    price: int | None = None
    sale_price_hidden: bool = False
    price_per_sqft: int | None = None
    hoa_monthly: int | None = None
    beds: float | None = None
    baths: float | None = None
    full_baths: int | None = None
    partial_baths: int | None = None
    sqft: int | None = None
    lot_sqft: int | None = None
    year_built: int | None = None
    stories: float | None = None
    property_type: str | None = None
    days_on_market: int | None = None
    last_sold_date: str | None = None
    address: str | None = None
    unit: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location: str | None = None
    listing_broker: str | None = None
    listing_agent: str | None = None
    open_house: str | None = None
    open_house_start: str | None = None
    badges: list[str] = field(default_factory=list)
    key_facts: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    remarks: str | None = None
    photo_count: int | None = None
    has_3d_tour: bool = False
    has_video_tour: bool = False
    is_new_construction: bool = False
    is_hot: bool = False


@dataclass
class Rental(_Model):
    """One rental listing (a house, a unit or a whole apartment building)."""

    property_id: int | None = None
    rental_id: str | None = None
    name: str | None = None
    url: str | None = None
    property_type: str | None = None
    rent_min: int | None = None
    rent_max: int | None = None
    beds_min: float | None = None
    beds_max: float | None = None
    baths_min: float | None = None
    baths_max: float | None = None
    sqft_min: int | None = None
    sqft_max: int | None = None
    available_units: int | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    specials: list[str] = field(default_factory=list)
    key_facts: list[str] = field(default_factory=list)
    description: str | None = None
    phone: str | None = None
    last_updated: str | None = None
    income_restricted: bool = False
    senior_living: bool = False
    student_housing: bool = False


@dataclass
class SearchPage(_Model):
    """One Redfin search: the homes it returned plus what Redfin says about it.

    Redfin returns at most :data:`~redfin_scraper.MAX_RESULTS` homes per search;
    ``capped`` is true when ``total`` says there are more than came back.
    """

    url: str
    region: Region | None = None
    applied_filters: str | None = None
    total: int | None = None
    homes: list[Home] = field(default_factory=list)
    capped: bool = False
    requests: int = 1


@dataclass
class RentalPage(_Model):
    """One Redfin rental search."""

    url: str
    region: Region | None = None
    applied_filters: str | None = None
    total: int | None = None
    total_units: int | None = None
    rentals: list[Rental] = field(default_factory=list)
    capped: bool = False
    requests: int = 1


@dataclass
class HomeDetails(_Model):
    """Everything on a home's page: listing facts, history, taxes, estimates, schools."""

    property_id: int | None = None
    listing_id: int | None = None
    url: str | None = None
    status: str | None = None
    price: int | None = None
    price_label: str | None = None
    price_per_sqft: int | None = None
    redfin_estimate: int | None = None
    rent_estimate: dict[str, Any] | None = None
    beds: float | None = None
    baths: float | None = None
    full_baths: int | None = None
    half_baths: int | None = None
    sqft: int | None = None
    lot_sqft: int | None = None
    year_built: int | None = None
    stories: float | None = None
    property_type: str | None = None
    days_on_market: int | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    county: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    apn: str | None = None
    mls_id: str | None = None
    listing_source: str | None = None
    description: str | None = None
    key_details: dict[str, str] = field(default_factory=dict)
    amenities: list[dict[str, Any]] = field(default_factory=list)
    listing_agent: dict[str, Any] | None = None
    listing_broker: dict[str, Any] | None = None
    property_history: list[dict[str, Any]] = field(default_factory=list)
    tax_history: list[dict[str, Any]] = field(default_factory=list)
    schools: list[dict[str, Any]] = field(default_factory=list)
    walk_score: int | None = None
    transit_score: int | None = None
    bike_score: int | None = None
    climate_risk: dict[str, int] = field(default_factory=dict)
    open_house: str | None = None
    photos: list[str] = field(default_factory=list)
    last_updated: str | None = None


@dataclass
class RentalDetails(_Model):
    """A rental's page: floor plans with live prices, amenities, pet and parking policies."""

    property_id: int | None = None
    rental_id: str | None = None
    name: str | None = None
    url: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    year_built: int | None = None
    description: str | None = None
    management_company: str | None = None
    phone: str | None = None
    office_hours: list[str] = field(default_factory=list)
    floor_plans: list[dict[str, Any]] = field(default_factory=list)
    unit_amenities: list[str] = field(default_factory=list)
    community_amenities: list[str] = field(default_factory=list)
    pet_policies: list[dict[str, Any]] = field(default_factory=list)
    parking: list[dict[str, Any]] = field(default_factory=list)
    walk_score: int | None = None
    transit_score: int | None = None
    bike_score: int | None = None
    climate_risk: dict[str, int] = field(default_factory=dict)


@dataclass
class Market(_Model):
    """Housing-market stats Redfin publishes for a search area."""

    region: Region | None = None
    median_list_price: int | None = None
    median_sale_price: int | None = None
    median_list_price_per_sqft: int | None = None
    median_sale_price_per_sqft: int | None = None
    sale_to_list_percent: float | None = None
    homes_sold: int | None = None
    homes_on_market: int | None = None
    avg_days_on_market: int | None = None
    avg_offers: float | None = None
    avg_down_payment_percent: float | None = None
    sale_price_yoy_percent: float | None = None
    sale_price_per_sqft_yoy_percent: float | None = None
    compete_score: int | None = None
    listings_by_beds: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
