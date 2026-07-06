"""Tests for Discovery API parsing (no network)."""

from __future__ import annotations

import pytest

from ticketman.discovery import extract_event_id, parse_event

SAMPLE = {
    "id": "0B00612D7C1E5A3F",
    "name": "Big Act - Live",
    "url": "https://www.ticketmaster.com/event/0B00612D7C1E5A3F",
    "dates": {
        "start": {
            "localDate": "2026-09-12",
            "localTime": "20:00:00",
            "dateTime": "2026-09-13T00:00:00Z",
        },
        "status": {"code": "onsale"},
    },
    "sales": {
        "public": {
            "startDateTime": "2026-05-01T14:00:00Z",
            "endDateTime": "2026-09-12T23:00:00Z",
        },
        "presales": [
            {
                "name": "Verified Fan Presale",
                "startDateTime": "2026-04-28T14:00:00Z",
                "endDateTime": "2026-04-28T22:00:00Z",
            },
            {
                "name": "American Express Card Member Presale",
                "startDateTime": "2026-04-29T14:00:00Z",
                "endDateTime": "2026-04-30T22:00:00Z",
            },
        ],
    },
    "priceRanges": [{"type": "standard", "currency": "USD", "min": 49.5, "max": 425.0}],
    "classifications": [{"segment": {"name": "Music"}, "genre": {"name": "Pop"}}],
    "_embedded": {
        "venues": [
            {
                "name": "Madison Square Garden",
                "city": {"name": "New York"},
                "state": {"stateCode": "NY"},
                "timezone": "America/New_York",
                "capacity": 20000,
            }
        ]
    },
}


def test_extract_event_id_from_url():
    url = "https://www.ticketmaster.com/artist/event/0B00612D7C1E5A3F"
    assert extract_event_id(url) == "0B00612D7C1E5A3F"


def test_extract_event_id_from_bare_id():
    assert extract_event_id("0B00612D7C1E5A3F") == "0B00612D7C1E5A3F"


def test_extract_event_id_invalid():
    with pytest.raises(ValueError):
        extract_event_id("not a url or id!!")


def test_parse_event_core_fields():
    e = parse_event(SAMPLE)
    assert e.id == "0B00612D7C1E5A3F"
    assert e.status == "onsale"
    assert e.city == "New York"
    assert e.capacity == 20000
    assert e.genre == "Pop"
    assert e.price_min == 49.5
    assert e.price_max == 425.0


def test_parse_event_windows():
    e = parse_event(SAMPLE)
    assert len(e.presales) == 2
    assert e.presales[0].name == "Verified Fan Presale"
    assert e.presales[0].start is not None
    assert e.public_sale is not None
    assert e.public_sale.start is not None


def test_parse_event_tolerates_missing_fields():
    e = parse_event({"id": "X", "name": "Bare Event"})
    assert e.id == "X"
    assert e.presales == []
    assert e.public_sale is None
    assert e.price_max is None
