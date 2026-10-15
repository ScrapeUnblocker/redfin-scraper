"""Scrape Redfin homes for sale, sold homes, rentals, home details and market stats.

Powered by the ScrapeUnblocker ``getPageSource`` API
(https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos).

Quick start::

    from redfin_scraper import Filters, RedfinScraper

    scraper = RedfinScraper()  # reads SCRAPEUNBLOCKER_KEY
    page = scraper.search("Austin, TX", Filters(min_beds=3, max_price=600_000))
    for home in page.homes:
        print(home.price, home.beds, home.baths, home.sqft, home.address)

    details = scraper.home(page.homes[0].url)
    print(details.redfin_estimate, details.tax_history[:1], details.schools[:1])

    sold = scraper.search("78704", Filters(sold="3mo"))
    rentals = scraper.rentals("Denver, CO", Filters(max_price=2500, dogs_allowed=True))
    stats = scraper.market("Austin, TX")
"""

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
from .parsing import (
    MAX_RESULTS,
    parse_home_page,
    parse_market,
    parse_rentals_page,
    parse_search_page,
)
from .scraper import RedfinScraper, lookup_steps, split_price, unique
from .state import FilterRejectedError, RedfinError, RedfinNotFoundError, RedfinParseError
from .urls import (
    PROPERTY_TYPES,
    RENTAL_PROPERTY_TYPES,
    SOLD_WINDOWS,
    SORTS,
    STATUSES,
    Filters,
    SearchTarget,
    home_url,
    parse_location,
    search_url,
)

__version__ = "0.1.0"

__all__ = [
    "MAX_RESULTS",
    "PROPERTY_TYPES",
    "RENTAL_PROPERTY_TYPES",
    "SOLD_WINDOWS",
    "SORTS",
    "STATUSES",
    "FilterRejectedError",
    "Filters",
    "Home",
    "HomeDetails",
    "Market",
    "RedfinError",
    "RedfinNotFoundError",
    "RedfinParseError",
    "RedfinScraper",
    "Region",
    "Rental",
    "RentalDetails",
    "RentalPage",
    "SearchPage",
    "SearchTarget",
    "__version__",
    "home_url",
    "lookup_steps",
    "parse_home_page",
    "parse_location",
    "parse_market",
    "parse_rentals_page",
    "parse_search_page",
    "search_url",
    "split_price",
    "unique",
]
