from __future__ import annotations

import argparse
import csv
import io
import json

import pytest
from conftest import FakeClient, fixture_html

from redfin_scraper import RedfinScraper, cli


def _parse(*argv: str) -> argparse.Namespace:
    return cli.build_parser().parse_args(list(argv))


def test_search_args_become_filters():
    args = _parse(
        "search",
        "Austin, TX",
        "--min-price",
        "400k",
        "--max-price",
        "$1.2m",
        "--beds",
        "3",
        "--baths",
        "2",
        "--type",
        "house,townhouse",
        "--status",
        "active",
        "--max-hoa",
        "250",
        "--min-lot",
        "0.25",
        "--keyword",
        "pool",
        "--garage",
        "--max-days",
        "1wk",
        "--sort",
        "newest",
        "--filter",
        "include=forsale+mlsfsbo",
    )
    filters = cli.filters_from_args(args)
    assert filters.min_price == 400_000
    assert filters.max_price == 1_200_000
    assert (filters.min_beds, filters.min_baths) == (3, 2.0)
    assert filters.property_types == ["house", "townhouse"]
    assert filters.statuses == ["active"]
    assert filters.max_hoa == 250
    assert filters.min_lot_acres == 0.25
    assert filters.keyword == "pool"
    assert filters.garage is True
    assert filters.max_days_on_market == "1wk"
    assert filters.sort == "newest"
    assert filters.extra == ["include=forsale+mlsfsbo"]


def test_sold_and_defaults():
    args = _parse("search", "78704", "--sold", "6mo")
    filters = cli.filters_from_args(args)
    assert filters.sold == "6mo"
    assert filters.tokens() == ["include=sold-6mo"]
    assert args.format == "json" and args.all is False and args.max_requests == 10


def test_rentals_args():
    args = _parse("rentals", "Denver, CO", "--max-price", "2500", "--type", "apartment", "--dogs")
    filters = cli.filters_from_args(args)
    assert filters.tokens(rentals=True) == [
        "property-type=multifamily",
        "max-price=2500",
        "dogs-allowed",
    ]


@pytest.mark.parametrize("argv", [["search"], ["search", "x", "--sold", "2wk"], ["frobnicate"]])
def test_bad_arguments_exit(argv):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(argv)


def test_bad_price_is_rejected():
    with pytest.raises(SystemExit):
        _parse("search", "78704", "--max-price", "cheap")


@pytest.fixture
def offline(monkeypatch):
    """Point the CLI at a fake client that serves fixture pages."""

    def install(responder):
        client = FakeClient(responder)

        def factory(**kwargs):
            kwargs.pop("api_key", None)
            return RedfinScraper(client=client, sleep=lambda s: None, **kwargs)

        monkeypatch.setattr(cli, "RedfinScraper", factory)
        return client

    return install


def test_search_json(offline, capsys):
    offline(lambda url, kw: fixture_html("search_zip.json"))
    assert cli.main(["search", "78704"]) == 0
    out, err = capsys.readouterr()
    data = json.loads(out)
    assert data["region"]["name"] == "78704"
    assert len(data["homes"]) == 2
    assert "2 results" in err


def test_search_csv_with_limit(offline, capsys):
    offline(lambda url, kw: fixture_html("search_sale.json"))
    assert cli.main(["search", "78704", "--format", "csv", "--limit", "2"]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == 2
    assert rows[0]["price"] == "699000"
    assert rows[0]["badges"] == "Open House"


def test_search_table(offline, capsys):
    offline(lambda url, kw: fixture_html("search_zip.json"))
    assert cli.main(["search", "78704", "-f", "table"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0].startswith("price")
    assert "2107 Arpdale St" in out


def test_rentals_jsonl(offline, capsys):
    offline(lambda url, kw: fixture_html("rentals.json"))
    assert cli.main(["rentals", "78704", "-f", "jsonl"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["rent_min"] == 450


def test_home_and_market(offline, capsys):
    offline(lambda url, kw: fixture_html("home_active.json"))
    assert cli.main(["home", "/TX/Austin/7500-Lobelia-Dr-78729/home/32797952"]) == 0
    assert json.loads(capsys.readouterr().out)["redfin_estimate"] == 650963

    offline(lambda url, kw: fixture_html("search_sale.json"))
    assert cli.main(["market", "78704", "--no-history"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["median_sale_price"] == 526_000
    assert data["history"] == []


def test_output_file(offline, tmp_path, capsys):
    offline(lambda url, kw: fixture_html("search_zip.json"))
    target = tmp_path / "homes.csv"
    assert cli.main(["search", "78704", "-f", "csv", "-o", str(target)]) == 0
    assert target.read_text(encoding="utf-8").startswith("property_id,")
    assert capsys.readouterr().out == ""


def test_errors_exit_with_1(offline, capsys):
    offline(lambda url, kw: fixture_html("search_zip.json"))
    assert cli.main(["home", "https://www.redfin.com/city/30818/TX/Austin"]) == 1
    assert "not a Redfin home URL" in capsys.readouterr().err
