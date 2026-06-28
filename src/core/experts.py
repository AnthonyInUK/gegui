"""
专家 Agent 运行器（场景无关）

从 Scene 提供的 ExpertSpec 构建专家 agent，喂入「文案 + 看图结果」，
产出场景定义的结构化结论（output_schema）。

策略：prompt 写死 JSON 形状 + 容错解析（见 jsonutil），不依赖 SDK 的
structured_output schema 强约束 —— 对 Qwen / DeepSeek 等国产接口更稳。
"""

from __future__ import annotations

from typing import Type

from pydantic import BaseModel
from strands import Agent

from core.jsonutil import parse_into, pydantic_field_hint
from core.model_provider import build_model
from core.vision_agent import tokens_of
from scenes.base import ExpertSpec


def build_expert(spec: ExpertSpec) -> Agent:
    """按 ExpertSpec 构建一个专家 agent。"""
    return Agent(
        model=build_model(spec.model_role),
        system_prompt=spec.system_prompt,
        tools=spec.tools or None,  # 空列表会被 Qwen 拒（tools 不能为 []），传 None 省略该字段
        callback_handler=None,     # 关掉流式打印，避免污染输出
    )


def build_corrections_hint(samples: list[dict], limit: int = 3) -> str:
    """把人工纠正样本渲染成 few-shot 提示（反馈闭环：人工修正 → 喂回模型）。"""
    if not samples:
        return ""
    lines = ["\n【历史人工纠正案例（请引以为戒，避免重犯同类误判）】"]
    for s in samples[:limit]:
        lines.append(
            f"- 素材「{s.get('material_text', '')[:40]}」：模型曾判 {s.get('final_verdict')}，"
            f"人工裁定为 {s.get('human_decision')}。原因：{s.get('human_notes') or '（无备注）'}"
        )
    return "\n".join(lines)


def _expert_prompt(
    material_text: str,
    vision_context: str,
    corrections_hint: str,
    output_model: Type[BaseModel],
    extra_context: str = "",
) -> str:
    return (
        f"【商品文案】\n{material_text or '（无）'}\n\n"
        f"{vision_context}\n"
        f"{corrections_hint}\n"
        f"{extra_context}\n\n"
        "请审核以上素材。注意：每条 violation 的 suggestion 字段必须给出可直接替换的改写文案（非泛泛建议）。"
        "严格只输出如下 JSON（字段名必须完全一致，含 json 字样）：\n"
        f"{pydantic_field_hint(output_model)}"
    )


def _text_of(result) -> str:
    return result.message["content"][0].get("text", "") if result.message.get("content") else ""


def _finalize(text: str, tokens: int, output_model: Type[BaseModel]) -> tuple[BaseModel, int]:
    """解析专家输出；失败则兜底为 NEEDS_HUMAN。同步/异步共用。"""
    parsed = parse_into(text, output_model)
    if parsed is not None:
        return parsed, tokens

    fallback = {}
    fields = output_model.model_fields
    if "verdict" in fields:
        fallback["verdict"] = "NEEDS_HUMAN"
    if "confidence" in fields:
        fallback["confidence"] = 0.0
    if "summary" in fields:
        fallback["summary"] = f"结构化解析失败，转人工。原始输出：{text[:200]}"
    try:
        return output_model.model_validate(fallback), tokens
    except Exception:
        raise ValueError(f"专家输出无法解析为 {output_model.__name__}: {text[:300]}")


def run_expert(
    spec: ExpertSpec,
    material_text: str,
    vision_context: str,
    output_model: Type[BaseModel],
    corrections_hint: str = "",
    extra_context: str = "",
) -> tuple[BaseModel, int]:
    """同步运行一个专家，返回 (output_model 实例, tokens)。"""
    agent = build_expert(spec)
    prompt = _expert_prompt(material_text, vision_context, corrections_hint, output_model, extra_context)
    result = agent(prompt)
    return _finalize(_text_of(result), tokens_of(result), output_model)


async def run_expert_async(
    spec: ExpertSpec,
    material_text: str,
    vision_context: str,
    output_model: Type[BaseModel],
    corrections_hint: str = "",
    extra_context: str = "",
) -> tuple[str, BaseModel, int]:
    """异步运行一个专家（供并行扇出）。返回 (专家名, 结论, tokens)。"""
    agent = build_expert(spec)
    prompt = _expert_prompt(material_text, vision_context, corrections_hint, output_model, extra_context)
    result = await agent.invoke_async(prompt)
    parsed, tokens = _finalize(_text_of(result), tokens_of(result), output_model)
    return spec.name, parsed, tokens
