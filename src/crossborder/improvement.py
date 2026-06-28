"""Turn review pain points into product-improvement requirements.

This module is intentionally deterministic. It does not invent product claims;
it maps known complaint topics from the Amazon Reviews loader into conservative
requirements and candidate listing bullets that still need compliance review.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import sys
from typing import Any

from crossborder.schemas import (
    ImprovementRequirement,
    ImprovementSpec,
    ReviewPainPoint,
)
from crossborder.tools_agent.contracts import input_hash

VERSION = "improvement-v1"
HONESTY_NOTE = (
    "卖点为候选措辞，发布前须过合规引擎；痛点源自关键词匹配的差评，"
    "非完整 QA，需人工二次确认。"
)

TOPIC_PLAYBOOK: dict[str, dict[str, Any]] = {
    "adhesive": {
        "requirement": "改强力/可重复粘性方案或加机械固定，减少脱落。",
        "bullet": "Strong, residue-free hold for everyday use",
        "keywords": ["strong adhesive", "reusable"],
    },
    "too bulky": {
        "requirement": "做更紧凑/低剖面结构，降低体积与重量。",
        "bullet": "Compact, low-profile design that saves space",
        "keywords": ["compact", "low profile"],
    },
    "durability": {
        "requirement": "使用更耐用材料或加固结构，提升日常使用寿命。",
        "bullet": "Reinforced build made for daily use",
        "keywords": ["durable", "reinforced"],
    },
    "installation": {
        "requirement": "简化安装流程，并提供清晰图文或视频说明。",
        "bullet": "Tool-free setup with a clear step-by-step guide",
        "keywords": ["easy setup", "tool-free"],
    },
    "size mismatch": {
        "requirement": "提供更准确的尺寸标注，并考虑可调或多尺寸方案。",
        "bullet": "Adjustable fit with an accurate size guide",
        "keywords": ["adjustable", "true to size"],
    },
    "odor": {
        "requirement": "选择低气味/亲肤材料，并增加出厂除味流程。",
        "bullet": "Odor-free, skin-friendly materials",
        "keywords": ["odor-free", "skin-friendly"],
    },
    "noise": {
        "requirement": "优化电机或结构减震，降低使用噪音。",
        "bullet": "Quiet operation for home and office",
        "keywords": ["quiet", "low noise"],
    },
    "battery": {
        "requirement": "提升电池容量或续航，并在页面如实标注使用时长。",
        "bullet": "Long-lasting battery with a clearly stated runtime",
        "keywords": ["long battery life", "rechargeable"],
    },
}

FALLBACK_PLAYBOOK = {
    "requirement": "针对该痛点制定产品改良，并在 listing 中如实说明。",
    "bullet": "Designed to address common buyer complaints",
    "keywords": [],
}


def build_improvement_spec(
    pain_points: list[ReviewPainPoint] | list[dict[str, Any]],
    *,
    product_title: str = "",
    keyword: str = "",
) -> ImprovementSpec:
    points = [
        point if isinstance(point, ReviewPainPoint) else ReviewPainPoint.model_validate(point)
        for point in pain_points
    ]
    points.sort(key=lambda p: max(1, p.frequency) * max(1, p.severity), reverse=True)

    requirements: list[ImprovementRequirement] = []
    bullets: list[str] = []
    keywords: list[str] = []
    for point in points:
        playbook = TOPIC_PLAYBOOK.get(point.topic, FALLBACK_PLAYBOOK)
        requirements.append(
            ImprovementRequirement(
                pain_topic=point.topic,
                requirement=str(playbook["requirement"]),
                priority=_priority(point.frequency, point.severity),
                frequency=point.frequency,
                severity=point.severity,
                evidence_quote=point.example,
                source_asins=list(point.source_asins),
            )
        )
        bullet = str(playbook["bullet"])
        if bullet not in bullets:
            bullets.append(bullet)
        for keyword_item in playbook.get("keywords") or []:
            if keyword_item not in keywords:
                keywords.append(str(keyword_item))

    payload_for_hash = {
        "product_title": product_title,
        "keyword": keyword,
        "pain_points": [point.model_dump(mode="json") for point in points],
    }
    return ImprovementSpec(
        product_title=product_title,
        keyword=keyword,
        requirements=requirements,
        differentiation_bullets=bullets[:5],
        emphasis_keywords=keywords[:10],
        honesty_note=HONESTY_NOTE,
        audit={
            "tool": "crossborder.improvement",
            "runtime": "deterministic_rules",
            "input_hash": input_hash(payload_for_hash),
            "created_at": datetime.now(UTC).isoformat(),
            "version": VERSION,
        },
    )


def _priority(frequency: int, severity: int) -> str:
    score = max(1, frequency) * max(1, severity)
    if score >= 30:
        return "high"
    if score >= 10:
        return "medium"
    return "low"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build product-improvement spec from review pain points.")
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    spec = build_improvement_spec(
        payload.get("pain_points") or [],
        product_title=str(payload.get("product_title") or ""),
        keyword=str(payload.get("keyword") or ""),
    )
    json.dump(spec.model_dump(mode="json"), sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
