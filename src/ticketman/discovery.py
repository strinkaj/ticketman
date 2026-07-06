"""Ticketmaster Discovery API client.

The Discovery API is Ticketmaster's official, public, read-only event catalog.
Register a free consumer key at https://developer.ticketmaster.com. This client
does event search and event lookup, then parses the response into the Event
model in models.py.

What this API gives you:
  - Event identity, url, venue, city, date, and status (onsale/offsale/etc).
  - The sales schedule: the public on-sale window and every presale window,
    each with a name and start/end time. This is the core of the presale
    strategy.
  - Price ranges (min and max) per event.

What it does NOT give you:
  - Seat-by-seat resale listings with individual prices. That is partner and
    commerce API access that individuals do not get. The resale watcher works
    off price-range and status changes, which is a proxy, not a live seat feed.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

import httpx

from ticketman.models import Event, PresaleWindow, SalesWindow

log = logging.getLogger(__name__)

BASE = "https://app.ticketmaster.com/discovery/v2"

# Event id patterns from a Ticketmaster URL, for example:
#   https://www.ticketmaster.com/event/0B00612D7C1E5A3F
#   https://www.ticketmaster.com/artist-name-city/event/0B00612D7C1E5A3F
_EVENT_ID_RE = re.compile(r"/event/([A-Za-z0-9]+)")


def extract_event_id(url_or_id: str) -> str:
    """Return the event id from a full Ticketmaster URL or a bare id."""
    match = _EVENT_ID_RE.search(url_or_id)
    if match:
        return match.group(1)
    # Assume the caller passed a bare id already.
    if re.fullmatch(r"[A-Za-z0-9]+", url_or_id):
        return url_or_id
    raise ValueError(f"Could not extract an event id from: {url_or_id}")


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO 8601 timestamp from the API into an aware datetime."""
    if not value:
        return None
    try:
        # The API uses a trailing Z for UTC, which fromisoformat rejects on
        # older Pythons. Normalize it.
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        log.debug("Could not parse datetime: %s", value)
        return None


def parse_event(raw: dict) -> Event:
    """Build an Event from a single Discovery API event object.

    Written defensively: nearly every field is optional in real responses.
    """
    dates = raw.get("dates", {})
    start = dates.get("start", {})
    status = dates.get("status", {}).get("code", "")

    sales = raw.get("sales", {})
    public = sales.get("public", {})
    public_sale = None
    if public.get("startDateTime") or public.get("endDateTime"):
        public_sale = SalesWindow(
            start=_parse_dt(public.get("startDateTime")),
            end=_parse_dt(public.get("endDateTime")),
        )

    presales = []
    for ps in sales.get("presales", []) or []:
        presales.append(
            PresaleWindow(
                name=ps.get("name", "Presale"),
                start=_parse_dt(ps.get("startDateTime")),
                end=_parse_dt(ps.get("endDateTime")),
            )
        )

    venue_name = city = state = ""
    capacity = None
    tz = ""
    venues = raw.get("_embedded", {}).get("venues", [])
    if venues:
        v = venues[0]
        venue_name = v.get("name", "")
        city = v.get("city", {}).get("name", "")
        state = v.get("state", {}).get("stateCode", "")
        tz = v.get("timezone", "")
        # Capacity is present only on some venues.
        cap = v.get("capacity")
        if isinstance(cap, int):
            capacity = cap
        elif isinstance(cap, str) and cap.isdigit():
            capacity = int(cap)

    segment = genre = ""
    classifications = raw.get("classifications", [])
    if classifications:
        c = classifications[0]
        segment = c.get("segment", {}).get("name", "")
        genre = c.get("genre", {}).get("name", "")

    price_min = price_max = None
    currency = "USD"
    price_ranges = raw.get("priceRanges", [])
    if price_ranges:
        mins = [pr["min"] for pr in price_ranges if pr.get("min") is not None]
        maxes = [pr["max"] for pr in price_ranges if pr.get("max") is not None]
        if mins:
            price_min = min(mins)
        if maxes:
            price_max = max(maxes)
        currency = price_ranges[0].get("currency", "USD")

    return Event(
        id=raw.get("id", ""),
        name=raw.get("name", ""),
        url=raw.get("url", ""),
        status=status,
        start_local=f"{start.get('localDate', '')} {start.get('localTime', '')}".strip(),
        start_utc=_parse_dt(start.get("dateTime")),
        timezone=tz,
        venue_name=venue_name,
        city=city,
        state=state,
        capacity=capacity,
        segment=segment,
        genre=genre,
        price_min=price_min,
        price_max=price_max,
        currency=currency,
        presales=presales,
        public_sale=public_sale,
    )


class DiscoveryClient:
    """Thin synchronous client over the Discovery API."""

    def __init__(self, api_key: str, country_code: str = "US", timeout: float = 15.0) -> None:
        if not api_key:
            raise ValueError(
                "No Ticketmaster API key. Set TM_API_KEY or add it to config.yaml. "
                "Get a free key at https://developer.ticketmaster.com."
            )
        self.api_key = api_key
        self.country_code = country_code
        self._client = httpx.Client(timeout=timeout)

    def _get(self, path: str, params: dict) -> dict:
        params = {**params, "apikey": self.api_key}
        resp = self._client.get(f"{BASE}/{path}", params=params)
        if resp.status_code == 401:
            raise RuntimeError("Ticketmaster rejected the API key (401). Check TM_API_KEY.")
        if resp.status_code == 429:
            raise RuntimeError("Rate limited by Ticketmaster (429). Slow the poll interval.")
        resp.raise_for_status()
        return resp.json()

    def search_events(
        self, keyword: str, *, city: str | None = None, size: int = 20
    ) -> list[Event]:
        """Search events by keyword, optionally scoped to a city."""
        params: dict = {
            "keyword": keyword,
            "countryCode": self.country_code,
            "size": size,
            "sort": "date,asc",
        }
        if city:
            params["city"] = city
        data = self._get("events.json", params)
        events = data.get("_embedded", {}).get("events", [])
        return [parse_event(e) for e in events]

    def get_event(self, url_or_id: str) -> Event:
        """Fetch a single event by URL or id."""
        event_id = extract_event_id(url_or_id)
        data = self._get(f"events/{event_id}.json", {})
        return parse_event(data)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DiscoveryClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
