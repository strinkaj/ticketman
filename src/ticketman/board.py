"""War-room views and winner-aware assignment.

Assembles the state the `board` command renders: per-event, who registered, who
won, their purchase windows, and how to split the buy across winners so the
group hits its target without overbuying. Pure data, no formatting or network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ticketman.models import Registration, RegistrationLog, Roster, Watchlist

# Ticketmaster caps most events per account. A single winner usually covers a
# 3 to 5 ticket group; this only matters if the target exceeds one account.
PER_ACCOUNT_CAP = 8


@dataclass
class Assignment:
    """One winner's share of the buy."""

    participant: str
    quantity: int


@dataclass
class EventBoard:
    """Everything the board command shows for one event."""

    event_id: str
    name: str
    target_qty: int
    registrations: list[Registration]
    assignments: list[Assignment]
    registered_count: int
    won_count: int
    secured_qty: int

    @property
    def remaining(self) -> int:
        return max(0, self.target_qty - self.secured_qty)


@dataclass
class PortfolioRow:
    """One event's roll-up in the portfolio view."""

    event_id: str
    name: str
    target_qty: int
    registered: int
    won: int
    secured: int


@dataclass
class Portfolio:
    rows: list[PortfolioRow] = field(default_factory=list)


def assign_winners(
    winners: list[Registration], target_qty: int, cap: int = PER_ACCOUNT_CAP
) -> list[Assignment]:
    """Split target_qty across winners, capped per account.

    Fills the first winner up to the cap, then the next, and so on. For a 3 to 5
    ticket group this puts the whole block on one winner and leaves the rest as
    standby, which is the point: do not overbuy.
    """
    assignments: list[Assignment] = []
    remaining = target_qty
    for reg in winners:
        if remaining <= 0:
            break
        take = min(cap, remaining)
        assignments.append(Assignment(participant=reg.participant, quantity=take))
        remaining -= take
    return assignments


def build_event_board(
    event_id: str,
    name: str,
    target_qty: int,
    reg_log: RegistrationLog,
) -> EventBoard:
    """Assemble the board for one event."""
    regs = reg_log.for_event(event_id)
    winners = [r for r in regs if r.status in ("won", "purchased")]
    secured = sum(r.purchased_qty for r in regs if r.status == "purchased")

    # Assign only the tickets still needed, across winners not yet purchased.
    still_open = [r for r in winners if r.status == "won"]
    assignments = assign_winners(still_open, max(0, target_qty - secured))

    return EventBoard(
        event_id=event_id,
        name=name,
        target_qty=target_qty,
        registrations=sorted(regs, key=lambda r: r.participant.lower()),
        assignments=assignments,
        registered_count=len([r for r in regs if r.status != "intend"]),
        won_count=len(winners),
        secured_qty=secured,
    )


def build_portfolio(watchlist: Watchlist, reg_log: RegistrationLog) -> Portfolio:
    """Roll up every tracked event."""
    rows: list[PortfolioRow] = []
    for entry in watchlist.events:
        regs = reg_log.for_event(entry.event_id)
        rows.append(
            PortfolioRow(
                event_id=entry.event_id,
                name=entry.name or entry.event_id,
                target_qty=entry.target_qty,
                registered=len([r for r in regs if r.status != "intend"]),
                won=len([r for r in regs if r.status in ("won", "purchased")]),
                secured=sum(r.purchased_qty for r in regs if r.status == "purchased"),
            )
        )
    return Portfolio(rows=rows)


def resolve_timezone(roster: Roster, participant_name: str):
    """Return a tzinfo for a participant, or None to fall back to local time."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    p = roster.find(participant_name)
    if p and p.timezone:
        try:
            return ZoneInfo(p.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return None
    return None
