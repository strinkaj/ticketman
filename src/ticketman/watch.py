"""Event watcher.

Polls the Discovery API for one event and fires a desktop alert when something
you care about changes: a presale or the public on-sale opens, the event status
flips to onsale, or the price range moves (a proxy for inventory or resale
activity, since the public API does not expose live seat listings).

This is a notifier, not a buyer. When it alerts, you go buy, by hand, on your
own account.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from ticketman.discovery import DiscoveryClient
from ticketman.models import Event
from ticketman.notify import Notifier

log = logging.getLogger(__name__)


@dataclass
class WatchState:
    """Snapshot of what we last saw, to detect transitions."""

    status: str = ""
    price_max: float | None = None
    open_windows: frozenset[str] = frozenset()


def _open_window_names(event: Event, now: datetime) -> frozenset[str]:
    """Names of sale windows currently open at `now`."""
    names = set()
    for ps in event.presales:
        if ps.start and ps.start <= now and (ps.end is None or now <= ps.end):
            names.add(ps.name)
    if event.public_sale and event.public_sale.start:
        s = event.public_sale.start
        e = event.public_sale.end
        if s <= now and (e is None or now <= e):
            names.add("General public on-sale")
    return frozenset(names)


def _next_window(event: Event, now: datetime) -> tuple[str, datetime] | None:
    """The soonest future sale window, if any."""
    upcoming: list[tuple[str, datetime]] = []
    for ps in event.presales:
        if ps.start and ps.start > now:
            upcoming.append((ps.name, ps.start))
    if event.public_sale and event.public_sale.start and event.public_sale.start > now:
        upcoming.append(("General public on-sale", event.public_sale.start))
    if not upcoming:
        return None
    return min(upcoming, key=lambda x: x[1])


def watch_event(
    client: DiscoveryClient,
    notifier: Notifier,
    url_or_id: str,
    *,
    interval: float = 60.0,
    max_polls: int | None = None,
) -> None:
    """Poll an event and alert on meaningful changes.

    Runs until interrupted (Ctrl-C) or until max_polls is reached (used in
    tests). interval is the seconds between polls; keep it at 30 or higher to
    stay well under Discovery API rate limits.
    """
    state = WatchState()
    first = True
    polls = 0

    while True:
        now = datetime.now(UTC)
        try:
            event = client.get_event(url_or_id)
        except Exception as e:  # network hiccup, keep going
            log.warning("Poll failed: %s (retrying in %.0fs)", e, interval)
            time.sleep(interval)
            continue

        open_now = _open_window_names(event, now)

        if first:
            log.info("Watching '%s' (%s)", event.name, event.status or "status unknown")
            nxt = _next_window(event, now)
            if nxt:
                mins = (nxt[1] - now).total_seconds() / 60.0
                log.info("Next window: %s at %s (in %.0f min)", nxt[0], nxt[1].isoformat(), mins)
            if open_now:
                notifier.notify(
                    "Tickets available now",
                    f"{event.name}: {', '.join(sorted(open_now))} is open. Go buy.",
                )
        else:
            newly_open = open_now - state.open_windows
            if newly_open:
                notifier.notify(
                    "Sale window opened",
                    f"{event.name}: {', '.join(sorted(newly_open))} just opened. Go buy.",
                )
            if event.status == "onsale" and state.status != "onsale":
                notifier.notify("Event on sale", f"{event.name} is now on sale.")
            if (
                event.price_max is not None
                and state.price_max is not None
                and event.price_max < state.price_max
            ):
                notifier.notify(
                    "Price dropped",
                    f"{event.name}: max price {state.price_max:.0f} -> "
                    f"{event.price_max:.0f} {event.currency}. Possible resale movement.",
                )

        state = WatchState(
            status=event.status, price_max=event.price_max, open_windows=open_now
        )
        first = False

        polls += 1
        if max_polls is not None and polls >= max_polls:
            return
        time.sleep(interval)
