"""Presale strategy and sellout-likelihood scoring.

This module is the brain. It does two things:

1. score_sellout(event, weights): estimate how likely an event is to sell out,
   as a 0..100 number with a per-factor breakdown so you can see exactly why.
   This is a heuristic, not a prediction backed by demand data (the public API
   does not expose demand). Every input is visible and every weight is tunable.

2. build_plan(event, roster): turn the sellout score plus the event's presale
   schedule into a concrete plan. Which window to target, who in your group can
   access which presale, and how to split a 3 to 5 ticket buy across real people
   so you maximize Verified Fan lottery entries without overbuying.

The scoring mechanism, stated plainly so there is no magic:
  final = 100 * sum(weight_i * normalized_factor_i) / sum(weight_i)
Each normalized factor is in 0..1. Bigger means more likely to sell out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ticketman.models import Event, Participant, Roster, StrategyWeights

# ---------------------------------------------------------------------------
# Reference tables. These are editable heuristics, not received truth. They
# encode "for the same act, a show in a bigger market or a smaller room sells
# out faster." Adjust to your own observations.
# ---------------------------------------------------------------------------

# City demand multiplier. Larger, ticket-hungry metros clear faster. Keys are
# lowercased city names. Unknown cities fall back to MARKET_DEFAULT.
MARKET_SIZE: dict[str, float] = {
    "new york": 1.0,
    "brooklyn": 1.0,
    "los angeles": 1.0,
    "inglewood": 1.0,
    "chicago": 0.92,
    "san francisco": 0.9,
    "oakland": 0.88,
    "boston": 0.88,
    "washington": 0.86,
    "seattle": 0.86,
    "philadelphia": 0.84,
    "toronto": 0.86,
    "atlanta": 0.82,
    "miami": 0.84,
    "dallas": 0.8,
    "houston": 0.8,
    "austin": 0.82,
    "denver": 0.8,
    "nashville": 0.8,
    "las vegas": 0.86,
    "san diego": 0.78,
    "portland": 0.76,
    "minneapolis": 0.74,
    "phoenix": 0.74,
    "detroit": 0.72,
    "san jose": 0.8,
}
MARKET_DEFAULT = 0.55

# Genre base sellout rate. K-Pop and hip-hop clear fastest, classical slowest.
# Keys are lowercased genre names as returned by the API.
GENRE_BASE: dict[str, float] = {
    "k-pop": 0.95,
    "hip-hop/rap": 0.85,
    "rap": 0.85,
    "pop": 0.8,
    "r&b": 0.75,
    "country": 0.72,
    "latin": 0.72,
    "rock": 0.7,
    "alternative": 0.7,
    "dance/electronic": 0.65,
    "electronic": 0.65,
    "metal": 0.6,
    "reggae": 0.55,
    "folk": 0.5,
    "jazz": 0.4,
    "blues": 0.4,
    "classical": 0.3,
}
GENRE_DEFAULT = 0.55

# Words in a venue name that hint at size when the API omits capacity.
# Smaller rooms sell out faster for the same demand, so scarcity is inverted
# from raw size.
_SMALL_VENUE_WORDS = ("club", "lounge", "hall", "theatre", "theater", "ballroom", "room")
_LARGE_VENUE_WORDS = ("stadium", "field", "amphitheater", "amphitheatre", "park", "coliseum")

# Case-insensitive markers that a presale or price tier signals top-tier demand.
_VERIFIED_FAN_MARKERS = ("verified fan", "verifiedfan")
_PLATINUM_MARKERS = ("platinum", "official platinum")


@dataclass
class Factor:
    """One scored input, kept fully inspectable."""

    name: str
    normalized: float  # 0..1
    weight: float
    note: str

    @property
    def contribution(self) -> float:
        return self.normalized * self.weight


@dataclass
class SelloutScore:
    """Result of scoring one event."""

    score: float  # 0..100
    tier: str
    factors: list[Factor] = field(default_factory=list)


def _tier(score: float) -> str:
    if score >= 78:
        return "Extreme"
    if score >= 55:
        return "High"
    if score >= 30:
        return "Moderate"
    return "Low"


def _market_factor(event: Event) -> Factor:
    val = MARKET_SIZE.get(event.city.lower(), MARKET_DEFAULT)
    note = f"{event.city or 'unknown city'} -> {val:.2f}"
    return Factor("Market size", val, 0.0, note)


def _genre_factor(event: Event) -> Factor:
    val = GENRE_BASE.get(event.genre.lower(), GENRE_DEFAULT)
    note = f"{event.genre or 'unknown genre'} -> {val:.2f}"
    return Factor("Genre base rate", val, 0.0, note)


def _venue_scarcity_factor(event: Event) -> Factor:
    if event.capacity:
        # Smaller capacity means it clears faster. Map capacity to scarcity.
        if event.capacity < 2000:
            val, why = 0.9, f"{event.capacity} seats (small room)"
        elif event.capacity < 6000:
            val, why = 0.75, f"{event.capacity} seats (mid)"
        elif event.capacity < 16000:
            val, why = 0.6, f"{event.capacity} seats (arena)"
        else:
            val, why = 0.45, f"{event.capacity} seats (stadium)"
        return Factor("Venue scarcity", val, 0.0, why)

    name = event.venue_name.lower()
    if any(w in name for w in _LARGE_VENUE_WORDS):
        return Factor("Venue scarcity", 0.45, 0.0, "large venue by name")
    if any(w in name for w in _SMALL_VENUE_WORDS):
        return Factor("Venue scarcity", 0.85, 0.0, "small venue by name")
    return Factor("Venue scarcity", 0.6, 0.0, "capacity unknown, assumed arena")


def _presale_density_factor(event: Event) -> Factor:
    n = len(event.presales)
    # More presale windows means the promoter expects heavy demand and is
    # rationing access. Diminishing returns past a few.
    mapping = {0: 0.1, 1: 0.35, 2: 0.55, 3: 0.72, 4: 0.85}
    val = mapping.get(n, 0.92)
    return Factor("Presale density", val, 0.0, f"{n} presale window(s)")


def _verified_fan_factor(event: Event) -> Factor:
    haystack = " ".join(p.name.lower() for p in event.presales)
    if any(m in haystack for m in _VERIFIED_FAN_MARKERS):
        return Factor("Verified Fan / Platinum", 0.95, 0.0, "Verified Fan presale present")
    if any(m in haystack for m in _PLATINUM_MARKERS):
        return Factor("Verified Fan / Platinum", 0.85, 0.0, "Platinum presale present")
    # High ceiling price is a softer signal of dynamic/platinum pricing.
    if event.price_max and event.price_max >= 400:
        return Factor("Verified Fan / Platinum", 0.7, 0.0, "high price ceiling suggests platinum")
    return Factor("Verified Fan / Platinum", 0.3, 0.0, "no Verified Fan / Platinum signal")


def _price_ceiling_factor(event: Event) -> Factor:
    pm = event.price_max
    if pm is None:
        return Factor("Price ceiling", 0.4, 0.0, "no price data yet")
    if pm >= 400:
        val = 0.95
    elif pm >= 250:
        val = 0.8
    elif pm >= 150:
        val = 0.6
    elif pm >= 75:
        val = 0.4
    else:
        val = 0.25
    return Factor("Price ceiling", val, 0.0, f"max ${pm:.0f}")


def score_sellout(event: Event, weights: StrategyWeights | None = None) -> SelloutScore:
    """Estimate sellout likelihood for an event with a visible breakdown."""
    w = weights or StrategyWeights()

    factors = [
        _presale_density_factor(event),
        _verified_fan_factor(event),
        _price_ceiling_factor(event),
        _market_factor(event),
        _venue_scarcity_factor(event),
        _genre_factor(event),
    ]
    weight_map = {
        "Presale density": w.presale_density,
        "Verified Fan / Platinum": w.verified_fan,
        "Price ceiling": w.price_ceiling,
        "Market size": w.market_size,
        "Venue scarcity": w.venue_scarcity,
        "Genre base rate": w.genre,
    }
    for f in factors:
        f.weight = weight_map[f.name]

    total_weight = sum(f.weight for f in factors) or 1.0
    score = 100.0 * sum(f.contribution for f in factors) / total_weight
    return SelloutScore(score=round(score, 1), tier=_tier(score), factors=factors)


# ---------------------------------------------------------------------------
# Presale planning
# ---------------------------------------------------------------------------


@dataclass
class WindowPlan:
    """A single sale window with who in the group can reach it."""

    name: str
    start: datetime | None
    end: datetime | None
    kind: str  # "presale" or "public"
    eligible: list[str] = field(default_factory=list)
    needs_registration: bool = False
    needs_code: bool = False


@dataclass
class GroupPlan:
    """Assignment of the buy across real people."""

    primary_buyer: str
    backups: list[str]
    per_person_quantity: int
    rationale: str


@dataclass
class EventPlan:
    """Everything the plan command prints for one event."""

    event: Event
    sellout: SelloutScore
    windows: list[WindowPlan]
    group: GroupPlan | None
    recommendation: str


def _match_access(presale_name: str, participant: Participant) -> bool:
    """Decide whether a participant's access tags cover this presale."""
    name = presale_name.lower()
    for tag in participant.access:
        t = tag.lower()
        if t in name:
            return True
        # Common shorthands.
        if t == "amex" and ("american express" in name or "amex" in name):
            return True
        if t == "citi" and "citi" in name:
            return True
        if t.startswith("verified-fan") and any(m in name for m in _VERIFIED_FAN_MARKERS):
            return True
        if t.startswith("fan-club") and ("fan club" in name or "artist presale" in name):
            return True
    return False


def _classify_window(name: str) -> tuple[bool, bool]:
    """Return (needs_registration, needs_code) for a presale name."""
    low = name.lower()
    needs_registration = any(m in low for m in _VERIFIED_FAN_MARKERS)
    # Most non-public presales gate on a code or a cardholder login.
    needs_code = not needs_registration
    return needs_registration, needs_code


def build_plan(
    event: Event, roster: Roster, weights: StrategyWeights | None = None, target_qty: int = 4
) -> EventPlan:
    """Build the full strategy for one event and buying group."""
    sellout = score_sellout(event, weights)

    windows: list[WindowPlan] = []
    for ps in event.presales:
        needs_reg, needs_code = _classify_window(ps.name)
        eligible = [p.name for p in roster.participants if _match_access(ps.name, p)]
        windows.append(
            WindowPlan(
                name=ps.name,
                start=ps.start,
                end=ps.end,
                kind="presale",
                eligible=eligible,
                needs_registration=needs_reg,
                needs_code=needs_code,
            )
        )
    if event.public_sale:
        windows.append(
            WindowPlan(
                name="General public on-sale",
                start=event.public_sale.start,
                end=event.public_sale.end,
                kind="public",
                eligible=[p.name for p in roster.participants],
                needs_registration=False,
                needs_code=False,
            )
        )

    # Sort windows chronologically, unknown times last.
    windows.sort(key=lambda w: (w.start is None, w.start or datetime.max.replace(tzinfo=UTC)))

    group = _assign_group(roster, target_qty)
    recommendation = _recommendation(event, sellout, windows, target_qty)
    return EventPlan(event, sellout, windows, group, recommendation)


def _assign_group(roster: Roster, target_qty: int) -> GroupPlan | None:
    """Pick a primary buyer and backups.

    Ticketmaster caps most events at 4 to 8 per account, so 3 to 5 tickets fit
    on a single account. The reason to have several people is redundancy and
    more Verified Fan lottery entries, not stacking accounts to beat a limit.
    Whoever clears the queue first buys the whole block; the rest stand down so
    the group does not overbuy.
    """
    if not roster.participants:
        return None
    names = [p.name for p in roster.participants]
    per_person = min(target_qty, 8)
    rationale = (
        f"Whoever reaches checkout first buys all {target_qty} in one order "
        f"(within the per-account limit). The others are live backups and each "
        f"registers for Verified Fan on their own account to add lottery entries. "
        f"Stand down the moment one person confirms, so the group does not overbuy."
    )
    return GroupPlan(
        primary_buyer=names[0],
        backups=names[1:],
        per_person_quantity=per_person,
        rationale=rationale,
    )


def _recommendation(
    event: Event, sellout: SelloutScore, windows: list[WindowPlan], target_qty: int
) -> str:
    """Plain-language advice given the score and windows."""
    presale_windows = [w for w in windows if w.kind == "presale"]
    lines: list[str] = []

    if sellout.tier in ("High", "Extreme"):
        if presale_windows:
            first = presale_windows[0]
            lines.append(
                f"Sellout risk is {sellout.tier}. Do not wait for the public on-sale. "
                f"Target the earliest presale ('{first.name}'). Inventory thins with "
                f"each window."
            )
        else:
            lines.append(
                f"Sellout risk is {sellout.tier} and no presales are listed yet. "
                f"Watch this event so you catch presales the moment they are announced, "
                f"and be ready at the public on-sale second."
            )
        reg_windows = [w for w in presale_windows if w.needs_registration]
        if reg_windows:
            lines.append(
                "This event has a Verified Fan presale. Register every person in the "
                "group before the registration deadline. Each real account is one more "
                "lottery entry."
            )
    else:
        lines.append(
            f"Sellout risk is {sellout.tier}. You likely have room at the public "
            f"on-sale, but a presale is still the safer path if you have access."
        )

    lines.append(
        f"For {target_qty} tickets you do not need many accounts. One account can "
        f"usually buy the whole block. Extra people are backups and lottery entries."
    )
    return " ".join(lines)
