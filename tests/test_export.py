from __future__ import annotations

import csv
import io
import json

from redfin_scraper.export import flatten, write_csv, write_json, write_jsonl, write_table
from redfin_scraper.models import Home


def test_flatten():
    row = flatten({"a": [1, 2], "b": [{"x": 1}], "c": None, "d": {}, "e": "z"})
    assert row == {"a": "1 | 2", "b": '[{"x": 1}]', "c": "", "d": "", "e": "z"}


def test_write_csv_union_of_columns():
    stream = io.StringIO()
    count = write_csv([{"a": 1}, {"a": 2, "b": 3}], stream)
    assert count == 2
    rows = list(csv.DictReader(io.StringIO(stream.getvalue())))
    assert rows == [{"a": "1", "b": ""}, {"a": "2", "b": "3"}]


def test_write_csv_empty():
    stream = io.StringIO()
    assert write_csv([], stream) == 0
    assert stream.getvalue() == ""


def test_write_json_and_jsonl_models():
    homes = [Home(property_id=1, price=500_000, tags=["POOL"])]
    stream = io.StringIO()
    write_json(homes, stream)
    assert json.loads(stream.getvalue())[0]["tags"] == ["POOL"]
    stream = io.StringIO()
    assert write_jsonl(homes, stream) == 1
    assert json.loads(stream.getvalue())["price"] == 500_000


def test_write_table_formats_cells():
    stream = io.StringIO()
    homes = [Home(price=1_250_000, beds=3.0, address="1 A Very Long Street Name That Goes On")]
    write_table(homes, [("price", 10), ("beds", 4), ("address", 12), ("zip", 5)], stream)
    lines = stream.getvalue().splitlines()
    assert lines[0].split() == ["price", "beds", "address", "zip"]
    assert lines[2].split()[:2] == ["1,250,000", "3"]
    assert "1 A Very Lo~" in lines[2]
    assert lines[2].rstrip().endswith("-")
