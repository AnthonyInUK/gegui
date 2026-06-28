"""
冲突触发式一轮辩论（真正的 agent 间交流）

设计哲学：
  - 独立 case → 并行扇出（asyncio），专家互不通信，省成本。
  - **冲突 case** → 才触发一轮辩论：让分歧的专家**互相看到对方的判断与理由**，
    各自重新审视、可坚持可修正。按"分歧程度"决定要不要让 agent 对话。

只辩一轮、只在冲突时辩 → 把"多 agent 通信"的成本压到少数 case。
冲突检测 detect_conflict 与互评渲染 peer_summary 是纯函数，离线可测。
"""

from __future__ import annotations

from pydantic import BaseModel

from core.experts import run_expert
from scenes.base import Scene


def _violations_of(res) -> list:
    return getattr(res, "violations", []) or []


def detect_conflict(expert_results: list[tuple[str, BaseModel]]) -> tuple[bool, str]:
    """检测专家间是否存在实质分歧（纯函数）。

    分歧 = 有专家报了违规、同时有专家判无违规。这种"一个说违规一个说没事"
    正是最该让他们对话的情形。
    """
    flagged = [n for n, r in expert_results if _violations_of(r)]
    clean = [n for n, r in expert_results if not _violations_of(r)]
    if flagged and clean:
        return True, f"分歧：{flagged} 判违规，{clean} 判无违规"
    return False, "专家判定一致，无需辩论"


def peer_summary(expert_results: list[tuple[str, BaseModel]], exclude: str) -> str:
    """把其他专家的判断与理由渲染成"对方意见"，供某专家辩论时参考。"""
    lines = []
    for name, res in expert_results:
        if name == exclude:
            continue
        verdict = getattr(res, "verdict", "?")
        conf = getattr(res, "confidence", "?")
        viols = _violations_of(res)
        if viols:
            detail = "；".join(
                f"{(v.rule_name if isinstance(v, BaseModel) else v.get('rule_name', ''))}"
                f"（证据：{(v.evidence if isinstance(v, BaseModel) else v.get('evidence', ''))}）"
                for v in viols
            )
        else:
            detail = "未发现违规"
        lines.append(f"- 专家[{name}] 判定 {verdict}(置信{conf})：{detail}")
    return "\n".join(lines)


def run_debate(
    scene: Scene,
    expert_results: list[tuple[str, BaseModel]],
    material_text: str,
    vision_context: str,
) -> tuple[list[tuple[str, BaseModel]], int]:
    """触发一轮辩论：每个专家看到同伴意见后重新裁决（串行，仅冲突时调用）。"""
    revised: list[tuple[str, BaseModel]] = []
    tokens = 0
    specs = {s.name: s for s in scene.expert_specs()}
    for name, _ in expert_results:
        spec = specs.get(name)
        if spec is None:
            continue
        peers = peer_summary(expert_results, exclude=name)
        debate_ctx = (
            "【其他专家的意见（辩论）】\n"
            f"{peers}\n"
            "请重新审视你的判断：若被对方说服可修正你的结论，"
            "若坚持原判请基于法条给出更充分的理由。输出你的最终结论。"
        )
        res, t = run_expert(
            spec, material_text, vision_context, scene.output_schema, extra_context=debate_ctx
        )
        revised.append((name, res))
        tokens += t
    return revised, tokens
