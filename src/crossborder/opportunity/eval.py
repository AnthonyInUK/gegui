"""Evaluation utilities for the opportunity discovery engine.

The opportunity engine has no objective ground-truth ranking, so this module
measures behavior quality: noise filtering, signal coverage, signal ablation,
and honest degradation triggers.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from crossborder.opportunity.dataset_index import DEFAULT_META, DEFAULT_REVIEWS, DatasetIndex
from crossborder.opportunity.discover import DEFAULT_SNAPSHOT, _is_sellable_niche, build_default_engine, discover
from crossborder.opportunity.pipeline import deep_dive
from crossborder.opportunity.ranker import DEFAULT_WEIGHTS, OpportunityRanker
from crossborder.opportunity.signals import NicheCandidate, OpportunityScore, SignalProvenance

DEFAULT_FIXTURE = ROOT / "examples" / "crossborder" / "opportunity_eval_fixture.json"
DEFAULT_REPORT = ROOT / "docs" / "opportunity_eval_report.md"


def eval_noise_filter(labels: list[dict[str, Any]], index) -> dict[str, Any]:
    confusion = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}
    misclassified = []
    for item in labels:
        query = str(item.get("query", ""))
        expected = bool(item.get("is_niche"))
        predicted = _is_sellable_niche(query, index)
        if predicted and expected:
            confusion["tp"] += 1
        elif predicted and not expected:
            confusion["fp"] += 1
        elif not predicted and not expected:
            confusion["tn"] += 1
        else:
            confusion["fn"] += 1
        if predicted != expected:
            misclassified.append({"query": query, "expected": expected, "predicted": predicted})

    tp, fp, fn = confusion["tp"], confusion["fp"], confusion["fn"]
    precision = _safe_div(tp, tp + fp)
    recall = _safe_div(tp, tp + fn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "confusion": confusion,
        "misclassified": misclassified,
    }


def eval_signal_coverage(opportunities: list[OpportunityScore]) -> dict[str, Any]:
    max_signal_count = max((len(item.signals) for item in opportunities), default=0)
    histogram: dict[int, int] = {i: 0 for i in range(max_signal_count + 1)}
    provenance: dict[str, int] = {item.value: 0 for item in SignalProvenance}
    usable_counts = []
    for opportunity in opportunities:
        usable = 0
        for signal in opportunity.signals:
            provenance[signal.provenance.value] = provenance.get(signal.provenance.value, 0) + 1
            if signal.provenance != SignalProvenance.unavailable:
                usable += 1
        histogram[usable] = histogram.get(usable, 0) + 1
        usable_counts.append(usable)
    return {
        "full_coverage_count": histogram.get(max_signal_count, 0),
        "expected_signal_count": max_signal_count,
        "coverage_histogram": {str(k): v for k, v in sorted(histogram.items())},
        "provenance_breakdown": provenance,
        "avg_usable_signals": round(sum(usable_counts) / len(usable_counts), 2) if usable_counts else 0.0,
    }


def eval_signal_ablation(
    baseline: list[OpportunityScore],
    seed: str,
    snapshot_path: Path | None = DEFAULT_SNAPSHOT,
    providers: list[Any] | None = None,
) -> dict[str, Any]:
    baseline_top3 = [item.keyword for item in baseline[:3]]
    baseline_ranks = {item.keyword: i for i, item in enumerate(baseline, start=1)}
    candidates = [
        NicheCandidate(keyword=item.keyword, source=item.discovery_source)
        for item in baseline
    ] or [NicheCandidate(keyword=seed, source="manual")]
    if providers is None:
        ranker, _ = build_default_engine(snapshot_path)
        providers = ranker.providers

    ablations = []
    for provider in providers:
        remaining = [item for item in providers if item is not provider]
        reranked = OpportunityRanker(remaining, DEFAULT_WEIGHTS).rank(candidates)
        new_top3 = [item.keyword for item in reranked[:3]]
        new_ranks = {item.keyword: i for i, item in enumerate(reranked, start=1)}
        displacement = sum(
            abs(new_ranks[key] - baseline_ranks[key])
            for key in set(new_ranks) & set(baseline_ranks)
        )
        ablations.append(
            {
                "removed_signal": provider.kind.value,
                "provider": provider.name,
                "new_top3": new_top3,
                "top1_changed": bool(baseline_top3 and new_top3 and baseline_top3[0] != new_top3[0]),
                "displacement": displacement,
            }
        )
    return {"baseline_top3": baseline_top3, "ablations": ablations}


def eval_degradation_rate(
    keywords: list[str],
    *,
    meta_path: Path = DEFAULT_META,
    review_path: Path = DEFAULT_REVIEWS,
) -> dict[str, Any]:
    price_hits = 0
    compliance_hits = 0
    blocked = 0
    coverages = []
    evaluated = 0
    for keyword in keywords:
        try:
            result = deep_dive(keyword, meta_path=meta_path, review_path=review_path)
        except Exception:
            continue
        research = result.get("research") or {}
        issues = research.get("issues") or []
        if any(issue.get("category") == "profitability_data_insufficient" for issue in issues):
            price_hits += 1
        if (research.get("score_breakdown") or {}).get("compliance", 100) < 50:
            compliance_hits += 1
        if research.get("decision") == "blocked":
            blocked += 1
        coverage = (result.get("intake_report") or {}).get("price_coverage")
        if isinstance(coverage, (int, float)):
            coverages.append(float(coverage))
        evaluated += 1

    return {
        "n": evaluated,
        "price_degradation_rate": round(_safe_div(price_hits, evaluated), 3),
        "compliance_human_review_rate": round(_safe_div(compliance_hits, evaluated), 3),
        "blocked_rate": round(_safe_div(blocked, evaluated), 3),
        "avg_price_coverage": round(sum(coverages) / len(coverages), 3) if coverages else 0.0,
    }


def run_opportunity_eval(
    fixture_path: Path = DEFAULT_FIXTURE,
    seed: str | None = None,
) -> dict[str, Any]:
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    selected_seed = seed or (fixture.get("seeds") or ["neck massager"])[0]
    index = DatasetIndex()
    noise = eval_noise_filter(fixture.get("noise_filter_labels") or [], index)
    baseline = discover(selected_seed)
    coverage = eval_signal_coverage(baseline)
    ablation = eval_signal_ablation(baseline, selected_seed)
    keywords = [item.keyword for item in baseline[:5]] or [selected_seed]
    degradation = eval_degradation_rate(keywords)
    return {
        "seed": selected_seed,
        "noise_filter": noise,
        "signal_coverage": coverage,
        "ablation": ablation,
        "degradation": degradation,
    }


def format_report(metrics: dict[str, Any]) -> str:
    noise = metrics["noise_filter"]
    coverage = metrics["signal_coverage"]
    ablation = metrics["ablation"]
    degradation = metrics["degradation"]
    lines = [
        "# Opportunity Engine Eval Report",
        "",
        f"Seed: `{metrics.get('seed', '')}`",
        "",
        "## 1. Noise Filter",
        "",
        "人工标注品牌词/意图词/真实赛道，评估 `_is_sellable_niche` 是否能把噪音挡在机会池外。",
        "",
        f"- Precision: **{noise['precision']}**",
        f"- Recall: **{noise['recall']}**",
        f"- F1: **{noise['f1']}**",
        f"- Confusion: `{noise['confusion']}`",
        "",
        "## 2. Signal Coverage",
        "",
        "统计每个赛道拿到几个有效信号，以及 live/cached/proxy/snapshot/unavailable 的来源分布。",
        "",
        f"- Full coverage count: **{coverage['full_coverage_count']}**",
        f"- Avg usable signals: **{coverage['avg_usable_signals']}**",
        f"- Coverage histogram: `{coverage['coverage_histogram']}`",
        f"- Provenance breakdown: `{coverage['provenance_breakdown']}`",
        "",
        "## 3. Signal Ablation",
        "",
        "逐个移除信号源重排 top-3，观察是否存在单一信号独大或无贡献信号。",
        "",
        f"- Baseline top3: `{ablation['baseline_top3']}`",
        "",
        "| Removed signal | Provider | Top1 changed | Displacement | New top3 |",
        "|---|---|---:|---:|---|",
    ]
    for item in ablation["ablations"]:
        lines.append(
            f"| {item['removed_signal']} | {item['provider']} | {item['top1_changed']} | "
            f"{item['displacement']} | `{item['new_top3']}` |"
        )
    lines.extend(
        [
            "",
            "## 4. Degradation Triggers",
            "",
            "降级率不是越高越好，它用于确认价格不足、合规风险等诚实机制确实会在真实赛道中触发。",
            "",
            f"- Evaluated niches: **{degradation['n']}**",
            f"- Price degradation rate: **{degradation['price_degradation_rate']}**",
            f"- Compliance human-review rate: **{degradation['compliance_human_review_rate']}**",
            f"- Blocked rate: **{degradation['blocked_rate']}**",
            f"- Avg price coverage: **{degradation['avg_price_coverage']}**",
            "",
            "## Resume Line",
            "",
            "Built an eval harness for a no-ground-truth ecommerce opportunity engine: noise-filter F1, signal coverage, signal ablation, and honest degradation-rate checks.",
            "",
        ]
    )
    return "\n".join(lines)


def _safe_div(num: float, denom: float) -> float:
    return num / denom if denom else 0.0


def main() -> None:
    seed = sys.argv[1] if len(sys.argv) > 1 else None
    if not DEFAULT_META.exists() or not DEFAULT_REVIEWS.exists():
        print("Amazon Reviews 2023 dataset not found; skip opportunity eval.")
        return
    metrics = run_opportunity_eval(seed=seed)
    report = format_report(metrics)
    DEFAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_REPORT.write_text(report, encoding="utf-8")
    print(f"Wrote {DEFAULT_REPORT}")
    print(f"noise_filter_f1={metrics['noise_filter']['f1']} avg_usable_signals={metrics['signal_coverage']['avg_usable_signals']}")


if __name__ == "__main__":
    main()
