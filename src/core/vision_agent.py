"""
看图 Agent（通用，场景无关）

职责单一：图片 → 结构化文字（OCR + 画面描述 + 可疑细节）。
- 用 VL 模型（Qwen-VL）
- 不挂任何工具：VL 模型 tool-calling 弱，只让它"看"，扬长避短
- 输出一次性供下游所有文本专家复用，图只读一次（省 token）

JSON 解析做成纯函数 `parse_extraction`，无需 API key 即可单元测试。
"""

from __future__ import annotations

from strands import Agent

from core.images import build_user_content
from core.jsonutil import extract_json_obj
from core.model_provider import build_model
from core.schemas import VisionExtraction

_DEFAULT_VISION_PROMPT = (
    "你是图片视觉提取器。请仔细查看图片，只做客观描述、不做任何合规判断，"
    "严格输出如下 JSON（不要额外文字）：\n"
    "{\n"
    '  "ocr_text": ["图中每一处可见文字，逐条；包括小字、水印、做进画面里的字"],\n'
    '  "visual_elements": "画面主要元素与场景的客观描述",\n'
    '  "suspicious_details": ["任何规避检测的迹象，如拆字/谐音/文字嵌图等；没有则留空"]\n'
    "}"
)


def parse_extraction(text: str) -> VisionExtraction:
    """从模型返回文本中稳健地解析出 VisionExtraction。

    兼容三种情况：纯 JSON、```json 代码块包裹、JSON 前后带解释文字。
    解析失败时退化为：把全部文本塞进 visual_elements，保证不崩。
    """
    data = extract_json_obj(text)
    if data is not None:
        return VisionExtraction(
            ocr_text=_as_list(data.get("ocr_text")),
            visual_elements=str(data.get("visual_elements") or ""),
            suspicious_details=_as_list(data.get("suspicious_details")),
        )

    # 兜底：解析失败不丢信息
    return VisionExtraction(visual_elements=text.strip())


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)]


def build_vision_agent(vision_prompt: str | None = None) -> Agent:
    """构建看图 agent（VL 模型，无工具）。"""
    return Agent(
        model=build_model("vision"),
        system_prompt=vision_prompt or _DEFAULT_VISION_PROMPT,
        tools=None,  # 看图 agent 不挂工具（空列表会被 Qwen 拒，用 None）
        callback_handler=None,
    )


def tokens_of(result) -> int:
    """从 Strands AgentResult 提取累计 token 数（拿不到则 0）。"""
    try:
        return int(result.metrics.accumulated_usage.get("totalTokens", 0))
    except (AttributeError, TypeError):
        return 0


def extract_from_images(
    image_paths: list[str],
    vision_prompt: str | None = None,
    instruction: str = "请提取这张图片的内容。",
) -> tuple[VisionExtraction, int]:
    """看图主入口：图片 → (VisionExtraction, tokens)。

    Args:
        image_paths: 本地图片路径列表
        vision_prompt: 场景定制的看图 system prompt（来自 Scene.vision_prompt()）
        instruction: 随图发送的用户指令
    """
    agent = build_vision_agent(vision_prompt)
    content = build_user_content(instruction, image_paths)
    result = agent(content)
    text = result.message["content"][0].get("text", "") if result.message.get("content") else ""
    return parse_extraction(text), tokens_of(result)
