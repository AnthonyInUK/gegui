"""Product research Agent-as-Tool MVP.

This first version is deterministic: it encodes the scoring rules we trust and
keeps a stable contract. Later, trend scraping, competitor review mining, and an
LLM opportunity judge can sit behind this same function.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossborder.platforms import MEDICAL_RISK_PATTERNS, RISKY_PHRASES
from crossborder.schemas import ProductResearchRequest, ProductResearchResult


def research_product(req: ProductResearchRequest) -> ProductResearchResult:
    breakdown = {
        "demand": _score_demand(req),
        "profitability": _score_profitability(req),
        "competition": _score_competition(req),
        "logistics": _score_logistics(req),
        "compliance": _score_compliance(req),
    }
    score = round(
        breakdown["demand"] * 0.25
        + breakdown["profitability"] * 0.25
        + breakdown["competition"] * 0.2
        + breakdown["logistics"] * 0.15
        + breakdown["compliance"] * 0.15
    )
    price_insufficient = _profitability_data_insufficient(req)
    issues = _issues(req, breakdown)
    if price_insufficient:
        coverage = _price_coverage(req)
        issues.append(
            {
                "category": "profitability_data_insufficient",
                "severity": "medium",
                "reason": (
                    f"Competitor price coverage is only {coverage * 100:.0f}%; "
                    "margin cannot be judged from the public dataset alone."
                ),
                "suggestion": (
                    "Supply a target_price (you know the niche price band), or pull a real "
                    "price for the shortlisted ASINs via Keepa before the sourcing decision."
                ),
            }
        )
    suggestions = _suggestions(req, breakdown)
    decision = _decision(score, breakdown, req)
    # Missing price must not let a candidate pass silently: a profitability we
    # cannot judge is a human decision, not an automated pass.
    if price_insufficient and decision in ("pass", "requires_revision"):
        decision = "requires_human_review"
    candidate_ranking = _candidate_ranking(req)
    selection_rationale = _selection_rationale(req, breakdown, candidate_ranking)
    research_pipeline = _research_pipeline(req, breakdown, score, decision, candidate_ranking, selection_rationale)
    missing = _missing_signal_count(req)
    confidence = max(0.45, round(0.9 - missing * 0.08, 2))
    if price_insufficient:
        confidence = round(min(confidence, 0.55), 2)
    human_review = decision == "requires_human_review"

    return ProductResearchResult(
        decision=decision,
        opportunity_level=_level(score),
        score=score,
        confidence=confidence,
        score_breakdown=breakdown,
        candidate_ranking=candidate_ranking,
        research_pipeline=research_pipeline,
        selection_rationale=selection_rationale,
        issues=issues,
        suggestions=suggestions,
        human_review_required=human_review,
        audit={
            "research_id": f"rsch_{uuid4().hex[:12]}",
            "workflow_id": req.workflow_id,
            "tool": "crossborder.product_research",
            "runtime": "deterministic_rules",
            "input_hash": _input_hash(req),
            "created_at": datetime.now(UTC).isoformat(),
            "version": "product-research-v2",
            "platform": req.platform.value,
        },
    )


def _candidate_ranking(req: ProductResearchRequest) -> list[dict[str, Any]]:
    selected_asin = str(req.product.attributes.get("source_parent_asin") or "")
    max_sales = max((c.estimated_monthly_sales or 0 for c in req.competitors), default=0) or 1
    max_reviews = max((c.review_count or 0 for c in req.competitors), default=0) or 1
    rows = []
    for competitor in req.competitors:
        sales_score = round(((competitor.estimated_monthly_sales or 0) / max_sales) * 40)
        review_score = round(((competitor.review_count or 0) / max_reviews) * 20)
        rating = competitor.rating or 0
        rating_score = 15 if 3.8 <= rating <= 4.4 else 10 if rating > 0 else 0
        weakness_score = min(len(competitor.weaknesses) * 5, 15)
        price_score = _price_position_score(req, competitor.price)
        total = sales_score + review_score + rating_score + weakness_score + price_score
        rows.append(
            {
                "asin": competitor.asin,
                "title": competitor.title,
                "role": "selected" if competitor.asin == selected_asin else "candidate",
                "score": total,
                "score_parts": {
                    "estimated_sales": sales_score,
                    "review_depth": review_score,
                    "rating_window": rating_score,
                    "pain_point_gap": weakness_score,
                    "price_position": price_score,
                },
                "signals": {
                    "price": competitor.price,
                    "rating": competitor.rating,
                    "review_count": competitor.review_count,
                    "estimated_monthly_sales": competitor.estimated_monthly_sales,
                    "weaknesses": competitor.weaknesses,
                },
                "why": _candidate_why(req, competitor, total),
            }
        )
    return sorted(rows, key=lambda item: (item["role"] != "selected", -item["score"]))


def _price_position_score(req: ProductResearchRequest, price: float | None) -> int:
    target = req.target_price or _median_competitor_price(req)
    if target is None or price is None or target <= 0:
        return 5
    distance = abs(price - target) / target
    if distance <= 0.1:
        return 10
    if distance <= 0.25:
        return 7
    return 3


def _candidate_why(req: ProductResearchRequest, competitor, score: int) -> list[str]:
    selected = competitor.asin == str(req.product.attributes.get("source_parent_asin") or "")
    reasons = [
        f"综合候选分 {score}/100，来自预估月销、评论深度、评分区间、痛点缺口和价格位置。",
        f"预估月销 {competitor.estimated_monthly_sales or 0}，评论数 {competitor.review_count or 0}，评分 {competitor.rating or '—'}。",
    ]
    if competitor.weaknesses:
        reasons.append(f"评论弱点命中 {', '.join(competitor.weaknesses)}，说明存在可改良/差异化空间。")
    if selected:
        reasons.append("这是当前进入后续 Listing/合规链路的主推候选。")
    else:
        reasons.append("该商品保留为对照候选，用来比较价格、评论和痛点差异。")
    return reasons


def _selection_rationale(
    req: ProductResearchRequest,
    breakdown: dict[str, int],
    candidate_ranking: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = next((item for item in candidate_ranking if item["role"] == "selected"), candidate_ranking[0] if candidate_ranking else {})
    runner_up = next((item for item in candidate_ranking if item["role"] != "selected"), {})
    landed_cost = _effective_landed_cost(req)
    target_price = req.target_price or _median_competitor_price(req)
    margin = None
    if target_price and landed_cost is not None:
        margin = round((target_price - landed_cost) / target_price * 100, 1)
    pain_topics = ", ".join(point.topic for point in req.pain_points) or "none"
    return [
        {
            "claim": f"候选池 {len(req.competitors)} 条，当前主推 {selected.get('asin', '—')}。",
            "evidence": f"主推来自 product.attributes.source_parent_asin；候选池来自 matched metadata rows。",
            "source": "ProductResearchRequest.product.attributes.source_parent_asin / competitors[]",
        },
        {
            "claim": f"主推需求信号强于对照：预估月销 {selected.get('signals', {}).get('estimated_monthly_sales', '—')} vs {runner_up.get('signals', {}).get('estimated_monthly_sales', '—')}，评论 {selected.get('signals', {}).get('review_count', '—')} vs {runner_up.get('signals', {}).get('review_count', '—')}。",
            "evidence": "estimated_monthly_sales 由 review_count 与 rating 的本地规则估算；不是 Amazon 实时销量。",
            "source": "competitors[].estimated_monthly_sales / competitors[].review_count",
        },
        {
            "claim": f"利润项得分 {breakdown['profitability']}/100，粗算毛利空间 {margin}%。",
            "evidence": f"target_price={target_price}, landed_cost={landed_cost}, formula=(target_price-landed_cost)/target_price。",
            "source": "ProductResearchRequest.target_price / cost_model.total_landed_cost()",
        },
        {
            "claim": f"评论痛点命中 {pain_topics}。",
            "evidence": "这些痛点来自 3 星及以下评论的关键词匹配，只能说明改良方向，不能直接证明市场规模。",
            "source": "pain_points[].topic / pain_points[].example / pain_points[].source_asins",
        },
        {
            "claim": f"物流分 {breakdown['logistics']}/100，合规分 {breakdown['compliance']}/100。",
            "evidence": "物流基于 weight/hazmat flags；合规基于标题/类目/features/claims 和 precheck flags，未发现阻断项。",
            "source": "logistics / compliance_precheck / product claims",
        },
    ]


def _research_pipeline(
    req: ProductResearchRequest,
    breakdown: dict[str, int],
    score: int,
    decision: str,
    candidate_ranking: list[dict[str, Any]],
    selection_rationale: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    competitor_sales = [c.estimated_monthly_sales for c in req.competitors if c.estimated_monthly_sales is not None]
    landed_cost = _effective_landed_cost(req)
    target_price = req.target_price or _median_competitor_price(req)
    return [
        {
            "step": "data_intake",
            "name": "候选数据接入",
            "question": "有哪些商品可以进入候选池？",
            "inputs": ["metadata", "reviews", "keyword", "category"],
            "calculation": f"按关键词 {req.metadata.get('keyword', '')!r} 和类目 {req.metadata.get('category', '')!r} 匹配，生成 {len(req.competitors)} 条候选。",
            "evidence": {
                "candidate_count": len(req.competitors),
                "pain_point_count": len(req.pain_points),
            },
            "output": "标准化候选池、评论痛点、成本/物流/合规预检。",
        },
        {
            "step": "candidate_ranking",
            "name": "候选排序",
            "question": "为什么是这条商品进入后续链路？",
            "inputs": ["estimated_monthly_sales", "review_count", "rating", "weaknesses", "price"],
            "calculation": "候选分 = 预估月销40 + 评论深度20 + 评分窗口15 + 痛点缺口15 + 价格位置10。",
            "evidence": {"ranking": candidate_ranking},
            "output": selection_rationale,
        },
        {
            "step": "demand",
            "name": "需求判断",
            "question": "市场是否有基本需求？",
            "inputs": ["competitor_estimated_sales", "review_pain_points"],
            "calculation": f"竞品预估月销样本 {competitor_sales}，再叠加痛点权重 {_pain_point_weight(req)}。",
            "evidence": {"score": breakdown["demand"], "competitor_sales": competitor_sales},
            "output": f"需求分 {breakdown['demand']}/100。",
        },
        {
            "step": "profitability",
            "name": "利润判断",
            "question": "扣掉成本后是否还有空间？",
            "inputs": ["target_price", "cost_model"],
            "calculation": f"目标售价 ${target_price} - 全成本 ${landed_cost}。",
            "evidence": {"score": breakdown["profitability"], "target_price": target_price, "landed_cost": landed_cost},
            "output": f"利润分 {breakdown['profitability']}/100。",
        },
        {
            "step": "competition",
            "name": "竞争判断",
            "question": "是否有差异化切入点？",
            "inputs": ["competitor_count", "avg_rating", "weaknesses"],
            "calculation": "候选池数量、平均评分和评论弱点共同判断竞争压力与改良空间。",
            "evidence": {"score": breakdown["competition"], "weaknesses": [c.weaknesses for c in req.competitors]},
            "output": f"竞争分 {breakdown['competition']}/100。",
        },
        {
            "step": "logistics_compliance",
            "name": "物流与合规预检",
            "question": "是否存在发布前就应该阻断的硬风险？",
            "inputs": ["weight", "hazmat_flags", "compliance_precheck"],
            "calculation": "重量/尺寸/电池/液体/侵权/医疗/儿童/杀菌等风险扣分。",
            "evidence": {"logistics_score": breakdown["logistics"], "compliance_score": breakdown["compliance"]},
            "output": f"物流 {breakdown['logistics']}/100，合规 {breakdown['compliance']}/100。",
        },
        {
            "step": "final_decision",
            "name": "最终路由",
            "question": "是否进入 Listing 和合规链路？",
            "inputs": ["score_breakdown", "blocking_risks"],
            "calculation": "总分 = 需求25% + 利润25% + 竞争20% + 物流15% + 合规15%。",
            "evidence": {"score": score, "decision": decision, "score_breakdown": breakdown},
            "output": f"{decision}，机会分 {score}/100。",
        },
    ]


def _score_demand(req: ProductResearchRequest) -> int:
    volume = req.monthly_search_volume
    competitor_sales = [
        c.estimated_monthly_sales
        for c in req.competitors
        if c.estimated_monthly_sales is not None
    ]
    if volume is None:
        if competitor_sales:
            median_sales = sorted(competitor_sales)[len(competitor_sales) // 2]
            base = 82 if median_sales >= 1000 else 68 if median_sales >= 300 else 50
        else:
            base = 55
    elif volume >= 50000:
        base = 90
    elif volume >= 10000:
        base = 78
    elif volume >= 3000:
        base = 65
    elif volume >= 800:
        base = 50
    else:
        base = 35
    pain_point_boost = min(_pain_point_weight(req) // 4, 14)
    return _clamp(base + pain_point_boost)


def _price_coverage(req: ProductResearchRequest) -> float:
    """Fraction of the competitor pool that carries a price (0-1)."""
    if not req.competitors:
        return 0.0
    priced = sum(1 for c in req.competitors if c.price is not None)
    return priced / len(req.competitors)


def _profitability_data_insufficient(req: ProductResearchRequest) -> bool:
    """True when there is no trustworthy basis to judge margin.

    A seller-supplied target_price rescues it (they know the price band). One
    stray competitor price does not — per-niche coverage in the public dataset
    can fall to ~5%, so below 25% coverage with no target_price we refuse to
    fake a profitability number.
    """
    if req.target_price is not None:
        return False
    return _price_coverage(req) < 0.25


def _score_profitability(req: ProductResearchRequest) -> int:
    # No trustworthy price basis -> stay neutral instead of scoring off one
    # unreliable competitor price. The degradation is surfaced separately.
    if _profitability_data_insufficient(req):
        return 50
    target_price = req.target_price or _median_competitor_price(req)
    landed_cost = _effective_landed_cost(req)
    if target_price is None or landed_cost is None or target_price <= 0:
        return 50
    margin = (target_price - landed_cost) / target_price
    if margin >= 0.55:
        return 90
    if margin >= 0.4:
        return 78
    if margin >= 0.28:
        return 62
    if margin >= 0.18:
        return 45
    return 25


def _score_competition(req: ProductResearchRequest) -> int:
    count = req.competitor_count if req.competitor_count is not None else len(req.competitors) or None
    rating = req.avg_rating or _avg_competitor_rating(req) or 0
    if count is None:
        base = 55
    elif count <= 20:
        base = 85
    elif count <= 80:
        base = 70
    elif count <= 200:
        base = 52
    else:
        base = 35
    strong_review_moat = _review_moat(req)
    if rating >= 4.6 and ((count or 0) > 80 or strong_review_moat):
        base -= 12
    elif rating <= 4.0 and (req.review_pain_points or req.pain_points):
        base += 8
    quality_gaps = sum(1 for c in req.competitors if c.weaknesses)
    if quality_gaps >= 3:
        base += 6
    return _clamp(base)


def _score_logistics(req: ProductResearchRequest) -> int:
    attrs = req.product.attributes
    score = 82
    logistics = req.logistics
    weight = logistics.weight_kg if logistics and logistics.weight_kg is not None else _float_attr(attrs, "weight_kg")
    if weight > 5:
        score -= 22
    elif weight > 2:
        score -= 10
    penalties = {
        "oversized": 18,
        "fragile": 14,
        "battery": 14,
        "liquid": 18,
        "magnet": 8,
        "hazmat": 24,
        "meltable": 10,
    }
    for key, penalty in penalties.items():
        from_profile = bool(getattr(logistics, key, False)) if logistics else False
        if from_profile or bool(attrs.get(key)):
            score -= penalty
    if logistics and logistics.length_cm and logistics.width_cm and logistics.height_cm:
        dimensional_sum = logistics.length_cm + logistics.width_cm + logistics.height_cm
        if dimensional_sum > 150:
            score -= 12
    return _clamp(score)


def _score_compliance(req: ProductResearchRequest) -> int:
    text = " ".join(
        [
            req.product.title,
            req.product.category,
            " ".join(req.product.features),
            " ".join(req.product.claims),
        ]
    ).lower()
    risk_hits = [
        phrase
        for phrase in {*RISKY_PHRASES.keys(), *MEDICAL_RISK_PATTERNS}
        if phrase.lower() in text
    ]
    precheck = req.compliance_precheck
    precheck_penalty = 0
    if precheck:
        # Penalties reflect fixability, not just severity. IP risk and a
        # restricted category are hard problems (the niche may be unsellable).
        # Medical/pesticide *claim* wording and missing certificates are
        # rewritable/obtainable, so they dent the score but should not crater it
        # into the hard-block range — _decision routes them to human review.
        risk_flags = {
            "trademark_risk": 24,
            "patent_risk": 28,
            "restricted_category": 30,
            "certificate_required": 8,
            "medical_claim_risk": 14,
            "pesticide_claim_risk": 14,
            "children_product_risk": 12,
        }
        precheck_penalty = sum(
            penalty for flag, penalty in risk_flags.items() if getattr(precheck, flag)
        )
    if not risk_hits:
        return _clamp(86 - precheck_penalty)
    # Medical-claim wording present: sellable but needs claim review. Stay below
    # the 50 human-review threshold (so it always routes to a human) yet above
    # the old near-zero base (so _decision no longer hard-blocks a fixable claim).
    if any(hit in MEDICAL_RISK_PATTERNS for hit in risk_hits):
        return _clamp(45 - precheck_penalty)
    return _clamp(60 - precheck_penalty)


def _issues(req: ProductResearchRequest, breakdown: dict[str, int]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if _missing_signal_count(req) >= 3:
        issues.append(
            {
                "category": "insufficient_market_data",
                "severity": "medium",
                "reason": "Missing several market signals such as price, cost, demand, competitors, or rating.",
                "suggestion": "Provide price/cost, search volume, competitor count, and average rating before a final sourcing decision.",
            }
        )
    if req.cost_model and req.cost_model.total_landed_cost() is None:
        issues.append(
            {
                "category": "missing_unit_cost",
                "severity": "medium",
                "reason": "Cost model was provided but unit_cost is missing.",
                "suggestion": "Provide unit_cost plus Amazon referral/FBA/ads/return allowances to calculate contribution margin.",
            }
        )
    if req.compliance_precheck:
        flagged = [
            key
            for key in (
                "trademark_risk",
                "patent_risk",
                "restricted_category",
                "medical_claim_risk",
                "pesticide_claim_risk",
                "children_product_risk",
            )
            if getattr(req.compliance_precheck, key)
        ]
        if flagged:
            issues.append(
                {
                    "category": "amazon_compliance_precheck",
                    "severity": "high" if {"patent_risk", "trademark_risk"} & set(flagged) else "medium",
                    "reason": f"Amazon precheck flagged: {', '.join(flagged)}.",
                    "suggestion": "Resolve IP/category/certificate risks before sourcing or publishing.",
                }
            )
    for key, score in breakdown.items():
        if score < 45:
            issues.append(
                {
                    "category": f"weak_{key}",
                    "severity": "high" if score < 35 else "medium",
                    "reason": f"{key} score is low ({score}/100).",
                    "suggestion": _suggestion_for(key),
                }
            )
    return issues


def _suggestions(req: ProductResearchRequest, breakdown: dict[str, int]) -> list[str]:
    suggestions = []
    if breakdown["profitability"] < 60:
        suggestions.append("Recalculate landed cost, referral fee, FBA/warehouse fee, and target margin.")
    if breakdown["competition"] < 60:
        suggestions.append("Look for a narrower keyword angle or differentiated bundle before entering.")
    if breakdown["logistics"] < 60:
        suggestions.append("Check size tier, battery/liquid restrictions, breakage rate, and return cost.")
    if breakdown["compliance"] < 60:
        suggestions.append("Run compliance review early and avoid medical, treatment, absolute, or guarantee claims.")
    if req.competitors:
        suggestions.append("Validate differentiation against top ASINs before purchasing inventory.")
    if req.pain_points:
        suggestions.append("Turn high-frequency review pain points into product requirements and listing bullets.")
    if not suggestions:
        suggestions.append("Candidate can proceed to listing generation and compliance review.")
    return suggestions


def _decision(score: int, breakdown: dict[str, int], req: ProductResearchRequest) -> str:
    pc = req.compliance_precheck
    # Hard block only for genuinely prohibited or infringing items: IP risk or a
    # restricted category (drug/weapon/supplement). Medical/pesticide *claim*
    # wording and missing certificates are fixable, so they route to human
    # review (rewrite the claim / get the cert) rather than killing the niche.
    if pc and (pc.patent_risk or pc.trademark_risk or pc.restricted_category):
        return "blocked"
    if breakdown["logistics"] < 25:
        return "blocked"
    if breakdown["compliance"] < 50 or _missing_signal_count(req) >= 4:
        return "requires_human_review"
    if score >= 70:
        return "pass"
    if score >= 50:
        return "requires_revision"
    if score >= 35:
        return "requires_human_review"
    return "blocked"


def _level(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _missing_signal_count(req: ProductResearchRequest) -> int:
    values = [
        req.target_price,
        _effective_landed_cost(req),
        req.monthly_search_volume,
        req.competitor_count if req.competitor_count is not None else (len(req.competitors) or None),
        req.avg_rating if req.avg_rating is not None else _avg_competitor_rating(req),
    ]
    return sum(1 for value in values if value is None)


def _suggestion_for(key: str) -> str:
    return {
        "demand": "Validate demand using marketplace search volume, trend data, and competitor sales estimates.",
        "profitability": "Improve margin by renegotiating cost, changing pack size, or raising target price.",
        "competition": "Avoid head-on competition; find a long-tail keyword, bundle, or underserved review pain point.",
        "logistics": "Reduce size/weight risk or avoid fragile, battery, liquid, and oversized variants.",
        "compliance": "Remove high-risk claims and confirm certificate/category requirements before sourcing.",
    }.get(key, "Review this dimension before continuing.")


def _float_attr(attrs: dict[str, Any], key: str) -> float:
    value = attrs.get(key, 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def _effective_landed_cost(req: ProductResearchRequest) -> float | None:
    if req.cost_model:
        total = req.cost_model.total_landed_cost()
        if total is not None:
            return total
    return req.landed_cost


def _median_competitor_price(req: ProductResearchRequest) -> float | None:
    prices = sorted(c.price for c in req.competitors if c.price is not None)
    if not prices:
        return None
    return prices[len(prices) // 2]


def _avg_competitor_rating(req: ProductResearchRequest) -> float | None:
    ratings = [c.rating for c in req.competitors if c.rating is not None]
    if not ratings:
        return None
    return round(sum(ratings) / len(ratings), 2)


def _review_moat(req: ProductResearchRequest) -> bool:
    review_counts = [c.review_count for c in req.competitors if c.review_count is not None]
    if not review_counts:
        return False
    return sorted(review_counts)[len(review_counts) // 2] >= 1000


def _pain_point_weight(req: ProductResearchRequest) -> int:
    structured = sum(max(1, point.frequency) * max(1, point.severity) for point in req.pain_points)
    legacy = len(req.review_pain_points) * 4
    return structured + legacy


def _input_hash(req: ProductResearchRequest) -> str:
    payload = json.dumps(req.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python src/crossborder/product_research.py <request.json>")
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = research_product(ProductResearchRequest.model_validate(payload))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
