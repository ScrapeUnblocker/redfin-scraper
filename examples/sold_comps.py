"""Pull recent sales near a ZIP code and summarize price per square foot.

    python examples/sold_comps.py 98103 3

Arguments: ZIP code, minimum bedrooms. Looks at homes sold in the last 6 months.
In non-disclosure states (Texas, for example) Redfin flags sale prices as not
publicly disclosed; those homes are reported separately.
"""

import statistics
import sys

from redfin_scraper import Filters, RedfinScraper


def main() -> None:
    zip_code = sys.argv[1] if len(sys.argv) > 1 else "98103"
    min_beds = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    scraper = RedfinScraper()
    page = scraper.search(zip_code, Filters(sold="6mo", min_beds=min_beds, sort="recently-sold"))
    sold = [h for h in page.homes if h.status == "Closed"]
    disclosed = [h for h in sold if not h.sale_price_hidden and h.price_per_sqft]
    print(f"{len(sold)} homes with {min_beds}+ beds sold in the last 6 months in {zip_code}")
    if disclosed:
        per_sqft = [h.price_per_sqft for h in disclosed]
        print(
            f"  price per sq ft: median ${statistics.median(per_sqft):,.0f} "
            f"(range ${min(per_sqft):,} - ${max(per_sqft):,}, {len(disclosed)} homes)"
        )
    hidden = sum(1 for h in sold if h.sale_price_hidden)
    if hidden:
        print(f"  {hidden} sale price(s) flagged by Redfin as not publicly disclosed")
    for home in sold[:10]:
        beds = f"{home.beds:g}" if home.beds is not None else "-"
        print(
            f"  {home.last_sold_date}  {home.address:<28} {beds:>2} bd  "
            f"{home.sqft or '-':>5} sqft  {home.url}"
        )


if __name__ == "__main__":
    main()
