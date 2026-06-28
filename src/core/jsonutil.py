"""
稳健 JSON 解析工具

国产 OpenAI 兼容接口（Qwen / DeepSeek）的 structured_output 不强制 pydantic
字段名，模型常自创字段。因此引擎统一策略：prompt 里写死 JSON 形状 + 这里容错解析，
而非依赖 SDK 的 schema 强约束。
"""

from __future__ import annotations

import json
import re
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def extract_json_obj(text: str) -> dict | None:
    """从模型返回文本中提取第一个 JSON 对象。

    兼容：纯 JSON、```json 围栏包裹、JSON 前后带解释文字。失败返回 None。
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        candidate = text[start : end + 1] if start != -1 and end > start else None
    if not candidate:
        return None
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def pydantic_field_hint(model: Type[BaseModel]) -> str:
    """把 pydantic 模型渲染成给 LLM 的「字段说明」，引导其输出正确字段名。"""
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})

    def render(props: dict, indent: int = 0) -> list[str]:
        lines = []
        pad = "  " * indent
        for name, spec in props.items():
            desc = spec.get("description", "")
            # 处理嵌套对象数组（如 violations: [Violation]）
            ref = spec.get("items", {}).get("$ref") or spec.get("$ref")
            if ref:
                sub = defs.get(ref.split("/")[-1], {})
                lines.append(f'{pad}"{name}": [ {{   // {desc}')
                lines += render(sub.get("properties", {}), indent + 1)
                lines.append(f"{pad}}} ]")
            else:
                lines.append(f'{pad}"{name}": ...,   // {desc}')
        return lines

    return "{\n" + "\n".join(render(schema.get("properties", {}), 1)) + "\n}"


def parse_into(text: str, model: Type[T]) -> T | None:
    """解析文本为指定 pydantic 模型实例；失败返回 None。"""
    obj = extract_json_obj(text)
    if obj is None:
        return None
    try:
        return model.model_validate(obj)
    except Exception:
        return None
