"""Print a one-page report for a Redfin home: price vs. estimate, taxes, schools, risk.

    python examples/home_report.py https://www.redfin.com/TX/Austin/.../home/32797952

Without an argument it reports on the newest 3-bed listing in Austin, TX.
"""

import sys

from redfin_scraper import Filters, HomeDetails, RedfinScraper


def main() -> None:
    scraper = RedfinScraper()
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        page = scraper.search("Austin, TX", Filters(min_beds=3, sort="newest"))
        url = page.homes[0].url

    home = scraper.home(url)
    if not isinstance(home, HomeDetails):
        print(f"{home.name}: a rental with {len(home.floor_plans)} floor plans")
        return

    print(f"{home.address}, {home.city}, {home.state} {home.zip}  [{home.status}]")
    print(f"  {home.beds} bd / {home.baths} ba / {home.sqft} sqft, built {home.year_built}")
    if home.price:
        print(f"  {home.price_label}: ${home.price:,}")
    if home.redfin_estimate:
        print(f"  Redfin Estimate: ${home.redfin_estimate:,}")
    if home.rent_estimate:
        print(f"  Rent estimate: ${home.rent_estimate['value']:,}/mo")
    if home.tax_history:
        latest = home.tax_history[0]
        print(f"  Property tax {latest['year']}: ${latest['tax']:,.0f}")
    for school in home.schools[:3]:
        print(f"  School: {school['name']} ({school['grades']}), rating {school['rating']}/10")
    if home.walk_score is not None:
        print(f"  Walk/Transit/Bike: {home.walk_score}/{home.transit_score}/{home.bike_score}")
    if home.climate_risk:
        risks = ", ".join(f"{name} {score}/10" for name, score in home.climate_risk.items())
        print(f"  Climate risk: {risks}")
    for event in home.property_history[:5]:
        price = f"${event['price']:,}" if event["price"] else "-"
        print(f"  {event['date']}  {event['event']:<24} {price}")
    print(f"  {home.url}")


if __name__ == "__main__":
    main()
