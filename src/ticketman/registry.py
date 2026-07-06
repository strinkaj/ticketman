"""Lottery ledger operations.

Pure functions over a RegistrationLog: record that a person registered for an
event's Verified Fan or presale, record the lottery result and the purchase
window they were given, and record a completed purchase. No network, no
automation. Each person still buys their own tickets in their own window.
"""

from __future__ import annotations

from datetime import datetime

from ticketman.models import Registration, RegistrationLog


def register(
    log: RegistrationLog,
    participant: str,
    event_id: str,
    *,
    presale_name: str = "Verified Fan",
    deadline: datetime | None = None,
) -> Registration:
    """Record that a person is registering for an event. Upserts."""
    existing = log.find(participant, event_id)
    if existing:
        existing.presale_name = presale_name
        if deadline is not None:
            existing.registration_deadline = deadline
        if existing.status == "intend":
            existing.status = "registered"
        return existing

    reg = Registration(
        participant=participant,
        event_id=event_id,
        presale_name=presale_name,
        registration_deadline=deadline,
        status="registered",
    )
    log.registrations.append(reg)
    return reg


def record_result(
    log: RegistrationLog,
    participant: str,
    event_id: str,
    *,
    won: bool,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    code_received: bool | None = None,
) -> Registration:
    """Record a lottery outcome. Creates the registration if missing."""
    reg = log.find(participant, event_id)
    if reg is None:
        reg = Registration(participant=participant, event_id=event_id)
        log.registrations.append(reg)

    reg.status = "won" if won else "lost"
    if won:
        reg.code_received = True if code_received is None else code_received
        reg.purchase_window_start = window_start
        reg.purchase_window_end = window_end
    return reg


def record_purchase(
    log: RegistrationLog, participant: str, event_id: str, *, qty: int
) -> Registration:
    """Record that a winner completed their purchase."""
    reg = log.find(participant, event_id)
    if reg is None:
        raise ValueError(f"No registration for {participant} on event {event_id}.")
    reg.status = "purchased"
    reg.purchased_qty = qty
    return reg


def secured_quantity(log: RegistrationLog, event_id: str) -> int:
    """Total tickets already bought for an event."""
    return sum(r.purchased_qty for r in log.for_event(event_id) if r.status == "purchased")
