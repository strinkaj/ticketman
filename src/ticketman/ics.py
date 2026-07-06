"""iCalendar export.

Writes a standard .ics file with a timed event for every deadline and sale
window under coordination: registration deadlines, presale and public on-sale
windows, and the purchase windows of anyone who won. Import it once into Google
or Apple Calendar. This is static file generation, not live alerting.

Hand-rolled VEVENTs, no dependency. We emit UTC timestamps (the trailing Z
form), which every calendar app renders in the viewer's local time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class CalEvent:
    """One calendar entry."""

    uid: str
    summary: str
    start: datetime
    end: datetime | None = None
    description: str = ""


def _fmt(dt: datetime) -> str:
    from datetime import UTC

    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _escape(text: str) -> str:
    # iCalendar text escaping: backslash, comma, semicolon, newline.
    return (
        text.replace("\\", "\\\\")
        .replace(",", "\\,")
        .replace(";", "\\;")
        .replace("\n", "\\n")
    )


def render_calendar(events: list[CalEvent], *, stamp: datetime) -> str:
    """Render a full VCALENDAR string.

    `stamp` is the DTSTAMP applied to every VEVENT. Pass a fixed timestamp so
    output is deterministic and testable.
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ticketman//EN",
        "CALSCALE:GREGORIAN",
    ]
    for ev in events:
        end = ev.end or (ev.start + timedelta(minutes=30))
        lines += [
            "BEGIN:VEVENT",
            f"UID:{ev.uid}",
            f"DTSTAMP:{_fmt(stamp)}",
            f"DTSTART:{_fmt(ev.start)}",
            f"DTEND:{_fmt(end)}",
            f"SUMMARY:{_escape(ev.summary)}",
        ]
        if ev.description:
            lines.append(f"DESCRIPTION:{_escape(ev.description)}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    # iCalendar requires CRLF line endings.
    return "\r\n".join(lines) + "\r\n"
