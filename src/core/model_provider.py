"""
Model provider 工厂 —— 按角色选模型

审核引擎用两类模型：
  - role="vision"  看图（VL 模型，读 OCR + 画面）
  - role="text"    专家推理（文本模型，tool-calling 强，做法条比对/调工具）

按环境变量自动挑后端，切换只改 .env，业务代码不动：
  DASHSCOPE_API_KEY  → 通义千问 Qwen（vision=qwen-vl-max / text=qwen-max）★ 首选
  DEEPSEEK_API_KEY   → DeepSeek（仅 text，无视觉）
  ANTHROPIC_API_KEY  → Claude（text + vision 都行）
  都没有             → AWS Bedrock 默认（需 AWS 凭证）
"""

import os

DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _no_empty_tools_model_cls():
    """OpenAIModel 子类：请求里 tools 为空时删掉该字段。

    Strands 总会序列化 `tools: []`，但 Qwen（qwen-max）等端点拒绝空 tools 数组
    （报 '[] is too short - tools'）。无工具的 agent（看图/专家）需要去掉它。
    """
    from strands.models.openai import OpenAIModel

    class _OpenAINoEmptyTools(OpenAIModel):
        def format_request(self, *args, **kwargs):
            req = super().format_request(*args, **kwargs)
            if not req.get("tools"):
                req.pop("tools", None)
                req.pop("tool_choice", None)
            return req

    return _OpenAINoEmptyTools


def _qwen(api_key: str, model_id: str, vision: bool):
    params = {"temperature": 0.2}
    if not vision:
        params["max_tokens"] = 4096
    return _no_empty_tools_model_cls()(
        client_args={"api_key": api_key, "base_url": DASHSCOPE_BASE_URL},
        model_id=model_id,
        params=params,
    )


def _deepseek(api_key: str):
    return _no_empty_tools_model_cls()(
        client_args={
            "api_key": api_key,
            "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        },
        model_id=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        params={"temperature": 0.2},
    )


def _anthropic(model_id: str):
    from strands.models.anthropic import AnthropicModel

    return AnthropicModel(
        client_args={"api_key": os.getenv("ANTHROPIC_API_KEY")},
        model_id=model_id,
        params={"max_tokens": 4096, "temperature": 0.2},
    )


def build_model(role: str = "text"):
    """返回指定角色的 Strands model 实例（None = 退回 Bedrock 默认）。

    Args:
        role: "vision"（看图）或 "text"（推理）。
    """
    dashscope = os.getenv("DASHSCOPE_API_KEY")
    deepseek = os.getenv("DEEPSEEK_API_KEY")
    anthropic = os.getenv("ANTHROPIC_API_KEY")

    if role == "vision":
        # 视觉：Qwen-VL > Claude > Bedrock。DeepSeek 无视觉能力，跳过。
        if dashscope:
            return _qwen(dashscope, os.getenv("QWEN_VL_MODEL", "qwen-vl-max"), vision=True)
        if anthropic:
            return _anthropic(os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8"))
        return None  # Bedrock 上的 Claude 也支持多模态

    # text：Qwen-Max > DeepSeek > Claude > Bedrock
    if dashscope:
        return _qwen(dashscope, os.getenv("QWEN_TEXT_MODEL", "qwen-max"), vision=False)
    if deepseek:
        return _deepseek(deepseek)
    if anthropic:
        return _anthropic(os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8"))
    return None


def active_provider_name(role: str = "text") -> str:
    dashscope = os.getenv("DASHSCOPE_API_KEY")
    if role == "vision":
        if dashscope:
            return f"Qwen-VL ({os.getenv('QWEN_VL_MODEL', 'qwen-vl-max')})"
        if os.getenv("ANTHROPIC_API_KEY"):
            return f"Anthropic ({os.getenv('ANTHROPIC_MODEL', 'claude-opus-4-8')})"
        return "AWS Bedrock (default, multimodal)"
    # text
    if dashscope:
        return f"Qwen ({os.getenv('QWEN_TEXT_MODEL', 'qwen-max')})"
    if os.getenv("DEEPSEEK_API_KEY"):
        return f"DeepSeek ({os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')})"
    if os.getenv("ANTHROPIC_API_KEY"):
        return f"Anthropic ({os.getenv('ANTHROPIC_MODEL', 'claude-opus-4-8')})"
    return "AWS Bedrock (default)"
