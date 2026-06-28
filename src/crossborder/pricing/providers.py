"""Pluggable price providers for shortlisted marketplace ASINs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PRICE_CACHE = ROOT / "data" / "cache" / "prices"


class PriceProvenance(str, Enum):
    live = "live"
    cached = "cached"
    manual = "manual"
    stub = "stub"
    unavailable = "unavailable"


class PriceQuote(BaseModel):
    asin: str
    price: float | None = None
    currency: str = "USD"
    provenance: PriceProvenance = PriceProvenance.unavailable
    source: str = ""
    fetched_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class PriceProvider(ABC):
    name: str

    @abstractmethod
    def fetch_price(self, asin: str) -> PriceQuote:
        """Return a quote. Providers degrade to unavailable instead of raising."""


class ManualPriceProvider(PriceProvider):
    name = "manual_price_provider"

    def __init__(self, path: Path):
        self.path = path
        self._prices = self._load(path)

    def fetch_price(self, asin: str) -> PriceQuote:
        price = self._prices.get(asin)
        if price is None:
            return PriceQuote(asin=asin, provenance=PriceProvenance.unavailable, source=self.name)
        return PriceQuote(asin=asin, price=price, provenance=PriceProvenance.manual, source=self.name)

    @staticmethod
    def _load(path: Path) -> dict[str, float]:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        prices: dict[str, float] = {}
        if not isinstance(raw, dict):
            return prices
        for asin, value in raw.items():
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if price > 0:
                prices[str(asin)] = round(price, 2)
        return prices


class StubPriceProvider(PriceProvider):
    name = "stub_price_provider"

    def fetch_price(self, asin: str) -> PriceQuote:
        value = int(sha256(asin.encode("utf-8")).hexdigest()[:6], 16) % 60
        return PriceQuote(
            asin=asin,
            price=float(15 + value),
            provenance=PriceProvenance.stub,
            source=self.name,
        )


class KeepaPriceProvider(PriceProvider):
    """Best-effort Keepa-style provider.

    This intentionally avoids a hard dependency on the keepa package. All
    failures, missing keys, unexpected formats, and no-price responses degrade
    to an unavailable quote so product research can continue safely.
    """

    name = "keepa_price_provider"

    def __init__(self, api_key: str | None = None, cache_dir: Path = DEFAULT_PRICE_CACHE):
        self.api_key = api_key if api_key is not None else os.environ.get("KEEPA_API_KEY")
        self.cache_dir = cache_dir

    def fetch_price(self, asin: str) -> PriceQuote:
        if not self.api_key:
            return PriceQuote(asin=asin, provenance=PriceProvenance.unavailable, source=self.name)
        cached = self._read_cache(asin)
        if cached is not None:
            return cached
        try:
            quote = self._fetch_live(asin)
        except Exception:
            return PriceQuote(asin=asin, provenance=PriceProvenance.unavailable, source=self.name)
        if quote.price is not None:
            self._write_cache(asin, quote)
        return quote

    def _fetch_live(self, asin: str) -> PriceQuote:
        params = urlencode({"key": self.api_key, "domain": 1, "asin": asin, "stats": 30})
        with urlopen(f"https://api.keepa.com/product?{params}", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        price = self._extract_price(payload)
        if price is None:
            return PriceQuote(asin=asin, provenance=PriceProvenance.unavailable, source=self.name)
        return PriceQuote(asin=asin, price=price, provenance=PriceProvenance.live, source=self.name)

    def _read_cache(self, asin: str) -> PriceQuote | None:
        path = self.cache_dir / f"{asin}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["provenance"] = PriceProvenance.cached.value
            return PriceQuote.model_validate(data)
        except (OSError, json.JSONDecodeError, ValueError):
            return None

    def _write_cache(self, asin: str, quote: PriceQuote) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            (self.cache_dir / f"{asin}.json").write_text(
                json.dumps(quote.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    @staticmethod
    def _extract_price(payload: dict[str, Any]) -> float | None:
        products = payload.get("products") or []
        if not products:
            return None
        product = products[0] or {}
        stats = product.get("stats") or {}
        candidates = [
            stats.get("current", [None])[1] if isinstance(stats.get("current"), list) and len(stats.get("current")) > 1 else None,
            stats.get("buyBoxPrice"),
            stats.get("avg30", [None])[1] if isinstance(stats.get("avg30"), list) and len(stats.get("avg30")) > 1 else None,
        ]
        for value in candidates:
            try:
                cents = int(value)
            except (TypeError, ValueError):
                continue
            if cents > 0:
                return round(cents / 100, 2)
        return None
