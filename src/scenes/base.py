"""
Scene 抽象接口 —— "可插拔场景" 的核心契约

引擎核心（core/）完全场景无关。一个具体业务（电商广告法、商家证照核验……）
只需实现一个 Scene 子类，向引擎提供四样东西：
  1. knowledge_base   该场景的规则 / 法条
  2. expert_agents    该场景的专家 agent 列表
  3. prescreen        初筛粗筛规则（便宜、快速、高召回）
  4. output_schema    该场景的结构化结论模型

切换业务 = 换一个 Scene 实例，引擎其余部分一行不改。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel


@dataclass
class ExpertSpec:
    """一个专家 agent 的声明。引擎据此构建专家 agent。"""

    name: str                       # 专家标识，如 "ad_law" / "qualification"
    description: str                # 该专家负责什么（用于编排时让主 agent 选择）
    system_prompt: str              # 该专家的判定规则 prompt（通常引用 knowledge_base）
    tools: list[Callable] = field(default_factory=list)  # 该专家可用的工具
    model_role: str = "text"        # "text"=文本推理模型 / "vision"=视觉模型


class PrescreenResult(BaseModel):
    """初筛层输出：决定一条素材是否需要进入 agent 复审。"""

    needs_review: bool              # True=进 agent 复审；False=明确放行/拦截
    reason: str                     # 粗筛判断依据
    hits: list[str] = []            # 命中的粗筛规则（如黑名单词）


class Scene(ABC):
    """一个可插拔的审核场景。"""

    #: 场景标识，如 "ecommerce_ad"
    scene_id: str = "base"

    #: 场景中文名，用于展示
    display_name: str = "未命名场景"

    @property
    @abstractmethod
    def knowledge_base(self) -> dict[str, Any]:
        """该场景的结构化规则 / 法条知识库。"""
        ...

    @abstractmethod
    def expert_specs(self) -> list[ExpertSpec]:
        """该场景的专家 agent 声明列表（广告法 / 资质 / 跨模态……）。"""
        ...

    @abstractmethod
    def prescreen(self, material: "ReviewMaterial") -> PrescreenResult:
        """初筛层：便宜规则粗筛，决定是否进入 agent 复审。"""
        ...

    @property
    @abstractmethod
    def output_schema(self) -> type[BaseModel]:
        """该场景的结构化审核结论模型（pydantic）。"""
        ...

    def vision_prompt(self) -> str:
        """看图 agent 的场景定制提示（看图时重点关注什么）。

        默认通用提示；场景可覆盖以强调本场景关心的视觉要素
        （如电商关心"图内文字"，证照关心"证件字段"）。
        """
        return (
            "请仔细查看图片，输出：①图中所有可见文字（逐字 OCR，包括小字、水印、"
            "做进画面里的文字）；②画面主要元素与场景描述；③任何异常或可疑细节。"
            "只做客观描述，不做合规判断。"
        )


@dataclass
class ReviewMaterial:
    """一条待审素材（场景无关的统一输入）。"""

    text: str = ""                          # 文案 / 标题 / 描述
    image_paths: list[str] = field(default_factory=list)  # 图片本地路径
    metadata: dict[str, Any] = field(default_factory=dict)  # 类目、商家ID 等场景上下文
