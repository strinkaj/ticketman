"""Tests for iCalendar export."""

from __future__ import annotations

from datetime import UTC, datetime

from ticketman.ics import CalEvent, render_calendar

STAMP = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def test_render_calendar_structure():
    events = [
        CalEvent(
            uid="e1@ticketman",
            summary="On-sale: Big Act",
            start=datetime(2026, 6, 1, 14, 0, tzinfo=UTC),
            end=datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
            description="https://example.com",
        )
    ]
    out = render_calendar(events, stamp=STAMP)
    assert out.startswith("BEGIN:VCALENDAR")
    assert "END:VCALENDAR" in out
    assert "BEGIN:VEVENT" in out
    assert "DTSTART:20260601T140000Z" in out
    assert "DTEND:20260601T150000Z" in out
    assert "SUMMARY:On-sale: Big Act" in out
    assert out.endswith("\r\n")
    assert "\r\n" in out  # CRLF line endings


def test_render_calendar_default_end():
    events = [
        CalEvent(
            uid="e2@ticketman",
            summary="Deadline",
            start=datetime(2026, 6, 1, 14, 0, tzinfo=UTC),
        )
    ]
    out = render_calendar(events, stamp=STAMP)
    # No explicit end means start + 30 minutes.
    assert "DTEND:20260601T143000Z" in out


def test_escaping_special_chars():
    events = [
        CalEvent(
            uid="e3@ticketman",
            summary="Act, Venue; Night",
            start=datetime(2026, 6, 1, 14, 0, tzinfo=UTC),
        )
    ]
    out = render_calendar(events, stamp=STAMP)
    assert "SUMMARY:Act\\, Venue\\; Night" in out
