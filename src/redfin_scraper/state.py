"""Read the data Redfin embeds in every page it renders on the server.

Redfin's pages are React apps rendered server-side. Before the HTML goes out, the
server calls Redfin's own JSON APIs (the map search, the home details sections, the
market trends, ...) and inlines every response in a script block::

    root.__reactServerState.InitialContext = {"ReactServerAgent.cache":
        {"dataCache": {"/stingray/api/gis?...": {"res": {"text": "{}&&{...}"}}, ...}}}

so the browser does not have to call them again. :func:`extract_data_cache` pulls
that cache out of the HTML and decodes each response, which gives the scraper the
same structured data the page itself is drawn from - no CSS selectors involved.
"""

from __future__ import annotations

import json
import re
from typing import Any

_MARKER = re.compile(r"__reactServerState\.InitialContext\s*=\s*")
#: Redfin prefixes its JSON responses with ``{}&&`` (an old anti-JSON-hijacking guard).
_JSON_GUARD = "{}&&"


class RedfinError(Exception):
    """Base class for every error raised by this package."""


class RedfinParseError(RedfinError):
    """The page did not carry the data the scraper expected."""


class RedfinNotFoundError(RedfinError):
    """The location, home or page does not exist on Redfin."""


class FilterRejectedError(RedfinError):
    """Redfin ignored the requested filters.

    When any single filter token is unknown or malformed, Redfin silently drops the
    *whole* filter string and shows the unfiltered search. The scraper checks the
    filter string Redfin echoes back and raises this instead of returning
    unfiltered results that look filtered.
    """


def extract_data_cache(html: str) -> dict[str, Any]:
    """Map each API path the server called to its decoded JSON response.

    Raises :class:`RedfinParseError` when the page has no server state at all
    (an error page, a challenge page, or not a Redfin page).
    """
    match = _MARKER.search(html or "")
    if not match:
        raise RedfinParseError("page has no Redfin server state (InitialContext)")
    try:
        state, _ = json.JSONDecoder().raw_decode(html, match.end())
    except ValueError as exc:
        raise RedfinParseError(f"could not decode Redfin server state: {exc}") from exc
    cache = (state.get("ReactServerAgent.cache") or {}).get("dataCache") or {}
    out: dict[str, Any] = {}
    for path, entry in cache.items():
        text = ((entry or {}).get("res") or {}).get("text")
        if not text:
            continue
        if text.startswith(_JSON_GUARD):
            text = text[len(_JSON_GUARD) :]
        try:
            out[path] = json.loads(text)
        except ValueError:
            continue
    return out


class PageData:
    """The decoded API responses embedded in one Redfin page."""

    def __init__(self, cache: dict[str, Any]):
        self.cache = cache

    @classmethod
    def from_html(cls, html: str) -> PageData:
        return cls(extract_data_cache(html))

    def keys(self, prefix: str) -> list[str]:
        """API paths (with their query strings) that start with ``prefix``."""
        return [key for key in self.cache if key.startswith(prefix)]

    def payload(self, prefix: str, contains: str = "") -> Any:
        """The ``payload`` of the first response whose path starts with ``prefix``.

        ``contains`` narrows the match to paths that also contain that text.
        Returns ``None`` when there is no such response or it carried no payload.
        """
        for key in self.keys(prefix):
            if contains and contains not in key:
                continue
            data = self.cache[key]
            if isinstance(data, dict) and "payload" in data:
                return data["payload"]
            if isinstance(data, dict) and "errorMessage" in data:
                return None  # an API envelope that came back without a payload
            return data
        return None
