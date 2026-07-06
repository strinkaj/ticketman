"""Tests for the sellout scorer and presale planner."""

from __future__ import annotations

from ticketman.models import Event, Participant, PresaleWindow, Roster, SalesWindow, StrategyWeights
from ticketman.strategy import build_plan, score_sellout


def _hot_event() -> Event:
    return Event(
        id="HOT",
        name="Sold Out Tour",
        status="onsale",
        city="New York",
        genre="Pop",
        capacity=1800,
        price_max=450.0,
        presales=[
            PresaleWindow(name="Verified Fan Presale"),
            PresaleWindow(name="American Express Presale"),
            PresaleWindow(name="Artist Fan Club"),
        ],
        public_sale=SalesWindow(),
    )


def _cold_event() -> Event:
    return Event(
        id="COLD",
        name="Local Jazz Night",
        status="onsale",
        city="Dubuque",
        genre="Jazz",
        capacity=25000,
        price_max=35.0,
        presales=[],
        public_sale=SalesWindow(),
    )


def test_hot_scores_higher_than_cold():
    hot = score_sellout(_hot_event())
    cold = score_sellout(_cold_event())
    assert hot.score > cold.score
    assert hot.tier in ("High", "Extreme")
    assert cold.tier in ("Low", "Moderate")


def test_score_bounds_and_factor_count():
    s = score_sellout(_hot_event())
    assert 0.0 <= s.score <= 100.0
    assert len(s.factors) == 6
    # Contributions must reconcile with the reported score.
    total_weight = sum(f.weight for f in s.factors)
    recomputed = 100.0 * sum(f.contribution for f in s.factors) / total_weight
    assert abs(recomputed - s.score) < 0.1


def test_verified_fan_marker_detected():
    s = score_sellout(_hot_event())
    vf = next(f for f in s.factors if f.name == "Verified Fan / Platinum")
    assert vf.normalized >= 0.9


def test_weights_change_outcome():
    # An event whose ONLY strong signals are the Verified Fan presale and
    # presale density; everything else (market, genre, venue, price) is weak.
    # Muting the two strong factors must lower the score.
    e = Event(
        id="MIX",
        name="Niche Act, Big Presale Push",
        city="Dubuque",
        genre="Jazz",
        capacity=25000,
        price_max=30.0,
        presales=[
            PresaleWindow(name="Verified Fan Presale"),
            PresaleWindow(name="Presale Two"),
            PresaleWindow(name="Presale Three"),
        ],
    )
    base = score_sellout(e)
    muted = score_sellout(e, StrategyWeights(verified_fan=0.0, presale_density=0.0))
    assert muted.score < base.score


def test_plan_assigns_primary_and_matches_access():
    roster = Roster(
        participants=[
            Participant(name="Joe", access=["amex"]),
            Participant(name="Amy", access=["verified-fan"]),
        ]
    )
    plan = build_plan(_hot_event(), roster, target_qty=4)
    assert plan.group is not None
    assert plan.group.primary_buyer == "Joe"
    assert plan.group.backups == ["Amy"]

    amex_window = next(w for w in plan.windows if "Express" in w.name)
    assert "Joe" in amex_window.eligible
    assert "Amy" not in amex_window.eligible

    vf_window = next(w for w in plan.windows if "Verified Fan" in w.name)
    assert "Amy" in vf_window.eligible


def test_plan_without_roster():
    plan = build_plan(_hot_event(), Roster(), target_qty=4)
    assert plan.group is None
    assert "Sellout risk" in plan.recommendation
