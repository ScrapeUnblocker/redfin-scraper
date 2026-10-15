from __future__ import annotations

import pytest

from redfin_scraper import Filters, SearchTarget, home_url, parse_location, search_url
from redfin_scraper.urls import merge_tokens


def test_zip_code_needs_no_lookup():
    assert parse_location("78704") == SearchTarget(region_path="/zipcode/78704")


def test_free_text_needs_lookup():
    assert parse_location("Austin, TX") is None
    assert parse_location("Capitol Hill, Seattle") is None


def test_search_url_keeps_filters_and_drops_paging():
    target = parse_location(
        "https://www.redfin.com/city/30818/TX/Austin/filter/property-type=house,min-beds=3/page-2"
    )
    assert target.region_path == "/city/30818/TX/Austin"
    assert target.tokens == ["property-type=house", "min-beds=3"]
    assert not target.rentals


def test_rentals_url():
    target = parse_location("/city/30818/TX/Austin/apartments-for-rent/filter/max-price=2.5k")
    assert target.region_path == "/city/30818/TX/Austin"
    assert target.rental_segment == "/apartments-for-rent"
    assert target.rentals
    assert target.tokens == ["max-price=2.5k"]


def test_page_segment_without_filters():
    assert parse_location("/zipcode/78704/page-3").region_path == "/zipcode/78704"


def test_home_url_is_not_a_search_area():
    with pytest.raises(ValueError, match="home page"):
        parse_location("https://www.redfin.com/TX/Austin/7500-Lobelia-Dr-78729/home/32797952")


def test_other_redfin_paths_are_rejected():
    with pytest.raises(ValueError):
        parse_location("https://www.redfin.com/news/some-article")


def test_home_url():
    path = "/TX/Austin/7500-Lobelia-Dr-78729/home/32797952"
    assert home_url(path) == "https://www.redfin.com" + path
    assert home_url("https://www.redfin.com" + path + "/") == "https://www.redfin.com" + path
    with pytest.raises(ValueError):
        home_url("https://www.redfin.com/city/30818/TX/Austin")
    with pytest.raises(ValueError):
        home_url("https://example.com/home/1")


def test_filter_tokens_for_sale():
    filters = Filters(
        min_price=400_000,
        max_price=800_000,
        min_beds=3,
        max_beds=4,
        min_baths=2.5,
        min_sqft=1500,
        max_sqft=3000,
        min_lot_acres=0.25,
        min_year_built=2000,
        max_hoa=200,
        min_stories=2,
        property_types=["house", "Townhouse"],
        statuses=["active", "pending"],
        keyword="solar panels",
        garage=True,
        max_days_on_market="1wk",
        sort="newest",
        extra=["include=forsale+mlsfsbo"],
    )
    assert filters.tokens() == [
        "property-type=house+townhouse",
        "min-price=400000",
        "max-price=800000",
        "min-beds=3",
        "max-beds=4",
        "min-baths=2.5",
        "min-sqft=1500-sqft",
        "max-sqft=3000-sqft",
        "min-lot-size=0.25-acre",
        "min-year-built=2000",
        "hoa=200",
        "min-stories=2",
        "status=active+pending",
        "remarks=solar%20panels",
        "has-garage",
        "max-days-on-market=1wk",
        "sort=lo-days",
        "include=forsale+mlsfsbo",
    ]


def test_sold_filter_and_sort():
    assert Filters(sold="3mo", sort="recently-sold").tokens() == [
        "include=sold-3mo",
        "sort=hi-sale-date",
    ]


def test_default_filters_are_empty():
    assert Filters().tokens() == []
    assert Filters().tokens(rentals=True) == []


def test_rental_filters():
    filters = Filters(property_types=["apartment", "house"], dogs_allowed=True, sort="price-asc")
    assert filters.tokens(rentals=True) == [
        "property-type=multifamily+house",
        "dogs-allowed",
        "sort=lo-price",
    ]


@pytest.mark.parametrize(
    ("filters", "rentals"),
    [
        (Filters(property_types=["castle"]), False),
        (Filters(property_types=["land"]), True),
        (Filters(statuses=["sold"]), False),
        (Filters(sold="2wk"), False),
        (Filters(sold="3mo"), True),
        (Filters(dogs_allowed=True), False),
        (Filters(sort="cheapest"), False),
        (Filters(sort="sqft-desc"), True),
        (Filters(max_days_on_market="a week"), False),
    ],
)
def test_invalid_filters_raise(filters, rentals):
    with pytest.raises(ValueError):
        filters.tokens(rentals=rentals)


def test_with_price_copies():
    filters = Filters(min_beds=3)
    band = filters.with_price(100, 200)
    assert (band.min_price, band.max_price, band.min_beds) == (100, 200, 3)
    assert filters.min_price is None


def test_merge_tokens_overrides_by_key():
    assert merge_tokens(["min-beds=2", "has-garage"], ["min-beds=3", "sort=lo-price"]) == [
        "has-garage",
        "min-beds=3",
        "sort=lo-price",
    ]


def test_search_url():
    target = parse_location("/city/30818/TX/Austin/filter/min-beds=2")
    assert search_url(target, Filters(min_beds=3, max_price=500_000)) == (
        "https://www.redfin.com/city/30818/TX/Austin/filter/max-price=500000,min-beds=3"
    )
    assert search_url(parse_location("78704")) == "https://www.redfin.com/zipcode/78704"
    assert search_url(parse_location("78704"), Filters(max_price=2500), rentals=True) == (
        "https://www.redfin.com/zipcode/78704/apartments-for-rent/filter/max-price=2500"
    )
