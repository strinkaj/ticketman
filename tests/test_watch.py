"""Tests for the event watcher (no network, fake client)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ticketman.models import Event, NotificationConfig, PresaleWindow, SalesWindow
from ticketman.notify import Notifier
from ticketman.watch import _next_window, _open_window_names, watch_event

NOW = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)


def _event_with_open_presale() -> Event:
    return Event(
        id="E",
        name="Show",
        presales=[
            PresaleWindow(
                name="Verified Fan Presale",
                start=NOW - timedelta(hours=1),
                end=NOW + timedelta(hours=1),
            )
        ],
        public_sale=SalesWindow(start=NOW + timedelta(days=2)),
    )


def test_open_window_names_detects_active_presale():
    e = _event_with_open_presale()
    names = _open_window_names(e, NOW)
    assert "Verified Fan Presale" in names
    assert "General public on-sale" not in names


def test_next_window_picks_soonest_future():
    e = _event_with_open_presale()
    nxt = _next_window(e, NOW)
    assert nxt is not None
    assert nxt[0] == "General public on-sale"


class _RecordingNotifier(Notifier):
    def __init__(self):
        super().__init__(NotificationConfig(desktop=False))
        self.alerts: list[tuple[str, str]] = []

    def notify(self, title: str, message: str) -> None:
        self.alerts.append((title, message))


class _FakeClient:
    """Returns a scripted sequence of events, one per get_event call."""

    def __init__(self, events: list[Event]):
        self._events = events
        self._i = 0

    def get_event(self, _url_or_id: str) -> Event:
        e = self._events[min(self._i, len(self._events) - 1)]
        self._i += 1
        return e


def test_watch_alerts_when_window_opens_between_polls():
    closed = Event(
        id="E",
        name="Show",
        presales=[
            PresaleWindow(
                name="Artist Presale",
                start=NOW + timedelta(hours=5),
                end=NOW + timedelta(hours=9),
            )
        ],
    )
    # Second poll: the presale is now open. Build it around the real current
    # time, because watch_event checks against the wall clock.
    real_now = datetime.now(UTC)
    opened = Event(
        id="E",
        name="Show",
        presales=[
            PresaleWindow(
                name="Artist Presale",
                start=real_now - timedelta(hours=1),
                end=real_now + timedelta(hours=1),
            )
        ],
    )
    notifier = _RecordingNotifier()
    client = _FakeClient([closed, opened])
    watch_event(client, notifier, "E", interval=0, max_polls=2)

    titles = [t for t, _ in notifier.alerts]
    assert "Sale window opened" in titles


def test_watch_alerts_on_price_drop():
    high = Event(id="E", name="Show", price_max=400.0)
    low = Event(id="E", name="Show", price_max=250.0)
    notifier = _RecordingNotifier()
    client = _FakeClient([high, low])
    watch_event(client, notifier, "E", interval=0, max_polls=2)

    titles = [t for t, _ in notifier.alerts]
    assert "Price dropped" in titles


def test_notifier_console_only_does_not_raise():
    n = Notifier(NotificationConfig(desktop=False))
    n.notify("hello", "world")  # should log, not raise
