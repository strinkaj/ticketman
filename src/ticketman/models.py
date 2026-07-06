"""Data models for ticketman.

Two groups of models live here:

1. Configuration and roster models (pydantic), read from and written to YAML on
   disk.
2. Parsed event models, built from the Ticketmaster Discovery API response and
   passed around in memory.

Nothing here automates a browser or a purchase. The tool is an alerting and
coordination system for real people buying on their own accounts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration models
# ---------------------------------------------------------------------------


class TicketmasterConfig(BaseModel):
    """Ticketmaster Discovery API access.

    The API key is a public consumer key from developer.ticketmaster.com. It
    returns read-only event data. It cannot log in, hold a cart, or buy
    anything.
    """

    api_key: str = ""
    country_code: str = "US"


class NotificationConfig(BaseModel):
    """Alert channels. Desktop toast only, by design."""

    desktop: bool = True


class StrategyWeights(BaseModel):
    """Weights for the sellout-likelihood score.

    Each factor is normalized to 0..1, multiplied by its weight, then the
    weighted average is rescaled to 0..100. Weights do not need to sum to 1;
    they are normalized by their own sum. Tune these to match what you have
    seen sell out in your markets.
    """

    presale_density: float = 0.25
    verified_fan: float = 0.25
    price_ceiling: float = 0.15
    market_size: float = 0.15
    venue_scarcity: float = 0.12
    genre: float = 0.08


class AppConfig(BaseModel):
    """Top-level application configuration."""

    ticketmaster: TicketmasterConfig = Field(default_factory=TicketmasterConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    strategy: StrategyWeights = Field(default_factory=StrategyWeights)


# ---------------------------------------------------------------------------
# Roster models (group coordination, not automation)
# ---------------------------------------------------------------------------


class Participant(BaseModel):
    """One real person in the buying group.

    We store an email so accounts can be told apart in the plan, and a set of
    free-form access tags (for example "amex", "citi", "fan-club:artist",
    "verified-fan"). We deliberately do NOT store passwords, and the tool never
    logs in as anyone. Each participant checks out on their own device.
    """

    name: str
    account_email: str = ""
    city: str = ""
    timezone: str = ""  # optional IANA name, e.g. "America/New_York"; else local
    access: list[str] = Field(default_factory=list)
    notes: str = ""


class Roster(BaseModel):
    """The buying group."""

    participants: list[Participant] = Field(default_factory=list)

    def find(self, name: str) -> Participant | None:
        lowered = name.lower()
        for p in self.participants:
            if p.name.lower() == lowered:
                return p
        return None

    def duplicate_emails(self) -> list[str]:
        """Emails shared by more than one participant.

        A shared email is the signature of one person holding several accounts,
        which is the farming pattern this tool refuses to help with. Callers
        surface these as a warning.
        """
        seen: dict[str, int] = {}
        for p in self.participants:
            email = p.account_email.strip().lower()
            if email:
                seen[email] = seen.get(email, 0) + 1
        return sorted(e for e, n in seen.items() if n > 1)


# ---------------------------------------------------------------------------
# Portfolio and lottery tracking (coordination state, still no automation)
# ---------------------------------------------------------------------------

# Lifecycle of one person's shot at one event.
RegistrationStatus = Literal[
    "intend",  # plans to register, has not yet
    "registered",  # registered for the Verified Fan / presale, awaiting draw
    "won",  # drew a code, has a purchase window
    "lost",  # not selected
    "purchased",  # bought tickets in their window
    "missed",  # won but did not buy in time
]


class WatchlistEntry(BaseModel):
    """One event you are tracking, cached so the portfolio renders offline."""

    event_id: str
    name: str = ""
    url: str = ""
    event_date: str = ""  # local date/time string from the API
    city: str = ""
    target_qty: int = 4
    added_at: str = ""  # ISO date the entry was added
    notes: str = ""


class Watchlist(BaseModel):
    """The set of events under coordination."""

    events: list[WatchlistEntry] = Field(default_factory=list)

    def find(self, event_id: str) -> WatchlistEntry | None:
        for e in self.events:
            if e.event_id == event_id:
                return e
        return None


class Registration(BaseModel):
    """One person's registration and outcome for one event."""

    participant: str
    event_id: str
    presale_name: str = "Verified Fan"
    registration_deadline: datetime | None = None
    status: RegistrationStatus = "intend"
    code_received: bool = False
    purchase_window_start: datetime | None = None
    purchase_window_end: datetime | None = None
    purchased_qty: int = 0
    notes: str = ""


class RegistrationLog(BaseModel):
    """All registrations across people and events."""

    registrations: list[Registration] = Field(default_factory=list)

    def find(self, participant: str, event_id: str) -> Registration | None:
        pl = participant.lower()
        for r in self.registrations:
            if r.participant.lower() == pl and r.event_id == event_id:
                return r
        return None

    def for_event(self, event_id: str) -> list[Registration]:
        return [r for r in self.registrations if r.event_id == event_id]


class EventOutcome(BaseModel):
    """A labeled past event, used to check the sellout score against reality."""

    event_id: str
    name: str = ""
    sold_out: bool = False
    minutes_to_sellout: int | None = None
    # Cached score at label time, so calibrate works without re-fetching.
    score: float | None = None


class OutcomeLog(BaseModel):
    """Labeled outcomes for calibration."""

    outcomes: list[EventOutcome] = Field(default_factory=list)

    def find(self, event_id: str) -> EventOutcome | None:
        for o in self.outcomes:
            if o.event_id == event_id:
                return o
        return None


# ---------------------------------------------------------------------------
# Parsed event models (built from Discovery API responses)
# ---------------------------------------------------------------------------


class PresaleWindow(BaseModel):
    """A single presale window on an event."""

    name: str
    start: datetime | None = None
    end: datetime | None = None


class SalesWindow(BaseModel):
    """The public on-sale window."""

    start: datetime | None = None
    end: datetime | None = None


class Event(BaseModel):
    """A parsed Ticketmaster event.

    Fields are optional-friendly because the Discovery API omits many of them
    depending on the event and how far out it is.
    """

    id: str
    name: str
    url: str = ""
    status: str = ""  # onsale, offsale, cancelled, postponed, rescheduled
    start_local: str = ""  # local date/time string as given by the API
    start_utc: datetime | None = None
    timezone: str = ""

    venue_name: str = ""
    city: str = ""
    state: str = ""
    capacity: int | None = None

    segment: str = ""  # e.g. Music
    genre: str = ""  # e.g. Pop

    price_min: float | None = None
    price_max: float | None = None
    currency: str = "USD"

    presales: list[PresaleWindow] = Field(default_factory=list)
    public_sale: SalesWindow | None = None
