"""
评估指标（纯函数，离线可测）

不止"对/错准确率"，而是大厂看重的严谨度：
  - 总准确率 + "安全率"（判对 或 安全地转人工）
  - 按规避类型拆准确率（谐音/拆字/图内字/跨模态 各自命中）
  - precision / recall（以 VIOLATION 为正类）
  - 置信度校准曲线（置信度分桶 → 该桶准确率，看二者是否相关）
"""

from __future__ import annotations

from collections import defaultdict
from statistics import mean


def compute_metrics(predictions: list[dict]) -> dict:
    """predictions: [{id, evasion_type, expected, predicted, confidence}, ...]

    expected / predicted ∈ {VIOLATION, PASS, NEEDS_HUMAN}
    """
    n = len(predictions)
    if n == 0:
        return {"n": 0}

    exact = sum(1 for p in predictions if p["predicted"] == p["expected"])
    # 安全率：判对，或在该违规上"安全地转人工"（NEEDS_HUMAN 不算误放行）
    safe = sum(
        1 for p in predictions
        if p["predicted"] == p["expected"]
        or (p["expected"] == "VIOLATION" and p["predicted"] == "NEEDS_HUMAN")
    )
    human = sum(1 for p in predictions if p["predicted"] == "NEEDS_HUMAN")
    false_release = sum(
        1 for p in predictions
        if p["expected"] == "VIOLATION" and p["predicted"] == "PASS"
    )
    false_block = sum(
        1 for p in predictions
        if p["expected"] == "PASS" and p["predicted"] == "VIOLATION"
    )

    # 按规避类型
    by_type: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "correct": 0, "safe": 0, "needs_human": 0}
    )
    for p in predictions:
        t = by_type[p["evasion_type"]]
        t["n"] += 1
        correct = p["predicted"] == p["expected"]
        t["correct"] += int(correct)
        t["safe"] += int(correct or (p["expected"] == "VIOLATION" and p["predicted"] == "NEEDS_HUMAN"))
        t["needs_human"] += int(p["predicted"] == "NEEDS_HUMAN")
    by_type = {
        k: {
            **v,
            "accuracy": round(v["correct"] / v["n"], 3),
            "safe_rate": round(v["safe"] / v["n"], 3),
        }
        for k, v in by_type.items()
    }

    # 混淆矩阵（VIOLATION 为正类；NEEDS_HUMAN/PASS 视为"未判正"）
    tp = sum(1 for p in predictions if p["expected"] == "VIOLATION" and p["predicted"] == "VIOLATION")
    fn = sum(1 for p in predictions if p["expected"] == "VIOLATION" and p["predicted"] != "VIOLATION")
    fp = sum(1 for p in predictions if p["expected"] == "PASS" and p["predicted"] == "VIOLATION")
    tn = sum(1 for p in predictions if p["expected"] == "PASS" and p["predicted"] != "VIOLATION")
    precision = round(tp / (tp + fp), 3) if (tp + fp) else None
    recall = round(tp / (tp + fn), 3) if (tp + fn) else None
    f1 = (
        round(2 * precision * recall / (precision + recall), 3)
        if precision and recall else None
    )

    token_values = [int(p.get("tokens") or 0) for p in predictions if p.get("tokens") is not None]
    latency_values = [
        int(p.get("latency_ms") or 0) for p in predictions if p.get("latency_ms") is not None
    ]

    return {
        "n": n,
        "accuracy": round(exact / n, 3),
        "safe_rate": round(safe / n, 3),
        "human_rate": round(human / n, 3),
        "false_release": false_release,
        "false_block": false_block,
        "by_evasion_type": by_type,
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "avg_tokens": round(mean(token_values), 1) if token_values else 0,
        "total_tokens": sum(token_values),
        "avg_latency_ms": round(mean(latency_values), 1) if latency_values else 0,
        "calibration": calibration_curve(predictions),
    }


def calibration_curve(predictions: list[dict], n_buckets: int = 4) -> list[dict]:
    """置信度分桶 → 桶内准确率。理想情况：置信度越高，准确率越高。"""
    buckets: dict[int, dict] = defaultdict(lambda: {"n": 0, "correct": 0})
    for p in predictions:
        conf = float(p.get("confidence") or 0.0)
        idx = min(int(conf * n_buckets), n_buckets - 1)  # [0,1)→桶
        buckets[idx]["n"] += 1
        buckets[idx]["correct"] += int(p["predicted"] == p["expected"])
    out = []
    for i in range(n_buckets):
        b = buckets.get(i, {"n": 0, "correct": 0})
        lo, hi = i / n_buckets, (i + 1) / n_buckets
        right = "]" if i == n_buckets - 1 else ")"
        out.append({
            "range": f"[{lo:.2f},{hi:.2f}{right}",
            "n": b["n"],
            "accuracy": round(b["correct"] / b["n"], 3) if b["n"] else None,
        })
    return out


def format_report(metrics: dict) -> str:
    """渲染成可读报告（markdown）。"""
    if metrics.get("n", 0) == 0:
        return "（无样本）"
    lines = [
        f"# Eval 报告（n={metrics['n']}）\n",
        "## 摘要",
        f"- 总准确率: **{metrics['accuracy']}**　安全率: **{metrics['safe_rate']}**　转人工率: **{metrics['human_rate']}**",
        f"- precision: {metrics['precision']}　recall: {metrics['recall']}　f1: {metrics['f1']}",
        f"- 误放行: **{metrics['false_release']}**　误拦截: **{metrics['false_block']}**",
        f"- 平均 token: {metrics['avg_tokens']}　总 token: {metrics['total_tokens']}　平均延迟: {metrics['avg_latency_ms']} ms",
        f"- 混淆矩阵: {metrics['confusion']}\n",
        "## 简历可写",
        (
            f"- 构建 {metrics['n']} 条多模态对抗评测集，覆盖图内藏字、谐音/拆字、繁体、"
            f"医疗功效、类目资质、跨模态组合和正常素材；当前准确率 {metrics['accuracy']}，"
            f"安全率 {metrics['safe_rate']}，违规召回 {metrics['recall']}，误放行 {metrics['false_release']} 条。"
        ),
        "",
        "## 按规避类型",
        "| 规避类型 | 样本 | 命中 | 转人工 | 准确率 | 安全率 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for t, v in metrics["by_evasion_type"].items():
        lines.append(
            f"| {t} | {v['n']} | {v['correct']} | {v['needs_human']} | "
            f"{v['accuracy']} | {v['safe_rate']} |"
        )
    lines += ["\n## 置信度校准曲线", "| 置信度区间 | 样本 | 准确率 |", "|---|---|---|"]
    for b in metrics["calibration"]:
        lines.append(f"| {b['range']} | {b['n']} | {b['accuracy']} |")
    return "\n".join(lines)
