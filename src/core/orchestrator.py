"""
审核引擎编排器（场景无关）

把一条素材跑完整流程：
    初筛 → 看图 → 串行跑各专家 → 合并违规 → 置信度路由 → ReviewOutcome

合并 + 路由逻辑抽成纯函数 `merge_and_route`，可用假数据离线测，无需调模型。

专家结论（scene.output_schema）需暴露以下字段供引擎读取：
    verdict: str / confidence: float / violations: list[BaseModel] / summary: str
"""

from __future__ import annotations

from pydantic import BaseModel

from core.approval import ApprovalHandler, apply_decision
from core.experts import run_expert
from core.schemas import ReviewOutcome
from core.vision_agent import extract_from_images
from scenes.base import ReviewMaterial, Scene

DEFAULT_THRESHOLD = 0.75


def calibrate_confidence(violations: list[dict], raw_conf: float) -> float:
    """置信度校准：把置信度锚定在"有没有法条原文依据"，而非模型自评。

    每条违规须有 law_quote（法条原文）。未引用原文的违规拉低整体置信度，
    迫使"无依据的判定"落到阈值以下 → 转人工。这是对抗 LLM 过度自信的关键。
    """
    if not violations:
        return raw_conf
    grounded = sum(1 for v in violations if (v.get("law_quote") or "").strip())
    ratio = grounded / len(violations)
    # ratio=1（全有原文）→ 不打折；ratio=0（全无原文）→ 砍半
    return round(min(raw_conf, raw_conf * (0.5 + 0.5 * ratio)), 3)


def merge_and_route(
    expert_results: list[tuple[str, BaseModel]],
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[str, float, list[dict]]:
    """合并各专家结论并做置信度路由（纯函数，离线可测）。

    Args:
        expert_results: [(专家名, 专家结论对象), ...]，结论对象需有
                        verdict / confidence / violations 字段。
        threshold: 置信度阈值，低于此值的违规判定转人工。

    Returns:
        (final_verdict, confidence, merged_violations)
    """
    merged: list[dict] = []
    violating_confidences: list[float] = []
    all_confidences: list[float] = []

    for name, res in expert_results:
        conf = float(getattr(res, "confidence", 0.0) or 0.0)
        all_confidences.append(conf)
        violations = getattr(res, "violations", []) or []
        if violations:
            violating_confidences.append(conf)
        for v in violations:
            item = v.model_dump() if isinstance(v, BaseModel) else dict(v)
            item["expert"] = name  # 标注来自哪个专家
            merged.append(item)

    if not merged:
        # 无违规 → 放行；置信度取各专家均值
        conf = sum(all_confidences) / len(all_confidences) if all_confidences else 1.0
        return "PASS", round(conf, 3), []

    # 有违规 → 取最有把握的检出专家置信度，再按"法条原文依据"做校准
    violation_conf = max(violating_confidences) if violating_confidences else 0.0
    violation_conf = calibrate_confidence(merged, violation_conf)
    verdict = "VIOLATION" if violation_conf >= threshold else "NEEDS_HUMAN"
    return verdict, violation_conf, merged


class ReviewEngine:
    """绑定一个 Scene，对素材执行完整审核流程。"""

    def __init__(
        self,
        scene: Scene,
        threshold: float = DEFAULT_THRESHOLD,
        approval_handler: ApprovalHandler | None = None,
        use_cache: bool = True,
        use_feedback: bool = True,
        parallel: bool = True,
        use_debate: bool = True,
    ):
        self.scene = scene
        self.threshold = threshold
        self.approval_handler = approval_handler  # None=不审批，直接返回 NEEDS_HUMAN
        self.use_cache = use_cache              # 去重缓存：相同内容直接复用历史结论
        self.use_feedback = use_feedback        # 反馈闭环：注入人工纠正样本作 few-shot
        self.parallel = parallel                # 专家并行扇出（asyncio）vs 串行
        self.use_debate = use_debate            # 冲突触发式一轮辩论

    def review(self, material: ReviewMaterial) -> ReviewOutcome:
        import time

        from core import storage

        chain: list[str] = []
        t0 = time.monotonic()

        # 0) 去重缓存：相同素材命中历史结论，直接返回，省 API
        if self.use_cache:
            cached = storage.get_cached(material)
            if cached is not None:
                cached.from_cache = True
                return cached

        # 1) 初筛
        pre = self.scene.prescreen(material)
        chain.append(f"[初筛] {pre.reason}")
        if not pre.needs_review:
            return ReviewOutcome(
                final_verdict="PASS",
                confidence=1.0,
                needs_human=False,
                reasoning_chain=chain,
                prescreen_reason=pre.reason,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )

        total_tokens = 0

        # 2) 看图（仅当有图片）
        vision_ctx = "【无图片】"
        if material.image_paths:
            vision, v_tokens = extract_from_images(
                material.image_paths,
                vision_prompt=self.scene.vision_prompt(),
            )
            total_tokens += v_tokens
            vision_ctx = vision.as_context()
            chain.append(f"[看图] OCR={vision.ocr_text} 可疑={vision.suspicious_details}")

        # 反馈闭环：拉取本场景的人工纠正样本，作为专家 few-shot
        corrections_hint = ""
        if self.use_feedback:
            from core.experts import build_corrections_hint
            samples = storage.get_correction_samples(scene_id=self.scene.scene_id)
            corrections_hint = build_corrections_hint(samples)
            if samples:
                chain.append(f"[反馈] 注入 {len(samples)} 条人工纠正样本作 few-shot")

        # 3) 跑各专家（并行扇出 / 串行）
        specs = self.scene.expert_specs()
        if self.parallel and len(specs) > 1:
            expert_results, e_tokens = self._run_experts_parallel(
                specs, material.text, vision_ctx, corrections_hint
            )
            chain.append(f"[并行] {len(specs)} 专家并发扇出（asyncio）")
        else:
            expert_results, e_tokens = self._run_experts_serial(
                specs, material.text, vision_ctx, corrections_hint
            )
        total_tokens += e_tokens
        for name, res in expert_results:
            v_count = len(getattr(res, "violations", []) or [])
            chain.append(
                f"[专家:{name}] verdict={getattr(res, 'verdict', '?')} "
                f"conf={getattr(res, 'confidence', '?')} 违规{v_count}项"
            )

        # 3.5) 冲突触发式辩论：专家分歧时才让他们互评一轮
        if self.use_debate and len(expert_results) > 1:
            from core.debate import detect_conflict, run_debate
            conflict, why = detect_conflict(expert_results)
            chain.append(f"[冲突检测] {why}")
            if conflict:
                expert_results, d_tokens = run_debate(
                    self.scene, expert_results, material.text, vision_ctx
                )
                total_tokens += d_tokens
                chain.append("[辩论] 触发一轮专家互评，已据对方意见重新裁决")
                for name, res in expert_results:
                    chain.append(
                        f"[辩论后:{name}] verdict={getattr(res, 'verdict', '?')} "
                        f"conf={getattr(res, 'confidence', '?')} "
                        f"违规{len(getattr(res, 'violations', []) or [])}项"
                    )

        # 4) 合并 + 路由（含置信度校准）
        verdict, confidence, violations = merge_and_route(expert_results, self.threshold)
        needs_human = verdict == "NEEDS_HUMAN"
        chain.append(
            f"[路由] {verdict} 校准后置信={confidence} 阈值={self.threshold}"
            + ("（低于阈值，转人工）" if needs_human else "")
        )

        outcome = ReviewOutcome(
            final_verdict=verdict,
            confidence=confidence,
            needs_human=needs_human,
            violations=violations,
            expert_results=[
                {"expert": n, **(r.model_dump() if isinstance(r, BaseModel) else {})}
                for n, r in expert_results
            ],
            reasoning_chain=chain,
            prescreen_reason=pre.reason,
            tokens=total_tokens,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

        # 5) 人工审批闸门：转人工 + 配了处理器 → 让人裁决
        if outcome.needs_human and self.approval_handler is not None:
            decision = self.approval_handler.decide(outcome)
            outcome = apply_decision(outcome, decision)

        return outcome

    def _run_experts_serial(self, specs, text, vision_ctx, corrections_hint):
        results, tokens = [], 0
        for spec in specs:
            res, t = run_expert(spec, text, vision_ctx, self.scene.output_schema, corrections_hint)
            results.append((spec.name, res))
            tokens += t
        return results, tokens

    def _run_experts_parallel(self, specs, text, vision_ctx, corrections_hint):
        """并行扇出：独立专家用 asyncio.gather 并发，省总延迟。"""
        import asyncio

        from core.experts import run_expert_async

        async def gather():
            tasks = [
                run_expert_async(s, text, vision_ctx, self.scene.output_schema, corrections_hint)
                for s in specs
            ]
            return await asyncio.gather(*tasks)

        triples = asyncio.run(gather())  # [(name, result, tokens), ...]
        results = [(name, res) for name, res, _ in triples]
        tokens = sum(t for _, _, t in triples)
        return results, tokens
