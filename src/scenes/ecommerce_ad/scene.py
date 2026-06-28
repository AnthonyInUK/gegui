"""
电商广告法素材审核 —— 首发场景实例

实现 Scene 接口的四样契约：knowledge_base / expert_specs / prescreen / output_schema。
引擎核心据此跑完整审核流程，与本场景的具体规则解耦。
"""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path

from pydantic import BaseModel, Field

from scenes.base import ExpertSpec, PrescreenResult, ReviewMaterial, Scene

_KB_PATH = Path(__file__).parent / "knowledge_base.json"


# ---------- 本场景的结构化结论 ----------

class Violation(BaseModel):
    rule_id: str = Field(description="命中的违规规则 id，如 absolute_terms")
    rule_name: str = Field(description="违规类型名称")
    law_article: str = Field(default="", description="对应法条编号，如 广告法第九条第（三）项")
    law_quote: str = Field(default="", description="引用的法条/知识库原文片段；引不出就留空（将拉低置信度）")
    evidence: str = Field(description="违规证据：具体是哪段文字/画面")
    location: str = Field(default="", description="出现位置：文案 / 图内文字 / 图文组合")
    suggestion: str = Field(
        default="",
        description=(
            "可直接替换的改写方案：引用证据原文中的违规词句，给出1-2个可直接使用的替换文案。"
            "格式：将「原文违规词句」改为「具体替换文案A」或「具体替换文案B」。"
            "参考知识库 remediation_templates，但必须结合当前文案语境生成具体版本，不得只写通用建议。"
        ),
    )


class AdReviewResult(BaseModel):
    verdict: str = Field(description="PASS / VIOLATION / NEEDS_HUMAN")
    violations: list[Violation] = Field(default_factory=list)
    confidence: float = Field(description="判定置信度 0-1")
    summary: str = Field(default="", description="一句话结论")


# ---------- 场景实现 ----------

class EcommerceAdScene(Scene):
    scene_id = "ecommerce_ad"
    display_name = "电商广告法素材审核"

    @cached_property
    def knowledge_base(self) -> dict:
        return json.loads(_KB_PATH.read_text(encoding="utf-8"))

    @property
    def output_schema(self) -> type[BaseModel]:
        return AdReviewResult

    def vision_prompt(self) -> str:
        # 强调本场景最关心的：图内文字 + 规避迹象
        return (
            "你是电商素材的图片视觉提取器。重点逐字识别图中所有文字"
            "（含主图上的大字、角标小字、水印、做进画面里的促销语），"
            "并留意是否存在拆字、谐音、繁体、符号插入等规避检测的迹象。"
            "只做客观提取、不做合规判断，严格输出 JSON：\n"
            '{"ocr_text": ["逐条文字"], "visual_elements": "画面描述", '
            '"suspicious_details": ["规避迹象，无则空"]}'
        )

    def prescreen(self, material: ReviewMaterial) -> PrescreenResult:
        """初筛层（便宜、纯文本）：扫文案黑名单。

        两层定位的体现：
        - 文案命中明显违禁词 → 进 agent 复审（确认 + 出整改建议）
        - 带图片 → 必进复审（图内可能藏违禁词，便宜文本筛看不到）
        - 纯文案且无命中 → 放行，不浪费大模型
        """
        hits: list[str] = []
        for rule in self.knowledge_base["violation_rules"]:
            for term in rule.get("blacklist", []):
                if term in material.text:
                    hits.append(term)

        if material.image_paths:
            return PrescreenResult(
                needs_review=True,
                reason="含图片，需多模态复审（图内可能藏违禁词）",
                hits=hits,
            )
        if hits:
            return PrescreenResult(
                needs_review=True,
                reason=f"文案命中疑似违禁词：{hits}",
                hits=hits,
            )
        return PrescreenResult(needs_review=False, reason="纯文案且无黑名单命中，直接放行")

    def expert_specs(self) -> list[ExpertSpec]:
        kb_text = json.dumps(self.knowledge_base, ensure_ascii=False, indent=2)
        return [
            ExpertSpec(
                name="ad_law",
                description="广告法违禁词专家：绝对化用语、虚假功效、医疗用语、暴富暗示，能识破谐音/拆字/繁体/图内藏字等规避手法",
                system_prompt=(
                    "你是中国广告法合规审核专家。依据下方知识库，审核电商素材"
                    "（文案 + 图片视觉提取结果）是否违反广告法。\n\n"
                    "判定要点：\n"
                    "1. 不只做字面匹配——谐音（国jia级）、拆字（国$家$级）、繁体（國家級）、"
                    "符号插入（第—一）、语义擦边（找不到更低价=最低价）都要识别。\n"
                    "2. 图内文字与文案同等对待：违禁词藏在图里也算违规。\n"
                    "3. 每条违规必须给出：命中规则 id、法条编号、**法条/知识库原文片段（law_quote）**、"
                    "证据原文、出现位置、整改建议。\n"
                    "4. law_quote 必须是知识库里真实存在的法条原文，不得编造；引不出原文就留空。\n"
                    "5. 拿不准的（语义模糊、可能豁免）要降低 confidence 并说明。\n"
                    "6. suggestion 字段必须是可直接替换的改写方案，而非泛泛建议：\n"
                    "   - 引用证据原文（evidence 字段）中的具体违规词句\n"
                    "   - 给出至少一个可直接粘贴使用的替换文案\n"
                    "   - 参考知识库 remediation_templates 字段的改写方向，但结合当前语境生成具体版本\n"
                    "   - 示例：evidence='销量第一的数据线' → suggestion='将「销量第一」改为「热销数据线」或「深受用户好评的数据线」'\n"
                    "7. 隐含声称检测（语义层）——除字面匹配外，还需识别：\n"
                    "   - 持续性/永久性暗示：如「可连续使用一年不掉落」→ 隐含永久声称\n"
                    "   - 夸大比较：如「比同类强50倍」→ 需要数据支撑，无数据则标记\n"
                    "   - 结果保证暗示：如「用完立刻见效」→ 隐含疗效保证\n"
                    "   - 上述情形以 rule_id='implicit_claim' 记录，confidence 相应降低\n\n"
                    f"【知识库】\n{kb_text}"
                ),
                model_role="text",
            ),
            ExpertSpec(
                name="qualification",
                description="资质类目专家：判断商品类目是否需要特定资质、是否缺证、是否类目错放（如保健品缺蓝帽子、械字号当普通化妆品卖）",
                system_prompt=(
                    "你是电商类目资质审核专家。依据下方知识库的 category_qualifications，"
                    "结合素材声称的商品类目与功效，判断是否存在资质问题：\n\n"
                    "判定要点：\n"
                    "1. 从文案/图片推断商品真实类目（如宣称'抗幽门螺杆菌'实为医疗功效）。\n"
                    "2. 对照该类目所需资质，判断是否缺失或类目错放。\n"
                    "3. 注意'打擦边'：用普通食品类目卖保健功效、用妆字号宣称特妆功效。\n"
                    "4. 无法确认商家是否持证时，降低 confidence、标注需核验证照。\n"
                    "5. 每条问题给出：规则 id（用 medical_terms_on_normal_goods 或自拟）、"
                    "证据、缺失的资质、整改建议。\n"
                    "6. suggestion 字段必须是可直接替换的改写方案，而非泛泛建议："
                    "引用 evidence 中的具体违规词句，给出至少一个可直接粘贴使用的替换文案；"
                    "参考知识库 remediation_templates，但必须结合当前商品语境生成具体版本。\n\n"
                    f"【知识库】\n{kb_text}"
                ),
                model_role="text",
            ),
            ExpertSpec(
                name="cross_modal",
                description="跨模态一致性专家：识别图、文单看都合规、但组合起来才违规的隐性违规（如豪车图+'月入过万'文案暗示暴富）",
                system_prompt=(
                    "你是跨模态一致性审核专家。重点不是单看文案或单看图，而是判断"
                    "【图 + 文案组合】是否产生引人误解或违规的暗示。\n\n"
                    "判定要点：\n"
                    "1. 图文是否暗示虚假收入/暴富（豪车、豪宅、成捆现金 + '轻松''自由''躺赚'）。\n"
                    "2. 图文是否暗示医疗功效（使用前后对比脸 + 普通护肤品文案）。\n"
                    "3. 是否存在违规导流（二维码/微信号图 + '加主页''站外更优惠'）。\n"
                    "4. 图文不符 / 图文擦边引流（暴露画面 + 无关商品）。\n"
                    "5. 单模态合规、仅组合才违规的，明确说明'组合后'的违规逻辑。\n"
                    "6. 每条给出：规则 id（用 false_income_inducement 等或自拟）、"
                    "图文证据、违规逻辑、整改建议。\n"
                    "7. suggestion 字段必须是可直接替换的改写方案，而非泛泛建议："
                    "引用 evidence 中的具体违规词句，给出至少一个可直接粘贴使用的替换文案；"
                    "参考知识库 remediation_templates，但必须结合当前图文组合语境生成具体版本。\n\n"
                    f"【知识库】\n{kb_text}"
                ),
                model_role="text",
            ),
        ]
