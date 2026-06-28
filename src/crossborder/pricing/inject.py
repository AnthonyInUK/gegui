"""Inject real or provider-backed prices into product research requests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from crossborder.data_intake.amazon_reviews_2023_loader import build_product_research_request
from crossborder.opportunity.dataset_index import DEFAULT_META, DEFAULT_REVIEWS
from crossborder.pricing.providers import ManualPriceProvider, PriceProvider, PriceQuote, StubPriceProvider
from crossborder.product_research import _price_coverage, research_product
from crossborder.schemas import CostModel, ProductResearchRequest

DEFAULT_MANUAL_PRICES = ROOT / "examples" / "crossborder" / "manual_prices.json"


def inject_real_prices(
    req: ProductResearchRequest,
    provider: PriceProvider,
    *,
    top_n: int = 3,
    unit_cost: float | None = None,
) -> tuple[ProductResearchRequest, list[PriceQuote]]:
    missing = [c for c in req.competitors if c.price is None]
    missing.sort(key=lambda item: item.review_count or 0, reverse=True)
    target_asins = {c.asin for c in missing[:top_n] if c.asin}
    quotes: list[PriceQuote] = []
    quoted_prices: dict[str, float] = {}

    for asin in target_asins:
        quote = provider.fetch_price(asin)
        quotes.append(quote)
        if quote.price is not None and quote.price > 0:
            quoted_prices[asin] = quote.price

    competitors = [
        competitor.model_copy(update={"price": quoted_prices[competitor.asin]})
        if competitor.asin in quoted_prices
        else competitor
        for competitor in req.competitors
    ]
    update: dict[str, Any] = {"competitors": competitors}
    known_prices = sorted(c.price for c in competitors if c.price is not None)
    if req.target_price is None and known_prices:
        update["target_price"] = _median(known_prices)
    if unit_cost is not None and req.cost_model is None:
        update["cost_model"] = CostModel(unit_cost=unit_cost)
    return req.model_copy(update=update), quotes


def deep_dive_with_prices(
    keyword: str,
    provider: PriceProvider,
    *,
    top_n: int = 3,
    unit_cost: float | None = None,
    meta_path: Path = DEFAULT_META,
    review_path: Path = DEFAULT_REVIEWS,
) -> dict[str, Any]:
    req = build_product_research_request(
        meta_path=meta_path,
        review_path=review_path,
        keyword=keyword,
        max_competitors=20,
        max_reviews=20000,
    )
    before = research_product(req)
    req2, quotes = inject_real_prices(req, provider, top_n=top_n, unit_cost=unit_cost)
    after = research_product(req2)
    return {
        "keyword": keyword,
        "price_quotes": [quote.model_dump(mode="json") for quote in quotes],
        "coverage_before": round(_price_coverage(req), 3),
        "coverage_after": round(_price_coverage(req2), 3),
        "target_price_before": req.target_price,
        "target_price_after": req2.target_price,
        "unit_cost_used": unit_cost,
        "before": {
            "decision": before.decision,
            "confidence": before.confidence,
            "profitability": before.score_breakdown["profitability"],
            "human_review_required": before.human_review_required,
        },
        "after": {
            "decision": after.decision,
            "confidence": after.confidence,
            "profitability": after.score_breakdown["profitability"],
            "human_review_required": after.human_review_required,
        },
    }


def _default_provider() -> PriceProvider:
    provider = ManualPriceProvider(DEFAULT_MANUAL_PRICES)
    return provider if provider._prices else StubPriceProvider()


def _median(values: list[float]) -> float:
    if not values:
        raise ValueError("median requires at least one value")
    return values[len(values) // 2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inject provider-backed prices into a niche deep-dive.")
    parser.add_argument("keyword", nargs="?", default="neck massager")
    parser.add_argument("--unit-cost", type=float, default=None)
    parser.add_argument("--top-n", type=int, default=3)
    args = parser.parse_args()
    report = deep_dive_with_prices(
        args.keyword,
        _default_provider(),
        top_n=args.top_n,
        unit_cost=args.unit_cost,
    )
    before = report["before"]
    after = report["after"]
    print(
        f"before: coverage={report['coverage_before']:.3f}, decision={before['decision']}, "
        f"profitability={before['profitability']}, human={before['human_review_required']}"
    )
    print(
        f"after:  coverage={report['coverage_after']:.3f}, decision={after['decision']}, "
        f"profitability={after['profitability']}, human={after['human_review_required']}"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
