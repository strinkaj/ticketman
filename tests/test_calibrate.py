"""Tests for sellout-score calibration."""

from __future__ import annotations

from ticketman.calibrate import auc, calibrate
from ticketman.models import EventOutcome


def test_auc_perfect_separation():
    scores = [90.0, 80.0, 30.0, 20.0]
    labels = [True, True, False, False]
    assert auc(scores, labels) == 1.0


def test_auc_backwards():
    scores = [10.0, 20.0, 80.0, 90.0]
    labels = [True, True, False, False]
    assert auc(scores, labels) == 0.0


def test_auc_ties_count_half():
    scores = [50.0, 50.0]
    labels = [True, False]
    assert auc(scores, labels) == 0.5


def test_auc_single_class_returns_none():
    assert auc([1.0, 2.0], [True, True]) is None


def test_calibrate_reports_low_confidence_on_small_sample():
    outcomes = [
        EventOutcome(event_id="A", sold_out=True, score=88.0),
        EventOutcome(event_id="B", sold_out=False, score=30.0),
    ]
    result = calibrate(outcomes)
    assert result.n == 2
    assert result.n_sold_out == 1
    assert result.overall_auc == 1.0
    assert result.low_confidence is True


def test_calibrate_skips_unscored():
    outcomes = [
        EventOutcome(event_id="A", sold_out=True, score=88.0),
        EventOutcome(event_id="B", sold_out=False, score=None),
    ]
    result = calibrate(outcomes)
    assert result.n == 1
    assert any("no cached score" in note for note in result.notes)
