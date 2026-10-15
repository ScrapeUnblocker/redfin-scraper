# Redfin Scraper

[![CI](https://github.com/ScrapeUnblocker/redfin-scraper/actions/workflows/ci.yml/badge.svg)](https://github.com/ScrapeUnblocker/redfin-scraper/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Powered by ScrapeUnblocker](https://img.shields.io/badge/powered%20by-ScrapeUnblocker-orange.svg)](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)

Scrape **Redfin** into clean JSON or CSV. It covers homes for sale, recently sold homes, rentals, full property details (Redfin Estimate, tax and price history, schools, climate risk) and housing-market stats. It ships as a CLI and a Python library.

**Powered by [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos).** Every page is fetched through the ScrapeUnblocker `getPageSource` API, which returns Redfin's fully rendered page, so you don't run a browser or manage blocks yourself.

```bash
redfin-scraper search "Austin, TX" --beds 3 --max-price 600k --format table
redfin-scraper search 98103 --sold 6mo --format csv -o seattle_sold.csv
redfin-scraper rentals "Denver, CO" --max-price 2500 --type apartment --dogs
redfin-scraper home https://www.redfin.com/WA/Seattle/1624-N-46th-St-98103/home/118803
redfin-scraper market "Boise, ID"
```

## Features

- **Homes for sale**: price, beds, baths, sq ft, lot size, year built, HOA, property type, status (Active, Coming Soon, Pending, ...), days on market, address, coordinates, neighborhood, open house, badges, key facts, listing remarks, photo count and tour flags.
- **Sold homes**: `--sold 1wk|1mo|3mo|6mo|1yr|2yr|3yr|5yr` with the sale date. A `sale_price_hidden` flag is set when Redfin marks a sale price as not publicly disclosed (in non-disclosure states such as Texas).
- **Rentals**: houses, condos, townhouses and apartment buildings with rent range, bed/bath/sq ft ranges, available units, specials ("12 WEEKS FREE"), key facts and the leasing phone.
- **Full home details** (`home`):
  - **Value:** list or sold price, Redfin Estimate, rent estimate.
  - **Facts:** every MLS amenity group (parking, interior, exterior, utilities, ...), key details, county, APN and MLS ID.
  - **Records:** property history (listed, price changes, sold) and tax history (assessed land and improvement values, taxes per year).
  - **Neighborhood:** assigned schools with GreatSchools ratings, Walk/Transit/Bike Scores, and First Street climate risk factors (flood, fire, heat, wind, air).
  - **Listing:** agent and broker, open house, full-size photos.
- **Rental details**: floor plans with live rent ranges and **individual units** (unit number, rent, sq ft, available date), unit and community amenities, pet policies with pet rent, parking, office hours and management company.
- **Market stats** (`market`): median list and sale price, $/sq ft, sale-to-list %, homes sold and on market, average days on market and offers, year-over-year change, Redfin Compete Score, inventory by bedroom count, and **5 years of monthly history**.
- **Every Redfin search filter that matters**: price, beds, baths, sq ft, lot size, year built, max HOA, stories, property type, listing status, keyword in description, garage, days on market, pets, sort. Any other filter token can be passed straight through.
- **Past the 350-home cap**: `--all` splits the price range into bands until every match is collected (or your request budget runs out), deduplicated by property ID.
- **Location input your way**: `"City, ST"`, a neighborhood name, a ZIP code, or any Redfin search URL pasted from your browser (its filters are kept).
- **Robust**: retries with backoff on timeouts and transient errors, and detects when Redfin silently ignores your filters instead of returning unfiltered results.
- Output as **JSON, JSON Lines, CSV or a terminal table**; typed dataclasses in Python.

## How it works

Redfin renders pages on the server, and while doing so it calls its own JSON APIs (map search, home-details sections, market trends) and **embeds every response in the page** (`root.__reactServerState.InitialContext`). This scraper fetches the page through ScrapeUnblocker's [`getPageSource`](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos) endpoint and reads that embedded data directly. It uses no CSS selectors, so it returns the same structured data the page itself is drawn from.

A few Redfin behaviors the scraper handles for you:

- **One search returns at most 350 homes.** That's Redfin's own cap (`page-2` URLs return the same 350). `search_all()` / `--all` splits the price range at the median price into bands that each fit under the cap.
- **One bad filter drops all filters.** If any filter token is unknown, Redfin silently shows the *unfiltered* search. The scraper compares your filters with the filter string Redfin echoes back and raises `FilterRejectedError` instead of returning misleading results.
- **Place names need a lookup.** `"Boise, ID"` is resolved by typing it into Redfin's own search box with ScrapeUnblocker browser `steps` (one request). That page *is* the search result, so an unfiltered search by name costs a single request. ZIP codes and Redfin URLs need no lookup.

## Install

```bash
git clone https://github.com/ScrapeUnblocker/redfin-scraper.git
cd redfin-scraper
python -m pip install .
```

Get an API key at [scrapeunblocker.com](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos) and expose it as `SCRAPEUNBLOCKER_KEY` (see `.env.example`):

```bash
export SCRAPEUNBLOCKER_KEY=your_key_here
```

Requires Python 3.9+. The only runtime dependency is the official [`scrapeunblocker`](https://docs.scrapeunblocker.com/sdks/python?utm_source=github&utm_medium=integration&utm_campaign=example-repos) SDK.

## CLI usage

```text
redfin-scraper search  LOCATION [filters] [--sold WINDOW] [--sort S] [--all] [-f FORMAT] [-o FILE]
redfin-scraper rentals LOCATION [filters] [--type T] [--dogs] [--cats] [--all] ...
redfin-scraper home    URL [URL ...]
redfin-scraper market  LOCATION [--no-history]
redfin-scraper locate  LOCATION
```

`LOCATION` is a place name (`"Austin, TX"`, `"Capitol Hill, Seattle"`), a ZIP code (`78704`) or a Redfin search URL or path (`https://www.redfin.com/city/30818/TX/Austin/filter/min-beds=3`).

### Search homes for sale

```bash
# 3+ bed houses and townhouses under $600k, newest listings first
redfin-scraper search "Austin, TX" --beds 3 --max-price 600k --type house,townhouse --sort newest -f table

# Every match, not just the first 350 (spends up to 8 requests)
redfin-scraper search "Austin, TX" --beds 3 --all --max-requests 8 -f csv -o austin.csv

# Keyword in the description, garage, max HOA, listed within the last week
redfin-scraper search 78704 --keyword "pool" --garage --max-hoa 300 --max-days 1wk
```

### Sold homes (comps)

```bash
redfin-scraper search 98103 --sold 6mo --beds 3 --sort recently-sold -f csv -o comps.csv
```

### Rentals

```bash
redfin-scraper rentals 78704 --max-price 2500 --type apartment -f table
redfin-scraper rentals "Denver, CO" --beds 2 --dogs --sort price-asc
```

### Home details, market stats, location lookup

```bash
redfin-scraper home https://www.redfin.com/TX/Austin/7500-Lobelia-Dr-78729/home/32797952
redfin-scraper market "Austin, TX" -f json
redfin-scraper market 78704 -f csv          # the monthly history as CSV
redfin-scraper locate "Boise, ID"
```

### Filters

| Option | Redfin filter | Applies to |
| --- | --- | --- |
| `--min-price`, `--max-price` | price (`400000`, `400k`, `1.2m`) | sale, sold, rentals |
| `--beds`, `--max-beds`, `--baths` | bedrooms / bathrooms | sale, sold, rentals |
| `--type` | `house, condo, townhouse, multifamily, land, manufactured, co-op, other` (rentals: `house, condo, townhouse, apartment`) | all |
| `--status` | `active, comingsoon, contingent, pending` | sale |
| `--sold` | `1wk, 1mo, 3mo, 6mo, 1yr, 2yr, 3yr, 5yr` | sold |
| `--min-sqft`, `--max-sqft` | interior size | sale, sold |
| `--min-lot`, `--max-lot` | lot size in acres | sale, sold |
| `--min-year`, `--max-year` | year built | sale, sold |
| `--max-hoa` | HOA dues per month | sale, sold |
| `--min-stories` | stories | sale, sold |
| `--keyword` | words in the listing description | sale, sold |
| `--garage` | has a garage | sale, sold |
| `--max-days` | time on market (`3d`, `1wk`, `1mo`, ...) | sale |
| `--dogs`, `--cats` | pets allowed | rentals |
| `--sort` | `recommended, newest, price-asc, price-desc, sqft-desc, recently-sold` | all (rentals: first four) |
| `--filter TOKEN` | any raw token copied from a Redfin URL (repeatable) | all |

Output options: `--format json|jsonl|csv|table` (default `json`), `--output FILE`, `--limit N`. A summary line, with the result count, Redfin's match count and requests used, goes to stderr so stdout stays clean for piping.

## Library usage

```python
from redfin_scraper import Filters, RedfinScraper

scraper = RedfinScraper()  # reads SCRAPEUNBLOCKER_KEY; or RedfinScraper(api_key="...")

# Homes for sale
page = scraper.search("Austin, TX", Filters(min_beds=3, max_price=600_000, sort="newest"))
print(page.region.name, page.total, page.applied_filters)
for home in page.homes:
    print(home.price, home.beds, home.baths, home.sqft, home.address, home.url)

# Past the 350-home cap, within a request budget
everything = scraper.search_all("Austin, TX", Filters(min_beds=3), max_requests=8)

# Sold comps and rentals
sold = scraper.search("98103", sold="6mo", min_beds=3)  # keyword shortcuts work too
rentals = scraper.rentals("78704", Filters(max_price=2500, property_types=["apartment"]))

# Full details of one home (HomeDetails) or rental building (RentalDetails)
details = scraper.home(page.homes[0].url)
print(details.redfin_estimate, details.rent_estimate, details.tax_history[:2])
print([(s["name"], s["rating"]) for s in details.schools], details.climate_risk)

# Market stats with 5 years of monthly history
market = scraper.market("Austin, TX")
print(market.median_sale_price, market.sale_to_list_percent, market.history[-1])
```

Every result is a dataclass with `to_dict()`. The parsers (`parse_search_page`, `parse_rentals_page`, `parse_home_page`, `parse_market`) are public too, so you can feed them HTML you fetched another way.

Errors: `RedfinNotFoundError` (unknown location or removed home), `FilterRejectedError` (Redfin ignored the filters; pass `check_filters=False` to accept the page anyway), `RedfinParseError` (the page had no data after retries). All derive from `RedfinError`.

## Example output

`redfin-scraper search 98103 --beds 3 --max-price 1.2m --type house -f table --limit 5`:

```text
price        beds  baths  sqft    property_type  status        address                         city            zip
-----------  ----  -----  ------  -------------  ------------  ------------------------------  --------------  -----
1,199,950    5     2      2610    house          Coming Soon   1624 N 46th St                  Seattle         98103
919,000      4     2      2040    house          Active        9752 Evanston Ave N             Seattle         98103
1,200,000    4     3.5    1785    house          Active        9251 Palatine Ave N             Seattle         98103
799,950      3     2      1280    house          Active        9751 Densmore Ave N             Seattle         98103
599,900      4     1      1500    house          Active        9555 College Way N              Seattle         98103
```

One home from the JSON output (`-f json`), trimmed:

```json
{
  "property_id": 118803,
  "url": "https://www.redfin.com/WA/Seattle/1624-N-46th-St-98103/home/118803",
  "status": "Coming Soon",
  "price": 1199950,
  "price_per_sqft": 460,
  "beds": 5.0,
  "baths": 2.0,
  "sqft": 2610,
  "lot_sqft": 4500,
  "year_built": 1922,
  "property_type": "house",
  "address": "1624 N 46th St",
  "city": "Seattle",
  "state": "WA",
  "zip": "98103",
  "latitude": 47.6623241,
  "longitude": -122.3379809,
  "location": "Wallingford",
  "badges": ["EARLY ACCESS", "COMPASS COMING SOON"],
  "key_facts": ["Endless potential", "Corner lot", "Incredible location"],
  "photo_count": 34
}
```

`python examples/home_report.py https://www.redfin.com/ID/Boise/6123-W-Northview-St-83704/home/106669402`:

```text
6123 W Northview St, Boise, ID 83704  [Active]
  3.0 bd / 2.0 ba / 1721 sqft, built 1957
  Price: $500,000
  Redfin Estimate: $499,646
  Rent estimate: $2,101/mo
  Property tax 2025: $2,695
  School: Koelsch Elementary School (PreK-6), rating 2/10
  School: Fairmont Junior High School (7-9), rating 3/10
  School: Capital Senior High School (9-12), rating 5/10
  Walk/Transit/Bike: 54/24/73
  Climate risk: flood 1/10, fire 1/10, heat 4/10, wind 1/10, air 8/10
  2026-10-15  Listed                   $500,000
  https://www.redfin.com/ID/Boise/6123-W-Northview-St-83704/home/106669402
```

`redfin-scraper market 78704 --no-history` (excerpt):

```json
{
  "region": {"name": "78704", "type": "zipcode", "id": 34098, "url": "https://www.redfin.com/zipcode/78704"},
  "median_list_price": 775000,
  "median_sale_price": 884000,
  "median_sale_price_per_sqft": 516,
  "sale_to_list_percent": 95.7,
  "homes_sold": 46,
  "homes_on_market": 368,
  "avg_days_on_market": 100,
  "compete_score": 32,
  "listings_by_beds": [{"beds": "studio", "active_listings": 3, "median_list_price": 925000}, "..."]
}
```

(Live data from the day this README was written; your numbers will differ.)

## Examples

| Script | What it does |
| --- | --- |
| [`examples/search_to_csv.py`](examples/search_to_csv.py) | Export 3+ bed houses and townhouses in a city to CSV with `search_all()` |
| [`examples/sold_comps.py`](examples/sold_comps.py) | Recent sales in a ZIP code with a price-per-sq-ft summary |
| [`examples/home_report.py`](examples/home_report.py) | One-page report: price vs. Redfin Estimate, taxes, schools, Walk Score, climate risk, history |

## Notes and limits

- **Requests:** each page fetch is one API request. A search by ZIP or URL is 1 request; a search by place name is 1 (no filters) or 2 (with filters); `--all` uses up to `--max-requests` in total.
- **350 per search:** without `--all`, results stop at 350 and the result says so (`capped`). Narrow the filters or use `--all` for more.
- **Match counts:** Redfin reports a total match count (`total`) for most for-sale and sold searches, but not all; it's `null` when Redfin didn't send one.
- **Disclosure:** some fields depend on the listing's MLS. For example, full vs. partial baths and the listing agent aren't always provided, and sale prices are hidden in non-disclosure states.
- **Coverage:** redfin.com (United States). Requests are routed through the US by default (`proxy_country`).
- Scrape responsibly: collect public data at a reasonable rate and follow Redfin's terms and the laws that apply to you.

## Project layout

```text
redfin-scraper/
├── src/redfin_scraper/
│   ├── __init__.py      # public API + __version__
│   ├── scraper.py       # RedfinScraper: fetch + retry, location lookup, search_all price bands
│   ├── parsing.py       # page data -> Home / Rental / HomeDetails / RentalDetails / Market
│   ├── state.py         # extracts the API responses embedded in Redfin pages; errors
│   ├── urls.py          # Filters -> Redfin filter tokens, search/home URLs
│   ├── models.py        # dataclasses
│   ├── export.py        # JSON / JSONL / CSV / table writers
│   └── cli.py           # `redfin-scraper` command
├── examples/            # runnable scripts
├── tests/               # offline tests (mocked client + trimmed real page data)
├── pyproject.toml
├── requirements.txt
├── Makefile
└── .env.example
```

## Development

```bash
make install   # pip install -e ".[dev]"
make lint      # ruff check .
make format    # ruff format .
make test      # pytest -q
```

The tests run fully offline. They use a fake client and trimmed snapshots of real Redfin page data (agent names and phone numbers replaced), so they cost no API credits. CI runs lint and tests on Python 3.9 and 3.12.

## Links

- [ScrapeUnblocker](https://scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos): web scraping API that handles blocks, CAPTCHAs and rendering
- [Documentation](https://docs.scrapeunblocker.com/?utm_source=github&utm_medium=integration&utm_campaign=example-repos)
- [Python SDK](https://docs.scrapeunblocker.com/sdks/python?utm_source=github&utm_medium=integration&utm_campaign=example-repos)

## License

[MIT](LICENSE). Copyright (c) 2026 ScrapeUnblocker.
