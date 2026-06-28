"""
审核并落库入口（真实端到端）

把"计算"与"存储"接起来：engine.review() 跑完 → storage.save_outcome() 落库，
之后看板能看到这条真实记录（含原图，供人工核对）。

用法：
    python src/run_review.py --case abs_plain_01      # 跑对抗样本集里的某条
    python src/run_review.py --text "文案" --image path/to.png
"""

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
load_dotenv(ROOT / ".env")

from core import storage  # noqa: E402
from core.orchestrator import ReviewEngine  # noqa: E402
from scenes.base import ReviewMaterial  # noqa: E402
from scenes.ecommerce_ad.scene import EcommerceAdScene  # noqa: E402

CASES_DIR = ROOT / "tests/ecommerce_ad"


def resolve_material(args) -> ReviewMaterial:
    if args.case:
        cases = json.loads((CASES_DIR / "cases.json").read_text(encoding="utf-8"))
        c = next((x for x in cases if x["id"] == args.case), None)
        if not c:
            sys.exit(f"找不到 case: {args.case}")
        img = CASES_DIR / c["material"]["image"]
        return ReviewMaterial(text=c["material"]["text"], image_paths=[str(img)])
    if args.text:
        imgs = [args.image] if args.image else []
        return ReviewMaterial(text=args.text, image_paths=imgs)
    sys.exit("需提供 --case 或 --text")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", help="对抗样本集里的 case id")
    ap.add_argument("--text", help="自定义文案")
    ap.add_argument("--image", help="自定义图片路径")
    args = ap.parse_args()

    material = resolve_material(args)
    print(f"审核：{material.text}  图片={material.image_paths}")

    # 真实端到端：审核（不走缓存）→ 落库
    eng = ReviewEngine(EcommerceAdScene(), use_cache=False, use_feedback=True, use_debate=True)
    outcome = eng.review(material)
    rid = storage.save_outcome(
        material, outcome, scene_id="ecommerce_ad",
        tokens=outcome.tokens, latency_ms=outcome.latency_ms,
    )

    print(f"\n判定：{outcome.final_verdict}  置信={outcome.confidence}  "
          f"成本={outcome.tokens}tok/{outcome.latency_ms}ms")
    for s in outcome.reasoning_chain:
        print(f"  {s}")
    print(f"\n已落库：{rid} → 刷新看板即可看到（含原图）")


if __name__ == "__main__":
    main()
