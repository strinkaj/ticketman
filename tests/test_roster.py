"""Tests for roster and config persistence."""

from __future__ import annotations

from ticketman.config import (
    load_config,
    load_registrations,
    load_roster,
    load_watchlist,
    save_registrations,
    save_roster,
    save_watchlist,
)
from ticketman.models import (
    Participant,
    Registration,
    RegistrationLog,
    Roster,
    Watchlist,
    WatchlistEntry,
)


def test_roster_roundtrip(tmp_path):
    path = tmp_path / "roster.yaml"
    roster = Roster(
        participants=[
            Participant(
                name="Joe", account_email="joe@example.com", access=["amex", "verified-fan"]
            ),
            Participant(name="Amy", account_email="amy@example.com"),
        ]
    )
    save_roster(roster, path)
    loaded = load_roster(path)
    assert len(loaded.participants) == 2
    assert loaded.find("joe") is not None
    assert loaded.find("JOE").account_email == "joe@example.com"
    assert loaded.find("nobody") is None


def test_load_roster_missing_returns_empty(tmp_path):
    loaded = load_roster(tmp_path / "does-not-exist.yaml")
    assert loaded.participants == []


def test_load_config_env_overrides_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TM_API_KEY", "env-key-123")
    cfg = load_config(tmp_path / "no-config.yaml")
    assert cfg.ticketmaster.api_key == "env-key-123"


def test_load_config_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("TM_API_KEY", raising=False)
    cfg = load_config(tmp_path / "no-config.yaml")
    assert cfg.ticketmaster.api_key == ""
    assert cfg.notifications.desktop is True
    assert cfg.strategy.verified_fan == 0.25


def test_duplicate_emails_detection():
    roster = Roster(
        participants=[
            Participant(name="Joe", account_email="shared@x.com"),
            Participant(name="Amy", account_email="Shared@X.com"),  # same, different case
            Participant(name="Bo", account_email="bo@x.com"),
        ]
    )
    assert roster.duplicate_emails() == ["shared@x.com"]


def test_no_duplicate_emails_when_distinct():
    roster = Roster(
        participants=[
            Participant(name="Joe", account_email="joe@x.com"),
            Participant(name="Amy", account_email="amy@x.com"),
        ]
    )
    assert roster.duplicate_emails() == []


def test_watchlist_roundtrip(tmp_path):
    path = tmp_path / "watchlist.yaml"
    wl = Watchlist(events=[WatchlistEntry(event_id="E1", name="Show", target_qty=5)])
    save_watchlist(wl, path)
    loaded = load_watchlist(path)
    assert loaded.find("E1").target_qty == 5


def test_registrations_roundtrip(tmp_path):
    path = tmp_path / "registrations.yaml"
    log = RegistrationLog(
        registrations=[Registration(participant="Joe", event_id="E1", status="won")]
    )
    save_registrations(log, path)
    loaded = load_registrations(path)
    assert loaded.find("Joe", "E1").status == "won"
    assert loaded.for_event("E1")
