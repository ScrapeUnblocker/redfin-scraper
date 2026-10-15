"""Write scraper results as JSON, JSON Lines, CSV or a quick text table."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Sequence
from typing import Any, TextIO


def as_dict(item: Any) -> dict[str, Any]:
    """A model (anything with ``to_dict``) or a plain dict, as a dict."""
    return item.to_dict() if hasattr(item, "to_dict") else dict(item)


def flatten(row: dict[str, Any]) -> dict[str, Any]:
    """One CSV row: lists of plain values joined with `` | ``, anything nested as JSON."""
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, list) and all(not isinstance(v, (dict, list)) for v in value):
            out[key] = " | ".join(str(v) for v in value)
        elif isinstance(value, (dict, list)):
            out[key] = json.dumps(value, ensure_ascii=False) if value else ""
        elif value is None:
            out[key] = ""
        else:
            out[key] = value
    return out


def write_json(data: Any, stream: TextIO) -> None:
    if isinstance(data, list):
        data = [as_dict(item) for item in data]
    elif hasattr(data, "to_dict"):
        data = data.to_dict()
    json.dump(data, stream, indent=2, ensure_ascii=False)
    stream.write("\n")


def write_jsonl(items: Iterable[Any], stream: TextIO) -> int:
    count = 0
    for item in items:
        stream.write(json.dumps(as_dict(item), ensure_ascii=False) + "\n")
        count += 1
    return count


def write_csv(items: Sequence[Any], stream: TextIO) -> int:
    rows = [flatten(as_dict(item)) for item in items]
    if not rows:
        return 0
    fields: list[str] = []
    for row in rows:
        fields.extend(key for key in row if key not in fields)
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return len(rows)


def _cell(value: Any, width: int) -> str:
    if value is None or value == "":
        text = "-"
    elif isinstance(value, float) and value.is_integer():
        text = str(int(value))
    elif isinstance(value, int) and not isinstance(value, bool) and value >= 10_000:
        text = f"{value:,}"
    else:
        text = str(value)
    return text if len(text) <= width else text[: width - 1] + "~"


def write_table(items: Sequence[Any], columns: Sequence[tuple[str, int]], stream: TextIO) -> int:
    """A fixed-width text table of ``columns`` (field name, width) for a terminal."""
    rows = [as_dict(item) for item in items]
    columns = [(name, max(width, len(name))) for name, width in columns]
    stream.write("  ".join(name.ljust(width) for name, width in columns).rstrip() + "\n")
    stream.write("  ".join("-" * width for _, width in columns) + "\n")
    for row in rows:
        cells = [_cell(row.get(name), width).ljust(width) for name, width in columns]
        stream.write("  ".join(cells).rstrip() + "\n")
    return len(rows)


HOME_COLUMNS = (
    ("price", 11),
    ("beds", 4),
    ("baths", 5),
    ("sqft", 6),
    ("property_type", 12),
    ("status", 12),
    ("address", 30),
    ("city", 14),
    ("zip", 5),
)
RENTAL_COLUMNS = (
    ("rent_min", 8),
    ("rent_max", 8),
    ("beds_min", 4),
    ("beds_max", 4),
    ("property_type", 11),
    ("available_units", 5),
    ("name", 24),
    ("address", 28),
    ("zip", 5),
)
