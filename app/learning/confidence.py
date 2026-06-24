"""Transparent concept-confidence scoring (plan §17).

confidence = 0.50*recent_accuracy + 0.20*long_term_accuracy
           + 0.15*review_recency  + 0.15*difficulty_performance

Everything is derived from recorded LearningEvents so the score is auditable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

W_RECENT = 0.50
W_LONG = 0.20
W_RECENCY = 0.15
W_DIFFICULTY = 0.15

RECENT_WINDOW = 5
RECENCY_HALFLIFE_DAYS = 14.0

DIFFICULTY_WEIGHT = {"easy": 1.0, "medium": 2.0, "hard": 3.0}

# Status bands (plan §17).
_BANDS = [
    (0.85, "strong"),
    (0.70, "good"),
    (0.40, "developing"),
    (0.0, "weak"),
]


@dataclass
class EventLike:
    score: float
    max_score: float
    difficulty: str | None
    timestamp: datetime


def status_band(confidence: float) -> str:
    for threshold, label in _BANDS:
        if confidence >= threshold:
            return label
    return "weak"


def _accuracy(events: list[EventLike]) -> float:
    total = sum(e.max_score for e in events)
    if total <= 0:
        return 0.0
    return sum(e.score for e in events) / total


def _difficulty_accuracy(events: list[EventLike]) -> float:
    num = den = 0.0
    for e in events:
        w = DIFFICULTY_WEIGHT.get((e.difficulty or "medium").lower(), 2.0)
        num += e.score * w
        den += e.max_score * w
    return num / den if den > 0 else 0.0


def _recency(events: list[EventLike], now: datetime) -> float:
    last = max(e.timestamp for e in events)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - last).total_seconds() / 86400.0)
    return math.pow(0.5, days / RECENCY_HALFLIFE_DAYS)


def compute_confidence(
    events: list[EventLike], now: datetime | None = None
) -> tuple[float, dict]:
    if not events:
        return 0.0, {"events": 0}
    now = now or datetime.now(timezone.utc)
    events = sorted(events, key=lambda e: e.timestamp)

    recent = events[-RECENT_WINDOW:]
    recent_acc = _accuracy(recent)
    long_acc = _accuracy(events)
    recency = _recency(events, now)
    diff_acc = _difficulty_accuracy(events)

    confidence = (
        W_RECENT * recent_acc
        + W_LONG * long_acc
        + W_RECENCY * recency
        + W_DIFFICULTY * diff_acc
    )
    confidence = max(0.0, min(1.0, confidence))
    evidence = {
        "events": len(events),
        "recent_accuracy": round(recent_acc, 3),
        "long_term_accuracy": round(long_acc, 3),
        "review_recency": round(recency, 3),
        "difficulty_performance": round(diff_acc, 3),
    }
    return confidence, evidence
