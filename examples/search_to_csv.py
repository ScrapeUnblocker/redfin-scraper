"""Export Redfin homes for sale in a city to CSV.

    python examples/search_to_csv.py "Austin, TX" homes.csv

Uses search_all(), which splits the price range into bands when a search has more
than Redfin's 350-home cap (capped here at 4 requests).
"""

import sys

from redfin_scraper import Filters, RedfinScraper
from redfin_scraper.export import write_csv


def main() -> None:
    location = sys.argv[1] if len(sys.argv) > 1 else "Austin, TX"
    path = sys.argv[2] if len(sys.argv) > 2 else "redfin_homes.csv"

    scraper = RedfinScraper()  # reads SCRAPEUNBLOCKER_KEY
    filters = Filters(min_beds=3, property_types=["house", "townhouse"], sort="newest")
    page = scraper.search_all(location, filters, max_requests=4)

    with open(path, "w", encoding="utf-8", newline="") as handle:
        count = write_csv(page.homes, handle)
    print(f"{page.region.name if page.region else location}: wrote {count} homes to {path}")
    print(f"Redfin reports {page.total} matching homes; used {page.requests} request(s)")


if __name__ == "__main__":
    main()
