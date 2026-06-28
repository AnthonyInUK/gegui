"""
给看板灌入演示数据（离线，不调模型）。
覆盖 VIOLATION / PASS / NEEDS_HUMAN + 一条已人工裁决，便于演示反馈闭环。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import storage
from core.schemas import ReviewOutcome
from scenes.base import ReviewMaterial

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "tests" / "ecommerce_ad" / "adversarial_cases"


def seed():
    samples = [
        (ReviewMaterial(
            text="智能扫地机器人",
            image_paths=[str(IMG_DIR / "abs_plain_01.png")],
        ), ReviewOutcome(
            final_verdict="VIOLATION", confidence=0.95,
            violations=[{"expert": "ad_law", "rule_id": "absolute_terms", "rule_name": "绝对化用语",
                         "law_article": "广告法第九条第（三）项", "evidence": "图内文字'全国销量第一'",
                         "suggestion": "改为'热销商品'"}],
            reasoning_chain=["[初筛] 含图片，需多模态复审", "[看图] OCR=['全国销量第一']",
                             "[专家:ad_law] VIOLATION conf=0.95", "[路由] VIOLATION 校准后0.95"],
            tokens=5320, latency_ms=12400), 4800),
        (ReviewMaterial(
            text="诚邀加入，时间灵活，多劳多得",
            image_paths=[str(IMG_DIR / "cross_income.png")],
        ), ReviewOutcome(
            final_verdict="VIOLATION", confidence=0.9,
            violations=[{"expert": "cross_modal", "rule_id": "false_income_inducement", "rule_name": "暴富暗示",
                         "law_article": "广告法第四条", "evidence": "豪车图+'多劳多得'", "suggestion": "移除豪车图"}],
            reasoning_chain=["[并行] 3 专家并发", "[冲突检测] 分歧：cross_modal 判违规",
                             "[辩论] 触发一轮专家互评", "[辩论后:qualification] 被说服改判 VIOLATION",
                             "[路由] VIOLATION 0.9"],
            tokens=10775, latency_ms=33300), 9900),
        (ReviewMaterial(
            text="静音扫地机器人，大吸力，高性价比",
            image_paths=[str(IMG_DIR / "clean_normal_01.png")],
        ), ReviewOutcome(
            final_verdict="PASS", confidence=0.92,
            reasoning_chain=["[并行] 3 专家并发", "[冲突检测] 一致", "[路由] PASS"],
            tokens=4100, latency_ms=9800), 3900),
        (ReviewMaterial(
            text="夏季新款连衣裙 限时优惠",
            image_paths=[str(IMG_DIR / "clean_promo_01.png")],
        ), ReviewOutcome(
            final_verdict="NEEDS_HUMAN", confidence=0.6, needs_human=True,
            violations=[{"expert": "cross_modal", "rule_id": "false_income_inducement", "rule_name": "暴富暗示",
                         "law_article": "", "evidence": "图文组合存疑", "suggestion": "需人工确认"}],
            reasoning_chain=["[专家:cross_modal] VIOLATION conf=0.6",
                             "[路由] 校准后0.45 < 0.75，转人工（无法条原文依据）"],
            tokens=6200, latency_ms=15100), 5800),
    ]
    ids = []
    for mat, out, _ in samples:
        rid = storage.save_outcome(mat, out, scene_id="ecommerce_ad",
                                   tokens=out.tokens, latency_ms=out.latency_ms)
        ids.append(rid)
    # 给第一条加一条人工裁决（演示反馈闭环）
    storage.record_feedback(ids[0], "APPROVE", "确认绝对化用语违规")
    print(f"已灌入 {len(ids)} 条演示记录：{ids}")
    print("统计:", storage.stats())


if __name__ == "__main__":
    seed()
