"""Standardized signal and result schemas for the opportunity engine.

Every provider, no matter where its data comes from (live Google Trends, a
cached Amazon snapshot, or the local review dataset), returns the same
DemandSignal shape. The ranker only ever sees DemandSignal objects, so adding,
removing, or swapping a source never changes the ranking code.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SignalKind(str, Enum):
    """What a signal measures. Drives how the ranker weights it."""

    trend_momentum = "trend_momentum"        # is search interest rising or falling
    demand_growth = "demand_growth"          # internal review velocity from timestamped reviews
    surge = "surge"                          # short-term rank jump (Movers & Shakers)
    absolute_demand = "absolute_demand"      # how big the niche is (BSR / review volume)
    differentiation = "differentiation"      # how beatable incumbents are (pain density)


class SignalProvenance(str, Enum):
    """Honesty marker: where the number actually came from."""

    live = "live"               # fetched in real time this run
    cached = "cached"           # previously fetched, read from disk cache
    snapshot = "snapshot"       # one-time captured fixture (e.g. Amazon BSR)
    proxy = "proxy"             # estimated from another signal (e.g. reviews -> sales)
    unavailable = "unavailable"  # source could not be reached


class DemandSignal(BaseModel):
    """One normalized signal about one niche from one provider."""

    kind: SignalKind
    provider: str
    # 0-100 normalized score the ranker consumes. Higher = more attractive.
    score: float = 0.0
    provenance: SignalProvenance = SignalProvenance.unavailable
    # 0-1 how much to trust this number (live real data > proxy estimate).
    confidence: float = 0.5
    # Human-readable basis for the score, shown in the UI / interview.
    evidence: str = ""
    # Raw numbers behind the score for audit (slope %, review_count, etc.).
    detail: dict[str, Any] = Field(default_factory=dict)


class NicheCandidate(BaseModel):
    """A candidate keyword/niche to be scored. May be human-given or discovered."""

    keyword: str
    source: str = "manual"  # manual | trends_rising | title_ngram
    note: str = ""


class OpportunityScore(BaseModel):
    """Final ranked result for one niche."""

    keyword: str
    score: float                       # weighted composite, 0-100
    rank: int = 0
    signals: list[DemandSignal] = Field(default_factory=list)
    discovery_source: str = "manual"
    # Per-kind contribution after weighting, for transparency.
    contribution: dict[str, float] = Field(default_factory=dict)
    missing_signals: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
