"""Command-line interface: ``redfin-scraper <command> ...``.

Commands:
  search   homes for sale (or sold with --sold) in a city, ZIP code or Redfin URL
  rentals  rental listings in a location
  home     full details of one or more homes (or rentals) by Redfin URL
  market   housing-market stats for a location (medians, sale-to-list, history)
  locate   resolve a place name to its Redfin search area
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any, TextIO

from . import __version__
from .export import (
    HOME_COLUMNS,
    RENTAL_COLUMNS,
    write_csv,
    write_json,
    write_jsonl,
    write_table,
)
from .scraper import RedfinScraper
from .state import RedfinError
from .urls import (
    PROPERTY_TYPES,
    RENTAL_PROPERTY_TYPES,
    RENTAL_SORTS,
    SOLD_WINDOWS,
    SORTS,
    STATUSES,
    Filters,
)

FORMATS = ("json", "jsonl", "csv", "table")


def _csv_list(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _price(value: str) -> int:
    """``450000``, ``450k``, ``1.2m`` or ``$1,200,000`` -> dollars."""
    text = value.strip().lower().replace("$", "").replace(",", "")
    scale = 1
    if text.endswith("k"):
        scale, text = 1_000, text[:-1]
    elif text.endswith("m"):
        scale, text = 1_000_000, text[:-1]
    try:
        return int(round(float(text) * scale))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a price: {value!r}") from None


def _add_output(parser: argparse.ArgumentParser, default: str = "json") -> None:
    parser.add_argument("--format", "-f", choices=FORMATS, default=default, help="output format")
    parser.add_argument("--output", "-o", help="write to this file instead of stdout")


def _add_common_filters(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("filters")
    group.add_argument("--min-price", type=_price, metavar="PRICE", help="e.g. 400000, 400k, 1.2m")
    group.add_argument("--max-price", type=_price, metavar="PRICE")
    group.add_argument("--beds", type=int, dest="min_beds", metavar="N", help="minimum bedrooms")
    group.add_argument("--max-beds", type=int, metavar="N")
    group.add_argument(
        "--baths", type=float, dest="min_baths", metavar="N", help="minimum bathrooms"
    )
    group.add_argument(
        "--filter",
        action="append",
        default=[],
        dest="extra",
        metavar="TOKEN",
        help="a raw filter token copied from a Redfin search URL (repeatable)",
    )
    group.add_argument(
        "--all",
        action="store_true",
        help="go past Redfin's 350-result cap by splitting the price range",
    )
    group.add_argument(
        "--max-requests",
        type=int,
        default=10,
        help="request budget for --all (default 10)",
    )
    group.add_argument("--limit", type=int, help="only output the first N results")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="redfin-scraper",
        description="Scrape Redfin homes for sale, sold homes, rentals, home details and "
        "market stats via the ScrapeUnblocker API.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--api-key", help="ScrapeUnblocker API key (default: $SCRAPEUNBLOCKER_KEY)")
    parser.add_argument("--retries", type=int, default=3, help="retries per request (default 3)")
    parser.add_argument(
        "--no-filter-check",
        action="store_true",
        help="return results even if Redfin ignored the filters",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="homes for sale or sold homes in a location")
    search.add_argument("location", help='"City, ST", a ZIP code or a Redfin search URL')
    _add_common_filters(search)
    group = search.add_argument_group("for-sale filters")
    group.add_argument(
        "--sold",
        choices=SOLD_WINDOWS,
        help="sold homes in this look-back window instead of homes for sale",
    )
    group.add_argument(
        "--type",
        type=_csv_list,
        default=[],
        dest="property_types",
        metavar="TYPES",
        help=f"comma-separated: {', '.join(PROPERTY_TYPES)}",
    )
    group.add_argument(
        "--status",
        type=_csv_list,
        default=[],
        dest="statuses",
        metavar="STATUSES",
        help=f"comma-separated: {', '.join(STATUSES)}",
    )
    group.add_argument("--min-sqft", type=int)
    group.add_argument("--max-sqft", type=int)
    group.add_argument("--min-lot", type=float, dest="min_lot_acres", metavar="ACRES")
    group.add_argument("--max-lot", type=float, dest="max_lot_acres", metavar="ACRES")
    group.add_argument("--min-year", type=int, dest="min_year_built", metavar="YEAR")
    group.add_argument("--max-year", type=int, dest="max_year_built", metavar="YEAR")
    group.add_argument("--max-hoa", type=int, help="maximum HOA dues per month")
    group.add_argument("--min-stories", type=int)
    group.add_argument("--keyword", help="words that must appear in the listing description")
    group.add_argument("--garage", action="store_true", help="only homes with a garage")
    group.add_argument(
        "--max-days",
        dest="max_days_on_market",
        metavar="AGE",
        help="listed within this long: 1d, 3d, 1wk, 2wk, 1mo, ...",
    )
    group.add_argument("--sort", choices=list(SORTS), default="recommended")
    _add_output(search)

    rentals = sub.add_parser("rentals", help="rental listings in a location")
    rentals.add_argument("location", help='"City, ST", a ZIP code or a Redfin search URL')
    _add_common_filters(rentals)
    group = rentals.add_argument_group("rental filters")
    group.add_argument(
        "--type",
        type=_csv_list,
        default=[],
        dest="property_types",
        metavar="TYPES",
        help=f"comma-separated: {', '.join(RENTAL_PROPERTY_TYPES)} (apartment = multifamily)",
    )
    group.add_argument("--dogs", action="store_true", dest="dogs_allowed", help="dogs allowed")
    group.add_argument("--cats", action="store_true", dest="cats_allowed", help="cats allowed")
    group.add_argument("--sort", choices=list(RENTAL_SORTS), default="recommended")
    _add_output(rentals)

    home = sub.add_parser("home", help="full details of homes by Redfin URL")
    home.add_argument("urls", nargs="+", metavar="URL", help="Redfin home URL(s) (.../home/<id>)")
    _add_output(home)

    market = sub.add_parser("market", help="housing-market stats for a location")
    market.add_argument("location", help='"City, ST", a ZIP code or a Redfin search URL')
    market.add_argument("--no-history", action="store_true", help="omit the monthly history")
    _add_output(market)

    locate = sub.add_parser("locate", help="find the Redfin search area for a place name")
    locate.add_argument("location", help='e.g. "Boise, ID" or "Capitol Hill, Seattle"')
    _add_output(locate)
    return parser


_FILTER_FIELDS = (
    "min_price",
    "max_price",
    "min_beds",
    "max_beds",
    "min_baths",
    "min_sqft",
    "max_sqft",
    "min_lot_acres",
    "max_lot_acres",
    "min_year_built",
    "max_year_built",
    "max_hoa",
    "min_stories",
    "property_types",
    "statuses",
    "sold",
    "keyword",
    "garage",
    "max_days_on_market",
    "dogs_allowed",
    "cats_allowed",
    "sort",
    "extra",
)


def filters_from_args(args: argparse.Namespace) -> Filters:
    """The :class:`Filters` a parsed ``search``/``rentals`` command line asks for."""
    values = {name: getattr(args, name) for name in _FILTER_FIELDS if hasattr(args, name)}
    return Filters(**{k: v for k, v in values.items() if v is not None})


def _emit(args: argparse.Namespace, payload: Any, items: Sequence[Any], columns, out: TextIO):
    if args.format == "json":
        write_json(payload, out)
    elif args.format == "jsonl":
        write_jsonl(items, out)
    elif args.format == "csv":
        write_csv(items, out)
    else:
        write_table(items, columns, out)


def run(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    scraper = RedfinScraper(
        api_key=args.api_key,
        max_retries=args.retries,
        check_filters=not args.no_filter_check,
    )
    if args.command in ("search", "rentals"):
        filters = filters_from_args(args)
        if args.command == "search":
            method = scraper.search_all if args.all else scraper.search
        else:
            method = scraper.rentals_all if args.all else scraper.rentals
        kwargs = {"max_requests": args.max_requests} if args.all else {}
        page = method(args.location, filters, **kwargs)
        items = page.homes if args.command == "search" else page.rentals
        if args.limit is not None:
            items = items[: args.limit]
            if args.command == "search":
                page.homes = items
            else:
                page.rentals = items
        columns = HOME_COLUMNS if args.command == "search" else RENTAL_COLUMNS
        _emit(args, page, items, columns, out)
        found = f"{len(items)} results"
        if page.total is not None:
            found += f", Redfin reports {page.total} matching"
        note = ""
        if page.capped:
            hint = "raise --max-requests" if args.all else "try --all"
            note = f" - more exist: {hint} or narrow the filters"
        err.write(f"{found}; {page.requests} request(s){note}\n")
        return 0
    if args.command == "home":
        details = (
            list(scraper.homes(args.urls)) if len(args.urls) > 1 else [scraper.home(args.urls[0])]
        )
        payload: Any = details if len(args.urls) > 1 else details[0]
        _emit(args, payload, details, (("url", 60), ("price", 11), ("status", 12)), out)
        if len(details) < len(args.urls):
            err.write(f"{len(args.urls) - len(details)} home(s) not found on Redfin\n")
        return 0
    if args.command == "market":
        stats = scraper.market(args.location)
        if args.no_history:
            stats.history = []
        _emit(args, stats, stats.history, (("month", 8), ("median_sale_price", 12)), out)
        return 0
    region = scraper.locate(args.location)
    _emit(args, region, [region], (("name", 24), ("type", 12), ("id", 8), ("url", 60)), out)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    out: TextIO = sys.stdout
    handle = None
    if args.output:
        handle = open(args.output, "w", encoding="utf-8", newline="")
        out = handle
    try:
        return run(args, out, sys.stderr)
    except (RedfinError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    finally:
        if handle is not None:
            handle.close()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
