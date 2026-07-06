"""CLI tests using Typer's runner. API-backed commands use a fake client."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from ticketman import cli
from ticketman.models import Event, PresaleWindow, SalesWindow

runner = CliRunner()


class _FakeClient:
    def __init__(self, event: Event):
        self._event = event

    def get_event(self, _url_or_id: str) -> Event:
        return self._event

    def search_events(self, _keyword, city=None, size=20):
        return [self._event]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_event() -> Event:
    return Event(
        id="ABC123",
        name="Big Act - Live",
        status="onsale",
        city="New York",
        state="NY",
        venue_name="Madison Square Garden",
        genre="Pop",
        capacity=20000,
        price_min=50.0,
        price_max=425.0,
        start_local="2026-09-12 20:00",
        presales=[
            PresaleWindow(name="Verified Fan Presale"),
            PresaleWindow(name="American Express Presale"),
        ],
        public_sale=SalesWindow(),
    )


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    # Keep roster writes and config reads inside a temp dir.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TM_API_KEY", "test-key")


def _patch_client(monkeypatch, event: Event):
    monkeypatch.setattr(cli, "_client", lambda cfg: _FakeClient(event))


def test_roster_add_list_remove():
    r = runner.invoke(
        cli.app,
        ["roster", "add", "Joe", "--email", "joe@x.com", "--access", "amex,verified-fan"],
    )
    assert r.exit_code == 0
    assert "Added Joe" in r.stdout

    r = runner.invoke(cli.app, ["roster", "list"])
    assert "Joe" in r.stdout
    assert "amex" in r.stdout

    r = runner.invoke(cli.app, ["roster", "remove", "Joe"])
    assert r.exit_code == 0

    r = runner.invoke(cli.app, ["roster", "remove", "Joe"])
    assert r.exit_code == 1  # already gone


def test_status():
    r = runner.invoke(cli.app, ["status"])
    assert r.exit_code == 0
    assert "Discovery API key: set" in r.stdout


def test_find(monkeypatch, fake_event):
    _patch_client(monkeypatch, fake_event)
    r = runner.invoke(cli.app, ["find", "big act"])
    assert r.exit_code == 0
    assert "ABC123" in r.stdout
    assert "Big Act" in r.stdout


def test_info(monkeypatch, fake_event):
    _patch_client(monkeypatch, fake_event)
    r = runner.invoke(cli.app, ["info", "ABC123"])
    assert r.exit_code == 0
    assert "Verified Fan Presale" in r.stdout
    assert "Madison Square Garden" in r.stdout


def test_plan(monkeypatch, fake_event):
    _patch_client(monkeypatch, fake_event)
    runner.invoke(cli.app, ["roster", "add", "Joe", "--access", "amex"])
    r = runner.invoke(cli.app, ["plan", "ABC123", "--quantity", "4"])
    assert r.exit_code == 0
    assert "SELLOUT RISK" in r.stdout
    assert "GROUP PLAN" in r.stdout
    assert "RECOMMENDATION" in r.stdout


def test_checklist(monkeypatch, fake_event):
    _patch_client(monkeypatch, fake_event)
    runner.invoke(cli.app, ["roster", "add", "Amy", "--access", "verified-fan"])
    r = runner.invoke(cli.app, ["checklist", "ABC123"])
    assert r.exit_code == 0
    assert "PREP CHECKLIST" in r.stdout
    assert "Verified Fan" in r.stdout


def test_watchlist_add_and_list(monkeypatch, fake_event):
    _patch_client(monkeypatch, fake_event)
    r = runner.invoke(cli.app, ["watchlist", "add", "ABC123", "--quantity", "5"])
    assert r.exit_code == 0
    r = runner.invoke(cli.app, ["watchlist", "list"])
    assert "Big Act" in r.stdout
    assert "ABC123" in r.stdout


def test_lottery_flow_and_board(monkeypatch, fake_event):
    _patch_client(monkeypatch, fake_event)
    runner.invoke(cli.app, ["watchlist", "add", "ABC123", "--quantity", "4"])
    runner.invoke(cli.app, ["roster", "add", "Joe"])
    runner.invoke(cli.app, ["roster", "add", "Amy"])

    # Joe must be in the roster to register.
    r = runner.invoke(cli.app, ["register", "ABC123", "Joe"])
    assert r.exit_code == 0
    r = runner.invoke(cli.app, ["register", "ABC123", "Ghost"])
    assert r.exit_code == 1  # not in roster

    runner.invoke(cli.app, ["result", "ABC123", "Joe", "--won"])
    r = runner.invoke(cli.app, ["board", "ABC123"])
    assert "won 1" in r.stdout
    assert "ASSIGNMENTS" in r.stdout
    assert "Joe: buy 4" in r.stdout

    r = runner.invoke(cli.app, ["purchased", "ABC123", "Joe", "--quantity", "4"])
    assert r.exit_code == 0
    r = runner.invoke(cli.app, ["board"])
    assert "DONE" in r.stdout


def test_purchased_without_registration_fails():
    r = runner.invoke(cli.app, ["purchased", "ABC123", "Nobody", "--quantity", "2"])
    assert r.exit_code == 1


def test_calendar_export(monkeypatch, fake_event, tmp_path):
    # Give the fake event a dated on-sale so there is something to export.
    from ticketman.models import SalesWindow

    fake_event.public_sale = SalesWindow(start=datetime(2026, 6, 1, 14, 0, tzinfo=UTC))
    _patch_client(monkeypatch, fake_event)
    runner.invoke(cli.app, ["watchlist", "add", "ABC123"])
    out = tmp_path / "cal.ics"
    r = runner.invoke(cli.app, ["calendar", "--out", str(out)])
    assert r.exit_code == 0
    assert out.exists()
    assert "BEGIN:VCALENDAR" in out.read_text()


def test_outcome_and_calibrate(monkeypatch, fake_event):
    _patch_client(monkeypatch, fake_event)
    r = runner.invoke(cli.app, ["outcome", "set", "ABC123", "--sold-out"])
    assert r.exit_code == 0
    r = runner.invoke(cli.app, ["calibrate"])
    assert r.exit_code == 0
    assert "CALIBRATION" in r.stdout
