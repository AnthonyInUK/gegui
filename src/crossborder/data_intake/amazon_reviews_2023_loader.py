"""Convert public Amazon Reviews 2023-style JSONL files into research input.

This loader is intentionally local-file first. It does not scrape Amazon and it
does not download the large public dataset. Put a category's review/meta JSONL
files on disk, then run this script to produce a ProductResearchRequest payload.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossborder.schemas import (  # noqa: E402
    CompetitorSnapshot,
    CompliancePrecheck,
    CostModel,
    DataIntakeReport,
    LogisticsProfile,
    ProductBrief,
    ProductResearchRequest,
    ReviewPainPoint,
)


PAIN_POINT_KEYWORDS = {
    "adhesive": {"adhesive", "stick", "sticky", "falls off", "fall off", "peel"},
    "too bulky": {"bulky", "too large", "too big", "thick", "heavy"},
    "durability": {"broke", "broken", "crack", "cheap", "flimsy", "durable", "lasted"},
    "installation": {"install", "setup", "hard to use", "confusing", "instructions"},
    "size mismatch": {"small", "too small", "does not fit", "fit", "tight"},
    "odor": {"smell", "odor", "chemical"},
    "noise": {"loud", "noisy", "noise"},
    "battery": {"battery", "charge", "charging"},
}

COMPLIANCE_TERMS = {
    "medical_claim_risk": {"pain relief", "chronic pain", "treat", "therapy", "arthritis"},
    "pesticide_claim_risk": {"antibacterial", "kills germs", "disinfect", "pesticide"},
    "children_product_risk": {"baby", "infant", "toddler", "kids", "children"},
}


def build_product_research_request(
    *,
    meta_path: Path,
    review_path: Path | None = None,
    keyword: str,
    category: str = "",
    target_price: float | None = None,
    unit_cost: float | None = None,
    max_competitors: int = 10,
    max_reviews: int = 5000,
    workflow_id: str = "",
    seller_id: str = "",
) -> ProductResearchRequest:
    metas = list(_iter_jsonl(meta_path))
    matched = _match_metadata(metas, keyword=keyword, category=category)[:max_competitors]
    if not matched:
        raise ValueError(f"No metadata rows matched keyword={keyword!r} category={category!r}")

    parent_asins = {_parent_asin(row) for row in matched if _parent_asin(row)}
    reviews = list(_iter_reviews(review_path, parent_asins=parent_asins, max_reviews=max_reviews))
    grouped_reviews = _group_reviews(reviews)

    competitors = [_to_competitor(row, grouped_reviews.get(_parent_asin(row), [])) for row in matched]
    pain_points = _extract_pain_points(grouped_reviews)
    product_row = matched[0]
    product = _to_product_brief(product_row, keyword)
    # Only impute a target price from the competitor median when enough of the
    # pool is actually priced. Below 25% coverage a median off 1-2 prices is
    # noise, so we leave target_price unset and let profitability degrade
    # honestly. A seller-supplied target_price always wins.
    priced_share = (
        sum(1 for c in competitors if c.price is not None) / len(competitors)
        if competitors
        else 0.0
    )
    if target_price is not None:
        inferred_target_price = target_price
    elif priced_share >= 0.25:
        inferred_target_price = _median_price(competitors)
    else:
        inferred_target_price = None
    cost_model = _cost_model(unit_cost=unit_cost, target_price=inferred_target_price)
    logistics = _logistics_from_metadata(product_row)
    compliance_precheck = _compliance_precheck(product, product_row)
    report = _build_report(
        metas=metas,
        reviews=reviews,
        matched=matched,
        competitors=competitors,
        pain_points=pain_points,
        cost_model=cost_model,
        logistics=logistics,
        compliance_precheck=compliance_precheck,
        target_price=target_price,
        unit_cost=unit_cost,
        inferred_target_price=inferred_target_price,
    )

    return ProductResearchRequest(
        platform="amazon",
        market="US",
        workflow_id=workflow_id or f"wf_public_amazon_{_slug(keyword)}",
        seller_id=seller_id,
        product=product,
        target_price=inferred_target_price,
        monthly_search_volume=None,
        competitors=competitors,
        pain_points=pain_points,
        cost_model=cost_model,
        logistics=logistics,
        compliance_precheck=compliance_precheck,
        data_intake_report=report,
        metadata={
            "source": "amazon_reviews_2023_public_jsonl",
            "keyword": keyword,
            "category": category,
            "meta_path": str(meta_path),
            "review_path": str(review_path) if review_path else "",
            "matched_items": len(matched),
            "matched_reviews": len(reviews),
        },
    )


def run_loader_and_optionally_research(
    *,
    meta_path: Path,
    review_path: Path | None = None,
    keyword: str,
    category: str = "",
    target_price: float | None = None,
    unit_cost: float | None = None,
    max_competitors: int = 10,
    max_reviews: int = 5000,
    workflow_id: str = "",
    seller_id: str = "",
    run_research: bool = False,
) -> dict[str, Any]:
    request = build_product_research_request(
        meta_path=meta_path,
        review_path=review_path,
        keyword=keyword,
        category=category,
        target_price=target_price,
        unit_cost=unit_cost,
        max_competitors=max_competitors,
        max_reviews=max_reviews,
        workflow_id=workflow_id,
        seller_id=seller_id,
    )
    payload: dict[str, Any] = {"request": request.model_dump(mode="json")}
    if run_research:
        from crossborder.product_research import research_product

        payload["research_result"] = research_product(request).model_dump(mode="json")
    return payload


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _iter_reviews(
    path: Path | None,
    *,
    parent_asins: set[str],
    max_reviews: int,
) -> Iterable[dict[str, Any]]:
    if path is None:
        return []
    rows = []
    for row in _iter_jsonl(path):
        asin = str(row.get("parent_asin") or row.get("asin") or "")
        if asin in parent_asins:
            rows.append(row)
            if len(rows) >= max_reviews:
                break
    return rows


def _match_metadata(rows: list[dict[str, Any]], *, keyword: str, category: str) -> list[dict[str, Any]]:
    keyword_terms = _terms(keyword)
    category_terms = _terms(category)

    def score(row: dict[str, Any]) -> tuple[int, int]:
        haystack = _row_text(row)
        keyword_score = sum(1 for term in keyword_terms if term in haystack)
        category_score = sum(1 for term in category_terms if term in haystack)
        rating_count = _int(row.get("rating_number") or row.get("review_count") or 0)
        return (keyword_score * 10 + category_score * 3, rating_count)

    matched = [row for row in rows if score(row)[0] > 0]
    return sorted(matched, key=score, reverse=True)


def _to_competitor(row: dict[str, Any], reviews: list[dict[str, Any]]) -> CompetitorSnapshot:
    rating = _float(row.get("average_rating") or row.get("rating"))
    review_count = _int(row.get("rating_number") or row.get("review_count") or len(reviews) or None)
    return CompetitorSnapshot(
        asin=_parent_asin(row),
        title=str(row.get("title") or ""),
        brand=str(row.get("brand") or row.get("store") or ""),
        price=_price(row.get("price")),
        rating=rating,
        review_count=review_count,
        estimated_monthly_sales=_estimate_monthly_sales(review_count, rating),
        bsr=_best_sales_rank(row),
        prime=None,
        listing_quality_score=_listing_quality(row),
        weaknesses=_weaknesses_from_reviews(reviews),
    )


def _to_product_brief(row: dict[str, Any], keyword: str) -> ProductBrief:
    categories = _flatten(row.get("categories") or row.get("category") or [])
    features = _flatten(row.get("features") or [])
    description = _flatten(row.get("description") or [])
    details = row.get("details") if isinstance(row.get("details"), dict) else {}

    # categories breadcrumb is ~empty in the 2023 dataset. Fall back to the
    # always-present main_category, then to the search keyword (the niche).
    category = (
        (categories[-1] if categories else "")
        or str(row.get("main_category") or "")
        or keyword
    )
    # details holds structured attributes the top-level fields lack. Pull Brand
    # and Material/Item Form so ProductBrief is richer than title-only.
    brand = (
        str(row.get("brand") or "")
        or str(details.get("Brand") or "")
        or str(details.get("Manufacturer") or "")
        or str(row.get("store") or "")
    )
    materials = _details_materials(details)
    return ProductBrief(
        title=str(row.get("title") or keyword),
        category=category,
        brand=brand,
        features=features[:5],
        claims=description[:3],
        materials=materials,
        image_urls=_image_urls(row),
        attributes={
            "source_parent_asin": _parent_asin(row),
            "source_categories": categories,
            "main_category": str(row.get("main_category") or ""),
            "item_form": str(details.get("Item Form") or ""),
            "age_range": str(details.get("Age Range (Description)") or ""),
            "color": str(details.get("Color") or ""),
            "average_rating": _float(row.get("average_rating")),
            "rating_number": _int(row.get("rating_number")),
        },
    )


def _details_materials(details: dict[str, Any]) -> list[str]:
    """Extract material/form attributes from the meta details block."""
    out: list[str] = []
    for key in ("Material", "Item Form", "Fabric Type"):
        value = details.get(key)
        if value and str(value).strip():
            out.append(str(value).strip())
    return out[:3]


def _extract_pain_points(grouped_reviews: dict[str, list[dict[str, Any]]]) -> list[ReviewPainPoint]:
    counter: Counter[str] = Counter()
    examples: dict[str, str] = {}
    source_asins: dict[str, set[str]] = defaultdict(set)
    severity_sum: Counter[str] = Counter()

    for parent_asin, reviews in grouped_reviews.items():
        for review in reviews:
            rating = _float(review.get("rating")) or 5.0
            text = f"{review.get('title', '')} {review.get('text', '')}".lower()
            if rating > 3:
                continue
            for topic, keywords in PAIN_POINT_KEYWORDS.items():
                if any(keyword in text for keyword in keywords):
                    counter[topic] += 1
                    severity_sum[topic] += max(1, round(6 - rating))
                    examples.setdefault(topic, str(review.get("text") or review.get("title") or ""))
                    source_asins[topic].add(parent_asin)

    points = []
    for topic, frequency in counter.most_common(8):
        severity = round(severity_sum[topic] / frequency)
        points.append(
            ReviewPainPoint(
                topic=topic,
                frequency=frequency,
                severity=max(1, min(5, severity)),
                example=examples.get(topic, "")[:240],
                source_asins=sorted(source_asins[topic]),
            )
        )
    return points


def _group_reviews(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        parent_asin = str(row.get("parent_asin") or row.get("asin") or "")
        if parent_asin:
            grouped[parent_asin].append(row)
    return grouped


def _weaknesses_from_reviews(reviews: list[dict[str, Any]]) -> list[str]:
    grouped = _group_reviews(reviews)
    points = _extract_pain_points(grouped)
    return [point.topic for point in points[:3]]


def _cost_model(unit_cost: float | None, target_price: float | None) -> CostModel | None:
    if unit_cost is None and target_price is None:
        return None
    price = target_price or 0
    return CostModel(
        unit_cost=unit_cost,
        inbound_shipping=round((unit_cost or 0) * 0.12, 2) if unit_cost else None,
        referral_fee=round(price * 0.15, 2) if price else None,
        fulfillment_fee=None,
        ads_cpa_estimate=round(price * 0.12, 2) if price else None,
        return_cost_allowance=round(price * 0.03, 2) if price else None,
    )


def _build_report(
    *,
    metas: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    matched: list[dict[str, Any]],
    competitors: list[CompetitorSnapshot],
    pain_points: list[ReviewPainPoint],
    cost_model: CostModel | None,
    logistics: LogisticsProfile,
    compliance_precheck: CompliancePrecheck,
    target_price: float | None,
    unit_cost: float | None,
    inferred_target_price: float | None,
) -> DataIntakeReport:
    missing_fields = {
        "price": sum(1 for row in matched if _price(row.get("price")) is None),
        "average_rating": sum(1 for row in matched if _float(row.get("average_rating") or row.get("rating")) is None),
        "review_count": sum(1 for row in matched if _int(row.get("rating_number") or row.get("review_count")) is None),
        "images": sum(1 for row in matched if not _image_urls(row)),
        "features": sum(1 for row in matched if not _flatten(row.get("features") or [])),
        "weight": 1 if logistics.weight_kg is None else 0,
        "unit_cost": 1 if unit_cost is None else 0,
    }
    inferred_fields = []
    if target_price is None and inferred_target_price is not None:
        inferred_fields.append("target_price_from_competitor_median")
    if cost_model:
        if cost_model.inbound_shipping is not None:
            inferred_fields.append("inbound_shipping_from_unit_cost")
        if cost_model.referral_fee is not None:
            inferred_fields.append("referral_fee_from_target_price")
        if cost_model.ads_cpa_estimate is not None:
            inferred_fields.append("ads_cpa_estimate_from_target_price")
        if cost_model.return_cost_allowance is not None:
            inferred_fields.append("return_cost_allowance_from_target_price")
    if any(c.estimated_monthly_sales is not None for c in competitors):
        inferred_fields.append("estimated_monthly_sales_from_review_count")

    priced = sum(1 for c in competitors if c.price is not None)
    price_coverage = round(priced / len(competitors), 3) if competitors else 0.0

    warnings = []
    if not reviews:
        warnings.append("No matching reviews were loaded; pain_points will be empty.")
    if unit_cost is None:
        warnings.append("unit_cost missing; cost_model is incomplete.")
    if logistics.weight_kg is None:
        warnings.append("Could not infer product weight from metadata details.")
    if compliance_precheck.certificate_required:
        warnings.append("Compliance precheck suggests certificates or manual review may be required.")
    if price_coverage < 0.25:
        warnings.append(
            f"Only {price_coverage * 100:.0f}% of the competitor pool has a price; "
            "profitability will degrade and route to human review unless a target_price is supplied."
        )

    return DataIntakeReport(
        source="amazon_reviews_2023_public_jsonl",
        raw_meta_rows=len(metas),
        raw_review_rows=len(reviews),
        matched_items=len(matched),
        matched_reviews=len(reviews),
        generated_competitors=len(competitors),
        generated_pain_points=len(pain_points),
        price_coverage=price_coverage,
        missing_fields=missing_fields,
        inferred_fields=sorted(set(inferred_fields)),
        warnings=warnings,
    )


def _logistics_from_metadata(row: dict[str, Any]) -> LogisticsProfile:
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    weight_text = " ".join(str(details.get(key, "")) for key in ("Item Weight", "Product Dimensions"))
    return LogisticsProfile(
        weight_kg=_parse_weight_kg(weight_text),
        battery=_contains_any(_row_text(row), {"battery", "batteries", "lithium"}),
        liquid=_contains_any(_row_text(row), {"liquid", "fluid", "spray"}),
        fragile=_contains_any(_row_text(row), {"glass", "ceramic", "fragile"}),
    )


def _compliance_precheck(product: ProductBrief, row: dict[str, Any]) -> CompliancePrecheck:
    text = f"{product.title} {product.category} {' '.join(product.features)} {' '.join(product.claims)}".lower()
    flags = {
        key: any(term in text for term in terms)
        for key, terms in COMPLIANCE_TERMS.items()
    }
    restricted_category = _contains_any(text, {"supplement", "medical", "drug", "weapon"})
    certificate_required = flags["medical_claim_risk"] or flags["children_product_risk"]
    return CompliancePrecheck(
        restricted_category=restricted_category,
        certificate_required=certificate_required,
        **flags,
    )


def _image_urls(row: dict[str, Any]) -> list[str]:
    images = row.get("images")
    if isinstance(images, list):
        urls = []
        for item in images:
            if isinstance(item, dict):
                url = item.get("large") or item.get("large_image_url") or item.get("hi_res") or item.get("thumb")
                if url:
                    urls.append(str(url))
        return urls[:6]
    return []


def _best_sales_rank(row: dict[str, Any]) -> int | None:
    rank = row.get("rank")
    if isinstance(rank, int):
        return rank
    if isinstance(rank, list):
        numbers = []
        for item in rank:
            match = re.search(r"#([0-9,]+)", str(item))
            if match:
                numbers.append(int(match.group(1).replace(",", "")))
        return min(numbers) if numbers else None
    return None


def _listing_quality(row: dict[str, Any]) -> int:
    score = 40
    if row.get("title"):
        score += 15
    if _flatten(row.get("features") or []):
        score += 15
    if _flatten(row.get("description") or []):
        score += 10
    if _image_urls(row):
        score += 10
    if _price(row.get("price")):
        score += 10
    return min(score, 100)


def _estimate_monthly_sales(review_count: int | None, rating: float | None) -> int | None:
    if review_count is None:
        return None
    # Public datasets do not include live sales. This rough proxy is only for
    # offline test ranking and should be replaced by real sales estimates later.
    multiplier = 2.2 if rating and rating >= 4.2 else 1.5
    return max(1, round(review_count * multiplier))


def _median_price(competitors: list[CompetitorSnapshot]) -> float | None:
    prices = sorted(c.price for c in competitors if c.price is not None)
    if not prices:
        return None
    return prices[len(prices) // 2]


def _parent_asin(row: dict[str, Any]) -> str:
    return str(row.get("parent_asin") or row.get("asin") or "")


def _row_text(row: dict[str, Any]) -> str:
    parts = [
        row.get("title", ""),
        row.get("brand", ""),
        row.get("store", ""),
        " ".join(_flatten(row.get("categories") or [])),
        " ".join(_flatten(row.get("features") or [])),
        " ".join(_flatten(row.get("description") or [])),
    ]
    return " ".join(str(part).lower() for part in parts if part)


def _terms(text: str) -> list[str]:
    return [term for term in re.split(r"[^a-z0-9]+", text.lower()) if len(term) >= 2]


def _flatten(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_flatten(item))
        return [item for item in result if item]
    return [str(value)]


def _price(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(value).replace(",", ""))
    return float(match.group(1)) if match else None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def _parse_weight_kg(text: str) -> float | None:
    lowered = text.lower()
    kg = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*kg", lowered)
    if kg:
        return float(kg.group(1))
    pounds = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:pounds|pound|lbs|lb)", lowered)
    if pounds:
        return round(float(pounds.group(1)) * 0.453592, 3)
    ounces = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(?:ounces|ounce|oz)", lowered)
    if ounces:
        return round(float(ounces.group(1)) * 0.0283495, 3)
    return None


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(term in text for term in terms)


def _slug(text: str) -> str:
    return "_".join(_terms(text))[:48] or "sample"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ProductResearchRequest from Amazon Reviews 2023-style JSONL.")
    parser.add_argument("--meta", required=True, type=Path, help="Path to meta_*.jsonl")
    parser.add_argument("--reviews", type=Path, help="Path to review *.jsonl")
    parser.add_argument("--keyword", required=True)
    parser.add_argument("--category", default="")
    parser.add_argument("--target-price", type=float)
    parser.add_argument("--unit-cost", type=float)
    parser.add_argument("--max-competitors", type=int, default=10)
    parser.add_argument("--max-reviews", type=int, default=5000)
    parser.add_argument("--workflow-id", default="")
    parser.add_argument("--seller-id", default="")
    parser.add_argument("--run-research", action="store_true", help="Also run product research v2 and include the result.")
    parser.add_argument("--output", type=Path, help="Write JSON output to this file instead of stdout.")
    args = parser.parse_args()

    if args.run_research:
        payload = run_loader_and_optionally_research(
            meta_path=args.meta,
            review_path=args.reviews,
            keyword=args.keyword,
            category=args.category,
            target_price=args.target_price,
            unit_cost=args.unit_cost,
            max_competitors=args.max_competitors,
            max_reviews=args.max_reviews,
            workflow_id=args.workflow_id,
            seller_id=args.seller_id,
            run_research=True,
        )
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        result = build_product_research_request(
            meta_path=args.meta,
            review_path=args.reviews,
            keyword=args.keyword,
            category=args.category,
            target_price=args.target_price,
            unit_cost=args.unit_cost,
            max_competitors=args.max_competitors,
            max_reviews=args.max_reviews,
            workflow_id=args.workflow_id,
            seller_id=args.seller_id,
        )
        text = result.model_dump_json(indent=2)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
        print(str(args.output))
    else:
        print(text)


if __name__ == "__main__":
    main()
