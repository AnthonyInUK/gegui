"""
商家证照核验 —— 第二个场景实例（验证引擎可插拔）

刻意复用与电商场景**完全相同**的 Scene 契约和引擎：
只换 knowledge_base + 专家 + output_schema，core/ 一行不改。

注意 output_schema 仍暴露引擎约定的 verdict / confidence / violations 字段，
每个 violation 带 law_quote（法规依据）以兼容置信度校准。
"""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path

from pydantic import BaseModel, Field

from scenes.base import ExpertSpec, PrescreenResult, ReviewMaterial, Scene

_KB_PATH = Path(__file__).parent / "knowledge_base.json"


class LicenseIssue(BaseModel):
    rule_id: str = Field(description="问题类型 id，如 expired / missing_license / scope_mismatch / forgery_suspect")
    rule_name: str = Field(description="问题名称")
    law_article: str = Field(default="", description="对应法规")
    law_quote: str = Field(default="", description="法规/知识库原文依据；引不出留空（将拉低置信度）")
    evidence: str = Field(description="证据：哪张证、哪个字段")
    location: str = Field(default="", description="出现位置")
    suggestion: str = Field(default="", description="处理建议")


class LicenseReviewResult(BaseModel):
    verdict: str = Field(description="PASS / VIOLATION / NEEDS_HUMAN")
    violations: list[LicenseIssue] = Field(default_factory=list)
    confidence: float = Field(description="判定置信度 0-1")
    summary: str = Field(default="", description="一句话结论")


class MerchantLicenseScene(Scene):
    scene_id = "merchant_license"
    display_name = "本地生活商家证照核验"

    @cached_property
    def knowledge_base(self) -> dict:
        return json.loads(_KB_PATH.read_text(encoding="utf-8"))

    @property
    def output_schema(self) -> type[BaseModel]:
        return LicenseReviewResult

    def vision_prompt(self) -> str:
        return (
            "你是证照图片识别器。逐字识别证件上的关键字段："
            "证件名称、统一社会信用代码/许可证编号、经营者名称、经营范围/经营项目、"
            "有效期/营业期限、登记/发证机关。并留意是否有篡改迹象"
            "（日期字体不一致、公章模糊变形、编号位数异常）。"
            "只做客观识别、不做合规判断，严格输出 JSON：\n"
            '{"ocr_text": ["逐字段：字段名=值"], "visual_elements": "证件类型与版式描述", '
            '"suspicious_details": ["篡改/伪造迹象，无则空"]}'
        )

    def prescreen(self, material: ReviewMaterial) -> PrescreenResult:
        # 证照核验没有"便宜放行"的情形：每条都要看图核验
        if material.image_paths:
            return PrescreenResult(
                needs_review=True,
                reason="提交了证照图片，需多模态核验字段/有效期/经营范围",
            )
        return PrescreenResult(
            needs_review=True,
            reason="未提交证照图片，需核查是否缺证",
        )

    def expert_specs(self) -> list[ExpertSpec]:
        kb_text = json.dumps(self.knowledge_base, ensure_ascii=False, indent=2)
        declared = "（商家申报类目见 metadata）"
        return [
            ExpertSpec(
                name="validity",
                description="证照有效性专家：核查证件字段完整性、有效期是否过期、是否有篡改/伪造迹象",
                system_prompt=(
                    "你是证照有效性核验专家。依据下方知识库，核查识别出的证照：\n\n"
                    "判定要点：\n"
                    "1. 必填字段是否齐全（缺字段 → 疑问）。\n"
                    "2. 有效期/营业期限是否过期（'长期'视为有效）。\n"
                    "3. 是否命中 forgery_signals 的伪造迹象 → 判 forgery_suspect 并转人工。\n"
                    "4. 每条问题给出：rule_id、law_quote（知识库 rule_basis 原文，不得编造）、"
                    "证据字段、处理建议。\n"
                    "5. 拿不准真伪的，降低 confidence。\n\n"
                    f"【知识库】\n{kb_text}"
                ),
                model_role="text",
            ),
            ExpertSpec(
                name="scope_match",
                description="经营范围匹配专家：判断证照经营范围/项目是否覆盖商家申报的经营类目，是否缺对应证照",
                system_prompt=(
                    "你是经营范围匹配专家。依据知识库 category_required_licenses，"
                    "判断商家申报类目所需证照是否齐全、经营范围是否覆盖。\n\n"
                    "判定要点：\n"
                    "1. 申报类目对应的必需证照是否都提交了（缺 → missing_license）。\n"
                    "2. 营业执照/许可证的经营范围是否含申报类目（不含 → scope_mismatch）。\n"
                    "3. 每条给出：rule_id、law_quote（原文）、证据、整改建议。\n\n"
                    f"商家申报类目：{declared}\n\n"
                    f"【知识库】\n{kb_text}"
                ),
                model_role="text",
            ),
        ]
