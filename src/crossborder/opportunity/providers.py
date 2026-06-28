"""Pluggable demand-signal providers.

Each provider implements one method: fetch(keyword) -> DemandSignal. The ranker
depends only on this interface, so a signal can move from live to cached to
snapshot to a paid API without the ranking logic ever changing.

Providers here:
- GoogleTrendsProvider   live trend momentum + rising-query discovery (cached)
- ReviewDemandProvider   absolute demand from the local review dataset
- ReviewVelocityProvider demand growth from timestamped local reviews
- DifferentiationProvider differentiation room from local negative reviews
- AmazonSnapshotProvider absolute demand from a captured Best Sellers snapshot
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from hashlib import sha256
import json
from pathlib import Path
import re
import time
from typing import Any

from crossborder.opportunity.signals import (
    DemandSignal,
    NicheCandidate,
    SignalKind,
    SignalProvenance,
)

ROOT = Path(__file__).resolve().parents[3]
TRENDS_CACHE = ROOT / "data" / "cache" / "trends"


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _terms(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 2]


class DemandSignalProvider(ABC):
    """A source of one kind of demand signal for a niche keyword."""

    kind: SignalKind
    name: str

    @abstractmethod
    def fetch(self, keyword: str) -> DemandSignal:
        """Return a normalized DemandSignal for this keyword."""


# --------------------------------------------------------------------------- #
# Google Trends: trend momentum + rising-query niche discovery
# --------------------------------------------------------------------------- #
class GoogleTrendsProvider(DemandSignalProvider):
    """Live Google Trends momentum via pytrends, cached to disk.

    pytrends is unofficial and rate-limited, so every keyword response is cached
    to data/cache/trends/. Score maps the 12-month slope to 0-100: flat = 50,
    strong rise pushes toward 100, sustained decline toward 0.
    """

    kind = SignalKind.trend_momentum
    name = "google_trends"

    def __init__(self, geo: str = "US", timeframe: str = "today 12-m", cache_ttl_days: int = 7):
        self.geo = geo
        self.timeframe = timeframe
        self.cache_ttl_seconds = cache_ttl_days * 86400
        TRENDS_CACHE.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, keyword: str) -> Path:
        key = sha256(f"{keyword}|{self.geo}|{self.timeframe}".encode()).hexdigest()[:16]
        return TRENDS_CACHE / f"{key}.json"

    def _read_cache(self, keyword: str) -> dict[str, Any] | None:
        path = self._cache_path(keyword)
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > self.cache_ttl_seconds:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache(self, keyword: str, payload: dict[str, Any]) -> None:
        try:
            self._cache_path(keyword).write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            pass

    def _fetch_raw(self, keyword: str) -> dict[str, Any]:
        """Hit pytrends. Returns {'series': [...], 'rising': [{query,value}]}."""
        from pytrends.request import TrendReq

        pt = TrendReq(hl="en-US", tz=360)
        pt.build_payload([keyword], timeframe=self.timeframe, geo=self.geo)
        iot = pt.interest_over_time()
        series = [] if iot.empty else [int(v) for v in iot[keyword].tolist()]
        rising: list[dict[str, Any]] = []
        try:
            rq = pt.related_queries().get(keyword, {})
            rising_df = rq.get("rising") if rq else None
            if rising_df is not None and not rising_df.empty:
                rising = [
                    {"query": str(r["query"]), "value": int(r["value"])}
                    for _, r in rising_df.head(10).iterrows()
                ]
        except Exception:
            rising = []
        return {"series": series, "rising": rising}

    @staticmethod
    def _slope_pct(series: list[int]) -> float | None:
        """Percent change of the last third vs the first third of the window."""
        n = len(series)
        if n < 6:
            return None
        third = max(1, n // 3)
        early = sum(series[:third]) / third
        late = sum(series[-third:]) / third
        if early <= 0:
            return 100.0 if late > 0 else 0.0
        return (late - early) / early * 100

    def fetch(self, keyword: str) -> DemandSignal:
        cached = self._read_cache(keyword)
        provenance = SignalProvenance.cached
        if cached is None:
            try:
                cached = self._fetch_raw(keyword)
                self._write_cache(keyword, cached)
                provenance = SignalProvenance.live
            except Exception as exc:  # network / rate limit / pytrends missing
                return DemandSignal(
                    kind=self.kind,
                    provider=self.name,
                    score=0.0,
                    provenance=SignalProvenance.unavailable,
                    confidence=0.0,
                    evidence=f"Google Trends unavailable: {type(exc).__name__}",
                )

        series = cached.get("series") or []
        slope = self._slope_pct(series)
        if slope is None:
            return DemandSignal(
                kind=self.kind,
                provider=self.name,
                score=40.0,
                provenance=provenance,
                confidence=0.3,
                evidence="Too little trend data to judge momentum.",
                detail={"series_points": len(series)},
            )
        # Map slope to 0-100. +200% -> ~100, flat -> 50, -100% -> ~0.
        score = _clamp(50 + slope * 0.25)
        recent_level = sum(series[-max(1, len(series) // 4):]) / max(1, len(series) // 4)
        return DemandSignal(
            kind=self.kind,
            provider=self.name,
            score=round(score, 1),
            provenance=provenance,
            confidence=0.85 if provenance == SignalProvenance.live else 0.8,
            evidence=(
                f"搜索热度 12 个月变化 {slope:+.0f}%（近期热度水平 {recent_level:.0f}/100）。"
            ),
            detail={
                "slope_pct": round(slope, 1),
                "recent_level": round(recent_level, 1),
                "series_points": len(series),
                "rising_query_count": len(cached.get("rising") or []),
            },
        )

    def discover_rising(self, seed_keyword: str) -> list[NicheCandidate]:
        """Use Google Trends rising related queries as discovered niche candidates."""
        cached = self._read_cache(seed_keyword)
        if cached is None:
            try:
                cached = self._fetch_raw(seed_keyword)
                self._write_cache(seed_keyword, cached)
            except Exception:
                return []
        candidates: list[NicheCandidate] = []
        for item in cached.get("rising") or []:
            query = _clean_query(item.get("query", ""))
            if not query or query == seed_keyword.lower():
                continue
            candidates.append(
                NicheCandidate(
                    keyword=query,
                    source="trends_rising",
                    note=f"Google Trends 上升查询 +{item.get('value', 0)}%",
                )
            )
        return candidates


def _clean_query(query: str) -> str:
    """Drop brand/model noise so rising queries map to sellable niches."""
    return re.sub(r"\s+", " ", query.strip().lower())


# --------------------------------------------------------------------------- #
# Review dataset: absolute demand + differentiation room (real local data)
# --------------------------------------------------------------------------- #
class ReviewDemandProvider(DemandSignalProvider):
    """Absolute demand proxy from the niche's competitor review volume.

    No public sales data exists, so we proxy market size with the total review
    count of the top matched listings (meta rating_number). Honestly labeled as
    a proxy, this is the same reverse-engineering third-party tools do with BSR.
    """

    kind = SignalKind.absolute_demand
    name = "review_volume_proxy"

    def __init__(self, index, min_reviews: int = 50, top_n: int = 20):
        self.index = index
        self.min_reviews = min_reviews
        self.top_n = top_n

    def fetch(self, keyword: str) -> DemandSignal:
        pool = self.index.match(keyword, self.min_reviews, self.top_n)
        if not pool:
            return DemandSignal(
                kind=self.kind,
                provider=self.name,
                score=0.0,
                provenance=SignalProvenance.unavailable,
                confidence=0.3,
                evidence="数据集中没有评论数达标的竞品。",
            )
        total_reviews = sum(r["review_count"] for r in pool)
        # Log-ish mapping: 500 reviews -> ~40, 5k -> ~70, 50k -> ~100.
        import math

        score = _clamp(20 + 23 * math.log10(max(total_reviews, 1)))
        return DemandSignal(
            kind=self.kind,
            provider=self.name,
            score=round(score, 1),
            provenance=SignalProvenance.proxy,
            confidence=0.55,
            evidence=(
                f"Top {len(pool)} 竞品累计 {total_reviews:,} 条评论（销量代理，非真实销量）。"
            ),
            detail={
                "pool_size": len(pool),
                "total_reviews": total_reviews,
                "top_review_count": pool[0]["review_count"],
            },
        )


class ReviewVelocityProvider(DemandSignalProvider):
    """Demand-growth proxy from timestamped reviews in the local dataset.

    Unlike Google Trends, this is internal marketplace behavior: compare review
    volume in the latest 12-month window against the previous 12-month window.
    It is still a proxy, because reviews are not sales, but it adds direction to
    the existing stock-volume signal.
    """

    kind = SignalKind.demand_growth
    name = "review_velocity"

    def __init__(self, index, min_reviews: int = 50, top_n: int = 20):
        self.index = index
        self.min_reviews = min_reviews
        self.top_n = top_n

    def fetch(self, keyword: str) -> DemandSignal:
        pool = self.index.match(keyword, self.min_reviews, self.top_n)
        if not pool:
            return DemandSignal(
                kind=self.kind,
                provider=self.name,
                score=0.0,
                provenance=SignalProvenance.unavailable,
                confidence=0.3,
                evidence="数据集中没有评论数达标的竞品，无法计算评论增速。",
            )

        digest = self.index.digest
        recent_total = 0
        prior_total = 0
        covered = 0
        for row in pool:
            entry = digest.get(row["asin"])
            if not entry:
                continue
            recent_total += int(entry.get("recent_reviews") or 0)
            prior_total += int(entry.get("prior_reviews") or 0)
            if "recent_reviews" in entry or "prior_reviews" in entry:
                covered += 1

        if recent_total + prior_total == 0:
            return DemandSignal(
                kind=self.kind,
                provider=self.name,
                score=40.0,
                provenance=SignalProvenance.proxy,
                confidence=0.3,
                evidence="评论文件未覆盖这些竞品的时间戳窗口，评论增速按中性代理分处理。",
                detail={
                    "covered_competitors": covered,
                    "recent_reviews": recent_total,
                    "prior_reviews": prior_total,
                    "growth": None,
                },
            )

        growth = recent_total / max(prior_total, 1)
        score = _clamp(40 + (growth - 1) * 40)
        return DemandSignal(
            kind=self.kind,
            provider=self.name,
            score=round(score, 1),
            provenance=SignalProvenance.proxy,
            confidence=0.6,
            evidence=(
                f"近12月 {recent_total:,} 条评论 vs 前12月 {prior_total:,} 条，"
                f"增速 {growth:.1f}×（数据集内部需求信号）。"
            ),
            detail={
                "covered_competitors": covered,
                "recent_reviews": recent_total,
                "prior_reviews": prior_total,
                "growth": round(growth, 3),
            },
        )


class DifferentiationProvider(DemandSignalProvider):
    """How beatable incumbents are, from negative-review density and pain topics.

    This is the dataset's strongest, most defensible signal: real 1-3 star
    reviews of the top listings reveal recurring complaints a new entrant can
    fix. High negative-review density + concentrated pain = more room to win.
    """

    kind = SignalKind.differentiation
    name = "review_pain_density"

    def __init__(self, index, min_reviews: int = 50, top_n: int = 20):
        self.index = index
        self.min_reviews = min_reviews
        self.top_n = top_n

    def fetch(self, keyword: str) -> DemandSignal:
        pool = self.index.match(keyword, self.min_reviews, self.top_n)
        if not pool:
            return DemandSignal(
                kind=self.kind,
                provider=self.name,
                score=0.0,
                provenance=SignalProvenance.unavailable,
                confidence=0.3,
                evidence="无竞品可分析差评。",
            )
        digest = self.index.digest
        total = 0
        negative = 0
        pain_counter: dict[str, int] = {}
        covered = 0
        for row in pool:
            entry = digest.get(row["asin"])
            if not entry:
                continue
            covered += 1
            total += entry["total"]
            negative += entry["negative"]
            for topic, count in entry["pains"].items():
                pain_counter[topic] = pain_counter.get(topic, 0) + count
        if total == 0:
            return DemandSignal(
                kind=self.kind,
                provider=self.name,
                score=40.0,
                provenance=SignalProvenance.proxy,
                confidence=0.3,
                evidence="评论文件中未覆盖到这些竞品的评论。",
                detail={"covered_competitors": covered},
            )
        neg_rate = negative / total
        top_pains = sorted(pain_counter.items(), key=lambda kv: kv[1], reverse=True)[:3]
        # Higher negative density -> more differentiation room. 0% -> 25, 30% -> ~85.
        score = _clamp(25 + neg_rate * 200)
        pain_text = "、".join(f"{t}×{c}" for t, c in top_pains) or "无集中痛点"
        return DemandSignal(
            kind=self.kind,
            provider=self.name,
            score=round(score, 1),
            provenance=SignalProvenance.proxy,
            confidence=0.7,
            evidence=(
                f"头部竞品差评率 {neg_rate * 100:.0f}%，主要痛点：{pain_text}。差评越集中越好打。"
            ),
            detail={
                "covered_competitors": covered,
                "negative_rate": round(neg_rate, 3),
                "top_pains": top_pains,
            },
        )


# --------------------------------------------------------------------------- #
# Amazon Best Sellers: absolute demand from a captured snapshot
# --------------------------------------------------------------------------- #
class AmazonSnapshotProvider(DemandSignalProvider):
    """Absolute demand / surge from a one-time captured Best Sellers snapshot.

    Amazon serves a degraded page to non-browser clients, so live scraping is
    unreliable. This provider reads a captured snapshot fixture; in production
    the same interface fronts a Rainforest-style scraping API. Provenance is
    marked 'snapshot' so the UI never pretends the rank is live.
    """

    kind = SignalKind.surge
    name = "amazon_bestsellers_snapshot"

    def __init__(self, snapshot_path: Path | None = None):
        self.snapshot_path = snapshot_path
        self._rows: list[dict[str, Any]] | None = None

    def _load(self) -> list[dict[str, Any]]:
        if self._rows is not None:
            return self._rows
        if not self.snapshot_path or not Path(self.snapshot_path).exists():
            self._rows = []
            return self._rows
        try:
            self._rows = json.loads(Path(self.snapshot_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._rows = []
        return self._rows

    def fetch(self, keyword: str) -> DemandSignal:
        rows = self._load()
        if not rows:
            return DemandSignal(
                kind=self.kind,
                provider=self.name,
                score=0.0,
                provenance=SignalProvenance.unavailable,
                confidence=0.0,
                evidence="无 Best Sellers 快照（生产环境接 Rainforest API）。",
            )
        terms = _terms(keyword)
        best = None
        for row in rows:
            blob = str(row.get("title", "")).lower()
            if all(t in blob for t in terms):
                rank = int(row.get("rank") or 999)
                if best is None or rank < best.get("rank", 999):
                    best = {**row, "rank": rank}
        if best is None:
            return DemandSignal(
                kind=self.kind,
                provider=self.name,
                score=30.0,
                provenance=SignalProvenance.snapshot,
                confidence=0.4,
                evidence="该赛道不在 Best Sellers 前 100，热度有限。",
            )
        rank = best["rank"]
        score = _clamp(100 - (rank - 1) * (60 / 100))  # rank1 -> 100, rank100 -> ~40
        return DemandSignal(
            kind=self.kind,
            provider=self.name,
            score=round(score, 1),
            provenance=SignalProvenance.snapshot,
            confidence=0.6,
            evidence=f"Best Sellers 快照排名 #{rank}（{best.get('title', '')[:40]}）。",
            detail={"rank": rank, "is_mover": bool(best.get("is_mover"))},
        )
