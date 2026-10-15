from __future__ import annotations

import pytest
import scrapeunblocker
from conftest import fixture_html, search_html

from redfin_scraper import (
    FilterRejectedError,
    Filters,
    HomeDetails,
    RedfinNotFoundError,
    RedfinParseError,
    lookup_steps,
    split_price,
    unique,
)
from redfin_scraper.models import Home

AUSTIN = "https://www.redfin.com/city/30818/TX/Austin"


def test_zip_search_builds_url_and_routes_through_us(make_scraper):
    scraper, client = make_scraper(lambda url, kw: fixture_html("search_zip.json"))
    page = scraper.search("78704")
    assert client.calls == [("https://www.redfin.com/zipcode/78704", {"proxy_country": "US"})]
    assert page.url == "https://www.redfin.com/zipcode/78704"
    assert len(page.homes) == 2
    assert page.requests == 1


def test_free_text_lookup_reuses_the_lookup_page(make_scraper):
    scraper, client = make_scraper(lambda url, kw: fixture_html("search_sale.json"))
    page = scraper.search("Austin, TX")
    url, kwargs = client.calls[0]
    assert url == "https://www.redfin.com/"
    assert kwargs["steps"] == lookup_steps("Austin, TX")
    assert len(client.calls) == 1  # no filters: the lookup page is the search page
    assert page.region.name == "Austin"
    assert page.requests == 1


def test_free_text_lookup_then_filtered_search(make_scraper):
    scraper, client = make_scraper(lambda url, kw: fixture_html("search_sale.json"))
    page = scraper.search("austin, tx", Filters(min_beds=3, property_types=["house"]))
    assert [call[0] for call in client.calls] == [
        "https://www.redfin.com/",
        AUSTIN + "/filter/property-type=house,min-beds=3",
    ]
    assert page.requests == 2
    # The resolved location is cached: a second search needs no lookup.
    scraper.search("Austin,  TX", Filters(min_beds=4))
    assert client.calls[-1][0] == AUSTIN + "/filter/min-beds=4"
    assert len(client.calls) == 3


def test_lookup_that_does_not_reach_a_search_page(make_scraper):
    scraper, _ = make_scraper(lambda url, kw: fixture_html("home_active.json"))
    with pytest.raises(RedfinNotFoundError, match="search box"):
        scraper.search("7500 Lobelia Dr, Austin, TX")


def test_keyword_shortcuts(make_scraper):
    scraper, client = make_scraper(lambda url, kw: fixture_html("search_sold.json"))
    scraper.search(AUSTIN, sold="3mo")
    assert client.calls[0][0] == AUSTIN + "/filter/include=sold-3mo"


def test_rejected_filters_raise(make_scraper):
    # The page Redfin serves when it drops the filters echoes none back.
    scraper, _ = make_scraper(lambda url, kw: search_html([500_000], total=10))
    with pytest.raises(FilterRejectedError, match="min-beds=3"):
        scraper.search(AUSTIN, Filters(min_beds=3))


def test_rejected_filter_check_can_be_disabled(make_scraper):
    scraper, _ = make_scraper(lambda url, kw: search_html([500_000], total=10), check_filters=False)
    assert len(scraper.search(AUSTIN, Filters(min_beds=3)).homes) == 1


def test_accepted_filters_pass(make_scraper):
    html = search_html([500_000], total=10, applied="min-beds%3D3")
    scraper, _ = make_scraper(lambda url, kw: html)
    assert scraper.search(AUSTIN, Filters(min_beds=3)).applied_filters == "min-beds=3"


def test_rentals_url_needs_rentals(make_scraper):
    scraper, _ = make_scraper(lambda url, kw: fixture_html("rentals.json"))
    with pytest.raises(ValueError, match="rentals"):
        scraper.search(AUSTIN + "/apartments-for-rent")


def test_rentals_search(make_scraper):
    scraper, client = make_scraper(lambda url, kw: fixture_html("rentals.json"))
    page = scraper.rentals(AUSTIN, Filters(max_price=3000, dogs_allowed=True))
    assert client.calls[0][0] == AUSTIN + "/apartments-for-rent/filter/max-price=3000,dogs-allowed"
    assert page.total == 847
    assert len(page.rentals) == 3


def test_retries_transient_errors_with_backoff(make_scraper):
    answers = [
        scrapeunblocker.ScrapeTimeoutError("timed out"),
        scrapeunblocker.BlockedError("blocked", status_code=403),
        fixture_html("search_zip.json"),
    ]
    scraper, client = make_scraper(lambda url, kw: answers.pop(0))
    page = scraper.search("78704")
    assert len(client.calls) == 3
    assert scraper.sleeps == [2.0, 4.0]
    assert page.requests == 3


def test_page_without_data_is_retried_then_fails(make_scraper):
    scraper, client = make_scraper(lambda url, kw: "<html>Please verify you are human</html>")
    with pytest.raises(RedfinParseError):
        scraper.search("78704")
    assert len(client.calls) == 4  # first try + 3 retries


def test_not_found_is_not_retried(make_scraper):
    error = scrapeunblocker.TargetNotFoundError("gone", status_code=404, origin_status=404)
    scraper, client = make_scraper(lambda url, kw: error)
    with pytest.raises(RedfinNotFoundError):
        scraper.home("/TX/Austin/1-Main-St-78701/home/1")
    assert len(client.calls) == 1


def test_other_errors_propagate(make_scraper):
    error = scrapeunblocker.AuthenticationError("bad key", status_code=401)
    scraper, client = make_scraper(lambda url, kw: error)
    with pytest.raises(scrapeunblocker.AuthenticationError):
        scraper.search("78704")
    assert len(client.calls) == 1


def test_home_details(make_scraper):
    scraper, client = make_scraper(lambda url, kw: fixture_html("home_active.json"))
    home = scraper.home("https://www.redfin.com/TX/Austin/7500-Lobelia-Dr-78729/home/32797952")
    assert isinstance(home, HomeDetails)
    assert home.redfin_estimate == 650963
    assert client.calls[0][1] == {"proxy_country": "US"}


def test_homes_skips_missing(make_scraper):
    def respond(url, kw):
        if url.endswith("/home/1"):
            return scrapeunblocker.TargetNotFoundError("gone", status_code=404, origin_status=404)
        return fixture_html("home_condo.json")

    scraper, _ = make_scraper(respond)
    found = list(scraper.homes(["/NY/x/home/1", "/NY/x/home/40483118"]))
    assert [h.open_house for h in found] == ["OPEN SAT, 2PM TO 3PM"]


def test_market_uses_region_page(make_scraper):
    scraper, client = make_scraper(lambda url, kw: fixture_html("search_sale.json"))
    market = scraper.market(AUSTIN + "/filter/min-beds=3")
    assert client.calls[0][0] == AUSTIN
    assert market.median_sale_price == 526_000


def test_locate(make_scraper):
    scraper, client = make_scraper(lambda url, kw: fixture_html("search_zip.json"))
    region = scraper.locate("78704")
    assert region.url == "https://www.redfin.com/zipcode/78704"
    assert client.calls[0][0] == "https://www.redfin.com/zipcode/78704"


# -- getting past the 350-home cap -------------------------------------------------------


def test_split_price():
    assert split_price([100, 300, 200, None], None, None) == 200
    assert split_price([100, 300, 200], 150, 250) == 200
    assert split_price([500, 900], None, 600) == 599
    assert split_price([100], None, None) is None
    assert split_price([100, 120], 200, None) is None


def test_unique_keeps_first():
    homes = [Home(property_id=1, price=1), Home(property_id=2), Home(property_id=1, price=9)]
    assert [(h.property_id, h.price) for h in unique(homes)] == [(1, 1), (2, None)]


def _capped_market(url: str, kw) -> str:
    """350 homes per page (the cap); 500 homes in total, priced 1000..500000."""
    low = high = None
    for token in url.split("/filter/")[-1].split(","):
        if token.startswith("min-price="):
            low = int(token.split("=")[1])
        if token.startswith("max-price="):
            high = int(token.split("=")[1])
    prices = [p * 1000 for p in range(1, 501)]
    matching = [p for p in prices if (low is None or p >= low) and (high is None or p <= high)]
    applied = "x" if low is not None or high is not None else None
    # property ID = price / 1000, so the same home has the same ID in every band
    first_id = matching[0] // 1000 if matching else 1
    return search_html(matching[:350], total=len(matching), start_id=first_id, applied=applied)


def test_search_all_splits_price_bands(make_scraper):
    scraper, client = make_scraper(_capped_market)
    page = scraper.search_all(AUSTIN, max_requests=5)
    assert len(client.calls) == 3  # first page + two price bands
    assert "max-price=" in client.calls[1][0] and "min-price=" in client.calls[2][0]
    assert len(page.homes) == 500
    assert len({h.property_id for h in page.homes}) == 500
    assert page.capped is False
    assert page.requests == 3


def test_search_all_respects_request_budget(make_scraper):
    scraper, client = make_scraper(_capped_market)
    page = scraper.search_all(AUSTIN, max_requests=2)
    assert len(client.calls) == 2
    assert page.capped is True
    assert len(page.homes) == 350


def test_search_all_without_cap_is_one_request(make_scraper):
    scraper, client = make_scraper(lambda url, kw: fixture_html("search_zip.json"))
    page = scraper.search_all("78704")
    assert len(client.calls) == 1
    assert len(page.homes) == 2
