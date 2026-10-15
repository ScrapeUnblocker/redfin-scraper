"""Shared test helpers: real (trimmed) Redfin page data and a fake ScrapeUnblocker client.

The fixtures in ``tests/fixtures/`` are API responses captured from real Redfin
pages, cut down to a few homes and with agent names and phone numbers replaced.
:func:`page_html` wraps them back into the script block Redfin pages carry, so the
parsers run on the same structure they see in production. No test calls the API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def page_html(entries: dict[str, Any]) -> str:
    """A minimal Redfin page whose server state holds ``entries`` (API path -> JSON)."""
    cache = {
        path: {"res": {"text": "{}&&" + json.dumps(data)}, "loaded": True}
        for path, data in entries.items()
    }
    state = {"ReactServerAgent.cache": {"dataCache": cache}}
    return (
        "<!DOCTYPE html><html><head><title>Redfin</title></head><body>"
        "<script>(function (root) {\nroot.__reactServerState || (root.__reactServerState = {});\n"
        f"root.__reactServerState.InitialContext = {json.dumps(state)};\n"
        "}(this));</script></body></html>"
    )


def fixture_html(name: str) -> str:
    return page_html(load_fixture(name))


def search_html(
    prices: list[int | None],
    total: int | None,
    start_id: int = 1,
    applied: str | None = None,
) -> str:
    """A synthetic for-sale search page with one home per price."""
    homes = [
        {
            "propertyId": start_id + i,
            "url": f"/TX/Austin/{start_id + i}-Main-St-78701/home/{start_id + i}",
            "mlsStatus": "Active",
            "price": {"value": price, "level": 1} if price is not None else {"level": 3},
            "uiPropertyType": 1,
        }
        for i, price in enumerate(prices)
    ]
    region = "/stingray/api/region?region_id=30818&region_type=6"
    if applied:
        region += "&f=" + applied
    entries: dict[str, Any] = {
        "/stingray/api/gis?region_id=30818&region_type=6&num_homes=350": {
            "version": 1,
            "errorMessage": "Success",
            "resultCode": 0,
            "payload": {"homes": homes},
        },
        region: {"version": 1},
    }
    if total is not None:
        entries["/stingray/api/gis-aggregates?region_id=30818"] = {
            "version": 1,
            "errorMessage": "Success",
            "resultCode": 0,
            "payload": {"numProperties": total},
        }
    return page_html(entries)


class FakeClient:
    """Stands in for ``scrapeunblocker.Client``; ``responder(url, kwargs)`` returns HTML.

    A responder may also return an exception instance, which is raised instead.
    """

    def __init__(self, responder: Callable[[str, dict[str, Any]], Any]):
        self.responder = responder
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_page_source(self, url: str, **kwargs: Any) -> str:
        self.calls.append((url, kwargs))
        result = self.responder(url, kwargs)
        if isinstance(result, BaseException):
            raise result
        return result


@pytest.fixture
def make_scraper():
    """Build a :class:`RedfinScraper` around a :class:`FakeClient` (no sleeping)."""
    from redfin_scraper import RedfinScraper

    def build(responder, **kwargs):
        client = FakeClient(responder)
        sleeps: list[float] = []
        scraper = RedfinScraper(client=client, sleep=sleeps.append, **kwargs)
        scraper.sleeps = sleeps  # type: ignore[attr-defined]
        return scraper, client

    return build
