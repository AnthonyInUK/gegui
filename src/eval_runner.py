"""
Eval 运行器：在对抗样本集上跑引擎，产出准确率报告。

用法：
    python src/eval_runner.py                         # 跑全部样本（真实调模型）
    python src/eval_runner.py --limit 3               # 只跑前 3 个（省 API）
    python src/eval_runner.py --from-predictions docs/eval_predictions.json
                                                    # 不调模型，仅复算报告

产出：docs/eval_report.md（报告）+ docs/eval_predictions.json（原始预测）
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

from core.evaluation import compute_metrics, format_report  # noqa: E402
from core.model_provider import active_provider_name  # noqa: E402
from core.orchestrator import ReviewEngine  # noqa: E402
from scenes.base import ReviewMaterial  # noqa: E402
from scenes.ecommerce_ad.scene import EcommerceAdScene  # noqa: E402

CASES_PATH = ROOT / "tests/ecommerce_ad/cases.json"
CASES_DIR = CASES_PATH.parent


def load_cases(limit: int = 0) -> list[dict]:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return cases[:limit] if limit else cases


def merge_expected(predictions: list[dict], cases: list[dict]) -> list[dict]:
    """允许预测文件只存 id/predicted/confidence，其余标签从 cases.json 补齐。"""
    by_id = {c["id"]: c for c in cases}
    merged = []
    for p in predictions:
        c = by_id.get(p["id"], {})
        item = {
            "id": p["id"],
            "evasion_type": p.get("evasion_type") or c.get("evasion_type", "unknown"),
            "expected": p.get("expected") or c.get("expected_verdict"),
            "predicted": p["predicted"],
            "confidence": p.get("confidence", 0.0),
            "tokens": p.get("tokens", 0),
            "latency_ms": p.get("latency_ms", 0),
        }
        if not item["expected"]:
            raise ValueError(f"预测缺少 expected，且 cases.json 中找不到 id={p['id']}")
        merged.append(item)
    return merged


def write_outputs(predictions: list[dict], report_header: str = "") -> str:
    metrics = compute_metrics(predictions)

    out_dir = ROOT / "docs"
    out_dir.mkdir(exist_ok=True)
    report = format_report(metrics)
    if report_header:
        report = report_header.rstrip() + "\n\n" + report

    (out_dir / "eval_report.md").write_text(report + "\n", encoding="utf-8")
    (out_dir / "eval_predictions.json").write_text(
        json.dumps(predictions, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个样本（0=全部）")
    ap.add_argument(
        "--from-predictions",
        type=Path,
        help="从已有预测 JSON 复算报告，不调模型；适合冻结一次真实跑的结果",
    )
    args = ap.parse_args()

    cases = load_cases(args.limit)
    if args.from_predictions:
        raw = json.loads(args.from_predictions.read_text(encoding="utf-8"))
        predictions = merge_expected(raw, cases)
        report = write_outputs(
            predictions,
            report_header=(
                "# 电商广告法多模态审核 Eval\n\n"
                f"- 模式: 从预测文件复算（{args.from_predictions}）\n"
                f"- 样本集: {CASES_PATH}"
            ),
        )
        print(report)
        print("\n已保存：docs/eval_report.md, docs/eval_predictions.json")
        return

    # eval 用：不走缓存（要真跑）、不注入反馈（纯净评估）、开辩论
    eng = ReviewEngine(EcommerceAdScene(), use_cache=False, use_feedback=False, use_debate=True)

    predictions = []
    for i, c in enumerate(cases, 1):
        img = CASES_DIR / c["material"]["image"]
        material = ReviewMaterial(text=c["material"]["text"], image_paths=[str(img)])
        print(f"[{i}/{len(cases)}] {c['id']} ({c['evasion_type']}) ...", flush=True)
        outcome = eng.review(material)
        predictions.append({
            "id": c["id"],
            "evasion_type": c["evasion_type"],
            "expected": c["expected_verdict"],
            "predicted": outcome.final_verdict,
            "confidence": outcome.confidence,
            "tokens": outcome.tokens,
            "latency_ms": outcome.latency_ms,
        })
        print(f"     → {outcome.final_verdict} (conf={outcome.confidence}, "
              f"{outcome.tokens}tok/{outcome.latency_ms}ms)")

    report = write_outputs(
        predictions,
        report_header=(
            "# 电商广告法多模态审核 Eval\n\n"
            "- 模式: 真实模型评测\n"
            f"- 视觉模型: {active_provider_name('vision')}\n"
            f"- 文本模型: {active_provider_name('text')}\n"
            f"- 样本集: {CASES_PATH}"
        ),
    )
    print("\n" + report)
    print(f"\n已保存：docs/eval_report.md, docs/eval_predictions.json")


if __name__ == "__main__":
    main()
