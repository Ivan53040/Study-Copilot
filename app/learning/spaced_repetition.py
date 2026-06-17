"""Simple spaced-repetition scheduling (plan §18).

Incorrect      -> review tomorrow
Partial        -> review in 3 days
Correct (low confidence)  -> review in 7 days
Correct (good/strong)     -> review in 14-30 days

Later this can be swapped for SM-2 / FSRS behind the same call.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def next_interval_days(outcome: str, confidence: float) -> int:
    if outcome == "incorrect":
        return 1
    if outcome == "partial":
        return 3
    # correct
    if confidence < 0.70:
        return 7
    if confidence < 0.85:
        return 14
    return 30


def next_review_date(
    outcome: str, confidence: float, now: datetime | None = None
) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now + timedelta(days=next_interval_days(outcome, confidence))
