"""Tests for the lottery ledger and winner-aware assignment."""

from __future__ import annotations

import pytest

from ticketman.board import assign_winners, build_event_board, build_portfolio
from ticketman.models import RegistrationLog, Watchlist, WatchlistEntry
from ticketman.registry import record_purchase, record_result, register, secured_quantity


def test_register_upsert():
    log = RegistrationLog()
    r1 = register(log, "Joe", "E1")
    assert r1.status == "registered"
    r2 = register(log, "joe", "E1", presale_name="Amex")
    assert len(log.registrations) == 1  # upsert, not duplicate
    assert r2.presale_name == "Amex"


def test_record_result_win_and_loss():
    log = RegistrationLog()
    register(log, "Joe", "E1")
    register(log, "Amy", "E1")
    record_result(log, "Joe", "E1", won=True)
    record_result(log, "Amy", "E1", won=False)
    assert log.find("Joe", "E1").status == "won"
    assert log.find("Joe", "E1").code_received is True
    assert log.find("Amy", "E1").status == "lost"


def test_record_result_creates_missing_registration():
    log = RegistrationLog()
    record_result(log, "Ghost", "E1", won=True)
    assert log.find("Ghost", "E1").status == "won"


def test_record_purchase_requires_registration():
    log = RegistrationLog()
    with pytest.raises(ValueError):
        record_purchase(log, "Nobody", "E1", qty=2)


def test_secured_quantity():
    log = RegistrationLog()
    register(log, "Joe", "E1")
    record_result(log, "Joe", "E1", won=True)
    record_purchase(log, "Joe", "E1", qty=4)
    assert secured_quantity(log, "E1") == 4


def test_assign_winners_single_account_covers_small_group():
    log = RegistrationLog()
    for name in ("Joe", "Amy", "Bo"):
        register(log, name, "E1")
        record_result(log, name, "E1", won=True)
    winners = log.for_event("E1")
    assignments = assign_winners(winners, target_qty=4)
    assert len(assignments) == 1
    assert assignments[0].quantity == 4


def test_assign_winners_spills_over_cap():
    log = RegistrationLog()
    for name in ("Joe", "Amy"):
        register(log, name, "E1")
        record_result(log, name, "E1", won=True)
    winners = log.for_event("E1")
    assignments = assign_winners(winners, target_qty=10, cap=8)
    assert [a.quantity for a in assignments] == [8, 2]


def test_build_event_board_counts():
    log = RegistrationLog()
    register(log, "Joe", "E1")
    register(log, "Amy", "E1")
    register(log, "Bo", "E1")
    record_result(log, "Joe", "E1", won=True)
    record_result(log, "Amy", "E1", won=False)
    b = build_event_board("E1", "Show", 4, log)
    assert b.registered_count == 3
    assert b.won_count == 1
    assert b.remaining == 4
    assert b.assignments[0].participant == "Joe"


def test_build_event_board_stops_assigning_when_secured():
    log = RegistrationLog()
    register(log, "Joe", "E1")
    record_result(log, "Joe", "E1", won=True)
    record_purchase(log, "Joe", "E1", qty=4)
    b = build_event_board("E1", "Show", 4, log)
    assert b.secured_qty == 4
    assert b.remaining == 0
    assert b.assignments == []


def test_build_portfolio_rolls_up():
    wl = Watchlist(events=[WatchlistEntry(event_id="E1", name="Show", target_qty=4)])
    log = RegistrationLog()
    register(log, "Joe", "E1")
    record_result(log, "Joe", "E1", won=True)
    portfolio = build_portfolio(wl, log)
    assert len(portfolio.rows) == 1
    assert portfolio.rows[0].won == 1
