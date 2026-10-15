"""Scrape Redfin through the ScrapeUnblocker ``getPageSource`` API.

:class:`RedfinScraper` builds the Redfin URL for a search or a home, fetches the
rendered page through ScrapeUnblocker and parses the data Redfin embeds in it.

* A search returns at most :data:`MAX_RESULTS` (350) homes - that is Redfin's own
  cap, and ``page-2`` style URLs return the same 350. :meth:`RedfinScraper.search_all`
  gets past it by splitting the price range into bands that each fit under the cap
  (one request per band, deduplicated by property ID).
* A free-text location such as ``"Boise, ID"`` is resolved by typing it into Redfin's
  own search box with browser steps (one request); ZIP codes and Redfin URLs need no
  lookup.
* Timeouts, transient API errors and pages that come back without their data are
  retried with doubling backoff.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from typing import Any, Callable

from .models import HomeDetails, Market, Region, RentalDetails, RentalPage, SearchPage
from .parsing import (
    is_search_page,
    parse_home_page,
    parse_market,
    parse_region,
    parse_rentals_page,
    parse_search_page,
)
from .state import FilterRejectedError, PageData, RedfinNotFoundError, RedfinParseError
from .urls import (
    BASE_URL,
    Filters,
    SearchTarget,
    home_url,
    merge_tokens,
    parse_location,
    search_url,
)

_TRANSIENT_NAMES = (
    "UpstreamOutageError",
    "RateLimitError",
    "ScrapeTimeoutError",
    "BrowserTimeoutError",
    "BlockedError",
    "ServerError",
    "ConnectionError",
    "StepFailedError",
)
_NOT_FOUND_NAMES = ("TargetNotFoundError", "NotFoundError")

#: Redfin's search box on its home page.
SEARCH_BOX = "#search-box-input"


def lookup_steps(query: str) -> list[dict[str, Any]]:
    """Browser steps that type ``query`` into Redfin's search box and open the result."""
    return [
        {"action": "wait_for", "selector": SEARCH_BOX, "timeout_ms": 15000},
        {"action": "type", "selector": SEARCH_BOX, "value": query},
        {"action": "wait", "value": 2500},  # let the suggestions load
        {"action": "press_key", "value": "Enter"},
        {"action": "wait", "value": 6000},  # the search page loads
    ]


def _is_named(error: BaseException, *names: str) -> bool:
    return any(cls.__name__ in names for cls in type(error).__mro__)


def _key(item: Any) -> Any:
    return getattr(item, "property_id", None) or getattr(item, "url", None) or id(item)


def unique(items: Iterable[Any]) -> list[Any]:
    """Drop repeated homes/rentals (same property ID), keeping the first one seen."""
    seen: set[Any] = set()
    out = []
    for item in items:
        key = _key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def split_price(prices: Sequence[int | None], low: int | None, high: int | None):
    """A price that splits a capped price band roughly in half, or ``None``.

    Uses the median of the prices Redfin returned for the band; the two halves are
    ``low..mid`` and ``mid+1..high``.
    """
    values = sorted(p for p in prices if p is not None)
    if len(values) < 2:
        return None
    mid = values[len(values) // 2]
    if high is not None:
        mid = min(mid, high - 1)
    if mid < (low or 0):
        return None
    return mid


class RedfinScraper:
    """Search Redfin homes for sale, sold homes and rentals, and read home pages.

    Args:
        api_key: Your ScrapeUnblocker API key. Defaults to the
            ``SCRAPEUNBLOCKER_KEY`` environment variable (read by the SDK).
        client: A ready ``scrapeunblocker.Client`` (or anything with a compatible
            ``get_page_source``); handy for tests.
        proxy_country: Country to route requests through. Redfin is a US site.
        max_retries: Extra attempts for a request that fails transiently.
        backoff: Seconds before the first retry; doubles on each retry.
        check_filters: Raise :class:`FilterRejectedError` when Redfin ignores the
            filters (see that class). Set ``False`` to get the page anyway.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: Any = None,
        proxy_country: str = "US",
        max_retries: int = 3,
        backoff: float = 2.0,
        timeout: float = 180.0,
        check_filters: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if client is None:
            from scrapeunblocker import Client

            client = Client(api_key=api_key, timeout=timeout)
        self.client = client
        self.proxy_country = proxy_country
        self.max_retries = max_retries
        self.backoff = backoff
        self.check_filters = check_filters
        self._sleep = sleep
        self._locations: dict[str, SearchTarget] = {}
        #: API requests made by this scraper so far (each one is a billed call).
        self.requests = 0

    # -- fetching -------------------------------------------------------------------

    def fetch(self, url: str, steps: list[dict[str, Any]] | None = None) -> str:
        """The rendered HTML of a Redfin page, retrying transient failures."""
        attempt = 0
        while True:
            try:
                kwargs: dict[str, Any] = {"proxy_country": self.proxy_country}
                if steps:
                    kwargs["steps"] = steps
                self.requests += 1
                html = self.client.get_page_source(url, **kwargs)
                if not isinstance(html, str) or "__reactServerState" not in html:
                    raise RedfinParseError(f"{url} did not return a rendered Redfin page")
                return html
            except Exception as exc:
                if _is_named(exc, *_NOT_FOUND_NAMES):
                    raise RedfinNotFoundError(f"Redfin has no page at {url}") from exc
                retryable = isinstance(exc, RedfinParseError) or _is_named(exc, *_TRANSIENT_NAMES)
                if not retryable or attempt >= self.max_retries:
                    raise
                self._sleep(self.backoff * (2**attempt))
                attempt += 1

    # -- locations ------------------------------------------------------------------

    def _resolve(self, location: str) -> tuple[SearchTarget, str | None]:
        """The search target for ``location`` and, for a fresh lookup, its page HTML."""
        target = parse_location(location)
        if target is not None:
            return target, None
        key = " ".join(location.lower().split())
        if not key:
            raise ValueError("location is empty")
        if key in self._locations:
            return self._locations[key], None
        html = self.fetch(BASE_URL + "/", steps=lookup_steps(location.strip()))
        if not is_search_page(html):
            raise RedfinNotFoundError(
                f"Redfin's search box did not open a search area for {location!r}; "
                "try 'City, ST', a ZIP code or a Redfin search URL"
            )
        region = parse_region(PageData.from_html(html))
        if region is None or not region.url:
            raise RedfinNotFoundError(
                f"could not read the search area Redfin chose for {location!r}"
            )
        target = parse_location(region.url)
        assert target is not None
        self._locations[key] = target
        return target, html

    def locate(self, location: str) -> Region:
        """The Redfin search area for a city/neighborhood name, ZIP code or URL."""
        target, html = self._resolve(location)
        if html is None:
            html = self.fetch(BASE_URL + target.region_path)
        region = parse_region(PageData.from_html(html))
        if region is None:
            raise RedfinParseError(f"no search area data for {location!r}")
        return region

    # -- searches -------------------------------------------------------------------

    def _check(self, tokens: list[str], applied: str | None, page_html: str, url: str) -> None:
        if not self.check_filters or not tokens or applied:
            return
        if not PageData.from_html(page_html).keys("/stingray/api/region?"):
            return  # nothing to verify against
        raise FilterRejectedError(
            f"Redfin ignored the filters {','.join(tokens)!r} - one unknown or malformed "
            f"filter makes it drop all of them ({url})"
        )

    def _search_once(
        self, target: SearchTarget, filters: Filters, lookup_html: str | None = None
    ) -> SearchPage:
        tokens = merge_tokens(target.tokens, filters.tokens())
        url = search_url(target, filters)
        before = self.requests
        html = lookup_html if (lookup_html is not None and not tokens) else self.fetch(url)
        page = parse_search_page(html, url)
        self._check(tokens, page.applied_filters, html, url)
        page.requests = self.requests - before
        return page

    def _rentals_once(self, target: SearchTarget, filters: Filters) -> RentalPage:
        tokens = merge_tokens(target.tokens, filters.tokens(rentals=True))
        url = search_url(target, filters, rentals=True)
        before = self.requests
        html = self.fetch(url)
        page = parse_rentals_page(html, url)
        self._check(tokens, page.applied_filters, html, url)
        page.requests = self.requests - before
        return page

    def search(self, location: str, filters: Filters | None = None, **kwargs: Any) -> SearchPage:
        """Homes for sale (or sold, with ``Filters(sold="3mo")``) in a location.

        ``location`` is a city/neighborhood name (``"Austin, TX"``), a ZIP code or a
        Redfin search URL (its filters are kept; ``filters`` override them). Keyword
        arguments are a shortcut for :class:`Filters` fields. Returns up to
        :data:`MAX_RESULTS` homes; see :meth:`search_all` for more.
        """
        filters = filters or Filters(**kwargs)
        before = self.requests
        target, lookup_html = self._resolve(location)
        if target.rentals:
            raise ValueError("that is a rentals search URL - use rentals() for it")
        page = self._search_once(target, filters, lookup_html)
        page.requests = self.requests - before
        return page

    def rentals(self, location: str, filters: Filters | None = None, **kwargs: Any) -> RentalPage:
        """Rental listings in a location (up to :data:`MAX_RESULTS`; see :meth:`rentals_all`)."""
        filters = filters or Filters(**kwargs)
        before = self.requests
        target, _ = self._resolve(location)
        page = self._rentals_once(target, filters)
        page.requests = self.requests - before
        return page

    def _sweep(self, first, fetch_band, items_of, price_of, filters: Filters, max_requests: int):
        """Split capped price bands until everything is collected or the budget is spent."""
        collected = list(items_of(first))
        spent = first.requests
        queue = deque([(filters.min_price, filters.max_price, items_of(first))])
        while queue and spent < max_requests:
            low, high, sample = queue.popleft()
            mid = split_price([price_of(item) for item in sample], low, high)
            if mid is None:
                continue
            for band_low, band_high in ((low, mid), (mid + 1, high)):
                if spent >= max_requests:
                    break
                page = fetch_band(filters.with_price(band_low, band_high))
                spent += page.requests
                collected.extend(items_of(page))
                if page.capped:
                    queue.append((band_low, band_high, items_of(page)))
        return unique(collected), spent

    def search_all(
        self,
        location: str,
        filters: Filters | None = None,
        max_requests: int = 10,
        **kwargs: Any,
    ) -> SearchPage:
        """Like :meth:`search`, but past the 350-home cap by splitting the price range.

        Stops after ``max_requests`` API requests. The result's ``capped`` flag says
        whether Redfin reports homes that were still not collected.
        """
        filters = filters or Filters(**kwargs)
        first = self.search(location, filters)
        if not first.capped or max_requests <= first.requests:
            return first
        target, _ = self._resolve(location)
        homes, spent = self._sweep(
            first,
            lambda band: self._search_once(target, band),
            lambda page: page.homes,
            lambda home: home.price,
            filters,
            max_requests,
        )
        first.homes = homes
        first.requests = spent
        first.capped = first.total is not None and len(homes) < first.total
        return first

    def rentals_all(
        self,
        location: str,
        filters: Filters | None = None,
        max_requests: int = 10,
        **kwargs: Any,
    ) -> RentalPage:
        """Like :meth:`rentals`, but past the cap by splitting the rent range."""
        filters = filters or Filters(**kwargs)
        first = self.rentals(location, filters)
        if not first.capped or max_requests <= first.requests:
            return first
        target, _ = self._resolve(location)
        rentals, spent = self._sweep(
            first,
            lambda band: self._rentals_once(target, band),
            lambda page: page.rentals,
            lambda rental: rental.rent_min,
            filters,
            max_requests,
        )
        first.rentals = rentals
        first.requests = spent
        first.capped = first.total is not None and len(rentals) < first.total
        return first

    # -- pages ----------------------------------------------------------------------

    def home(self, url: str) -> HomeDetails | RentalDetails:
        """Full details of a home (or a rental) from its Redfin URL."""
        full = home_url(url)
        return parse_home_page(self.fetch(full), full)

    def homes(self, urls: Iterable[str]) -> Iterator[HomeDetails | RentalDetails]:
        """:meth:`home` for several URLs, skipping homes Redfin no longer has."""
        for url in urls:
            try:
                yield self.home(url)
            except RedfinNotFoundError:
                continue

    def market(self, location: str) -> Market:
        """Housing-market stats for a search area (median prices, sale-to-list, history)."""
        target, lookup_html = self._resolve(location)
        html = lookup_html or self.fetch(BASE_URL + target.region_path)
        return parse_market(html)
