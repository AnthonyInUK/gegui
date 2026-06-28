"""
引擎结构化数据模型（pydantic）

场景无关的通用模型放这里；场景专属的结论字段由各 Scene 的 output_schema 提供。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class VisionExtraction(BaseModel):
    """看图 agent 的结构化输出 —— 把图片转成下游专家可读的文字。

    刻意只做客观描述、不做合规判断：判断是文本专家 agent 的职责。
    图只在这一步读一次，下游 agent 复用这段文字，避免图片 token 重复消耗。
    """

    ocr_text: list[str] = Field(
        default_factory=list,
        description="图中所有可见文字，逐条列出（含小字、水印、做进画面里的字）",
    )
    visual_elements: str = Field(
        default="",
        description="画面主要元素与场景的客观描述",
    )
    suspicious_details: list[str] = Field(
        default_factory=list,
        description="任何异常/可疑细节（如文字被拆字、谐音、嵌入图片规避检测的迹象）",
    )

    def as_context(self) -> str:
        """渲染成给下游专家 agent 的纯文本上下文。"""
        lines = ["【图片视觉提取结果】"]
        if self.ocr_text:
            lines.append("图中文字：")
            lines += [f"  - {t}" for t in self.ocr_text]
        else:
            lines.append("图中文字：（未识别到文字）")
        lines.append(f"画面描述：{self.visual_elements or '（无）'}")
        if self.suspicious_details:
            lines.append("可疑细节：")
            lines += [f"  - {d}" for d in self.suspicious_details]
        return "\n".join(lines)


class ReviewOutcome(BaseModel):
    """引擎对一条素材的最终统一结论（场景无关）。

    各专家用场景的 output_schema 各自产出结论，引擎在此合并 + 路由成一份总结论，
    并保留完整 reasoning_chain 供审计。
    """

    final_verdict: str = Field(description="PASS / VIOLATION / NEEDS_HUMAN")
    confidence: float = Field(default=0.0, description="总置信度 0-1")
    needs_human: bool = Field(default=False, description="是否需人工复核")
    violations: list[dict] = Field(
        default_factory=list, description="合并后的违规项（含来自哪个专家）"
    )
    expert_results: list[dict] = Field(
        default_factory=list, description="各专家原始结论"
    )
    reasoning_chain: list[str] = Field(
        default_factory=list, description="完整推理链，供审计"
    )
    prescreen_reason: str = Field(default="", description="初筛判断依据")
    tokens: int = Field(default=0, description="本次审核累计 token 消耗")
    latency_ms: int = Field(default=0, description="本次审核耗时（毫秒）")
    from_cache: bool = Field(default=False, description="是否命中去重缓存")
