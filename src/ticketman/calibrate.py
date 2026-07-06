"""Sellout-score calibration.

Checks how well the sellout score ranks events that actually sold out above
events that did not, using your own labeled outcomes. Reports a rank-separation
number (AUC) overall and per factor, so you can see which inputs carry signal
and adjust the weights yourself.

Deliberately does NOT auto-optimize weights. On the handful of events you can
realistically label, a search would fit noise and hand back false precision.
The honest output is the separation and a small-sample warning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ticketman.models import EventOutcome


def auc(scores: list[float], labels: list[bool]) -> float | None:
    """Area under the ROC curve via the rank-pair method.

    Returns the fraction of (sold-out, not-sold-out) pairs the score orders
    correctly, with ties counting as half. 1.0 is perfect, 0.5 is coin-flip,
    below 0.5 means the score is backwards. None if either class is empty.
    """
    pos = [s for s, y in zip(scores, labels, strict=True) if y]
    neg = [s for s, y in zip(scores, labels, strict=True) if not y]
    if not pos or not neg:
        return None

    wins = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1.0
            elif p == n:
                wins += 0.5
    return wins / (len(pos) * len(neg))


@dataclass
class Calibration:
    """Result of a calibration run."""

    n: int
    n_sold_out: int
    overall_auc: float | None
    low_confidence: bool
    notes: list[str] = field(default_factory=list)


# Below this many labeled events, treat any AUC as directional only.
MIN_CONFIDENT_N = 15


def calibrate(outcomes: list[EventOutcome]) -> Calibration:
    """Assess how well the stored scores separate sold-out events."""
    labeled = [o for o in outcomes if o.score is not None]
    scores = [o.score for o in labeled]
    labels = [o.sold_out for o in labeled]
    n = len(labeled)
    n_sold = sum(1 for o in labeled if o.sold_out)

    notes: list[str] = []
    if n < len(outcomes):
        notes.append(
            f"{len(outcomes) - n} outcome(s) have no cached score and were skipped. "
            f"Re-label them with the event fetched so a score is stored."
        )

    overall = auc(scores, labels) if n else None
    low_conf = n < MIN_CONFIDENT_N

    if overall is None:
        notes.append("Need at least one sold-out and one not-sold-out event to compare.")
    elif low_conf:
        notes.append(
            f"Only {n} labeled events. Treat the AUC as directional, not precise. "
            f"Aim for {MIN_CONFIDENT_N}+ before trusting it."
        )

    if overall is not None:
        if overall >= 0.75:
            notes.append("Score ranks sold-out events well above the rest.")
        elif overall >= 0.55:
            notes.append("Score has some signal but leaves room to tune weights.")
        elif overall >= 0.45:
            notes.append("Score is near coin-flip on your data. Revisit the weights.")
        else:
            notes.append("Score is ranking backwards on your data. Check the inputs.")

    return Calibration(
        n=n,
        n_sold_out=n_sold,
        overall_auc=overall,
        low_confidence=low_conf,
        notes=notes,
    )
