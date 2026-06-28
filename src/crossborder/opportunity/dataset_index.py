"""Local Amazon Reviews 2023 index for the opportunity engine.

Scanning 60K products and 494K reviews per niche would be far too slow, so this
module builds two cached indexes once:

1. meta index   compact per-product rows (title blob, review_count, rating,
                price) kept in memory for fast keyword matching.
2. review digest one streaming pass over the review file produces a per-ASIN
                summary (total reviews, negative-review count, top pain topics,
                recent/prior review windows), cached to disk. Differentiation
                and review-velocity lookups then cost O(pool size).

Both providers (absolute demand, differentiation) read from these indexes, so a
niche is scored with a couple of dict lookups instead of a full file scan.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = ROOT / "data" / "amazon_reviews_2023"
CACHE_DIR = ROOT / "data" / "cache" / "dataset"

DEFAULT_META = DATA_DIR / "meta_Health_and_Personal_Care.jsonl"
DEFAULT_REVIEWS = DATA_DIR / "Health_and_Personal_Care.jsonl"

# Generic negative-experience pain buckets. Category-specific tuning can be
# layered on later; these cover the recurring complaints across phys. products.
PAIN_KEYWORDS: dict[str, set[str]] = {
    "做工差/易坏": {"broke", "broken", "stopped working", "died after", "cheap", "flimsy", "quit working", "fell apart"},
    "电池/续航": {"battery", "charge", "charging", "dies", "died", "won't charge"},
    "力度/性能不足": {"weak", "not strong", "too gentle", "barely", "no power", "not powerful", "underpowered"},
    "太吵": {"loud", "noisy", "noise"},
    "发热/温控问题": {"too hot", "burn", "overheat", "not warm", "no heat", "stopped heating"},
    "难用/说明差": {"hard to use", "complicated", "confusing", "instructions", "difficult to"},
    "尺寸/贴合差": {"too big", "too small", "doesn't fit", "does not fit", "bulky", "too heavy"},
    "气味/材质差": {"smell", "odor", "chemical", "rash", "irritation"},
}


def _terms(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) >= 2]


def _row_blob(d: dict[str, Any]) -> str:
    return " ".join(
        [
            str(d.get("title", "")),
            " ".join(d.get("features") or []),
            " ".join(d.get("description") or []),
        ]
    ).lower()


def _price(value: Any) -> float | None:
    if value is None:
        return None
    match = re.search(r"[0-9]+(?:\.[0-9]+)?", str(value))
    return float(match.group()) if match else None


class DatasetIndex:
    """Holds the in-memory meta index and the cached per-ASIN review digest."""

    def __init__(self, meta_path: Path = DEFAULT_META, review_path: Path = DEFAULT_REVIEWS):
        self.meta_path = meta_path
        self.review_path = review_path
        self._meta: list[dict[str, Any]] | None = None
        self._digest: dict[str, dict[str, Any]] | None = None

    # -- meta index --------------------------------------------------------- #
    @property
    def meta(self) -> list[dict[str, Any]]:
        if self._meta is None:
            self._meta = self._load_meta()
        return self._meta

    def _load_meta(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with open(self.meta_path, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                rows.append(
                    {
                        "asin": d.get("parent_asin") or d.get("asin") or "",
                        "title": d.get("title", ""),
                        "blob": _row_blob(d),
                        "review_count": int(d.get("rating_number") or 0),
                        "rating": float(d.get("average_rating") or 0) or None,
                        "price": _price(d.get("price")),
                        "store": d.get("store", ""),
                    }
                )
        return rows

    def match(self, keyword: str, min_reviews: int = 50, top_n: int = 20) -> list[dict[str, Any]]:
        """Keyword-match the meta index, gate by review count, rank by popularity."""
        terms = _terms(keyword)
        if not terms:
            return []
        hits = [r for r in self.meta if all(t in r["blob"] for t in terms)]
        pool = [r for r in hits if r["review_count"] >= min_reviews]
        pool.sort(key=lambda r: r["review_count"] * (r["rating"] or 0), reverse=True)
        return pool[:top_n]

    # -- review digest ------------------------------------------------------ #
    @property
    def digest(self) -> dict[str, dict[str, Any]]:
        if self._digest is None:
            self._digest = self._load_or_build_digest()
        return self._digest

    def _digest_cache_path(self) -> Path:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return CACHE_DIR / f"review_digest_v2_{self.review_path.stem}.json"

    def _load_or_build_digest(self) -> dict[str, dict[str, Any]]:
        cache = self._digest_cache_path()
        if cache.exists():
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        digest = self._build_digest()
        try:
            cache.write_text(json.dumps(digest, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return digest

    def _build_digest(self) -> dict[str, dict[str, Any]]:
        """One streaming pass: per-ASIN counts, pain topics, and review windows."""
        total: Counter[str] = Counter()
        negative: Counter[str] = Counter()
        pains: dict[str, Counter[str]] = defaultdict(Counter)
        timestamps: dict[str, list[int]] = defaultdict(list)
        max_ts: int | None = None
        with open(self.review_path, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                asin = d.get("parent_asin") or d.get("asin") or ""
                if not asin:
                    continue
                total[asin] += 1
                ts = _timestamp_ms(d.get("timestamp"))
                if ts is not None:
                    timestamps[asin].append(ts)
                    max_ts = ts if max_ts is None else max(max_ts, ts)
                rating = d.get("rating") or 5
                if rating > 3:
                    continue
                negative[asin] += 1
                text = f"{d.get('title', '')} {d.get('text', '')}".lower()
                for topic, kws in PAIN_KEYWORDS.items():
                    if any(k in text for k in kws):
                        pains[asin][topic] += 1
        one_year_ms = 365 * 86400 * 1000
        recent_cutoff = (max_ts - one_year_ms) if max_ts is not None else None
        prior_cutoff = (max_ts - 2 * one_year_ms) if max_ts is not None else None

        digest: dict[str, dict[str, Any]] = {}
        for asin, tot in total.items():
            recent_reviews = 0
            prior_reviews = 0
            if recent_cutoff is not None and prior_cutoff is not None:
                for ts in timestamps.get(asin, []):
                    if ts > recent_cutoff:
                        recent_reviews += 1
                    elif ts > prior_cutoff:
                        prior_reviews += 1
            digest[asin] = {
                "total": tot,
                "negative": negative.get(asin, 0),
                "pains": dict(pains.get(asin, {})),
                "recent_reviews": recent_reviews,
                "prior_reviews": prior_reviews,
            }
        return digest


def _timestamp_ms(value: Any) -> int | None:
    if value is None:
        return None
    try:
        ts = int(float(value))
    except (TypeError, ValueError):
        return None
    return ts if ts > 0 else None
