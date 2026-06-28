"""
人工审批闸门（编排器主导流程用）

引擎路由到 NEEDS_HUMAN（或命中高风险规则）时，调用 ApprovalHandler 让人工裁决：
  - APPROVE → 确认违规，维持拦截
  - REJECT  → 判定为误报，放行

审批处理器可插拔：CLI 交互版（真人）/ 自动版（测试、批量回归）。
裁决的应用 `apply_decision` 是纯函数，离线可测。
"""

from __future__ import annotations

from typing import Protocol

from core.schemas import ReviewOutcome


class ApprovalHandler(Protocol):
    def decide(self, outcome: ReviewOutcome) -> str:
        """返回 'APPROVE'（确认违规）或 'REJECT'（误报放行）。"""
        ...


class AutoApprovalHandler:
    """非交互处理器：固定返回某裁决。用于测试 / 批量回归。"""

    def __init__(self, decision: str = "APPROVE"):
        self.decision = decision

    def decide(self, outcome: ReviewOutcome) -> str:
        return self.decision


class CLIApprovalHandler:
    """命令行交互处理器：展示违规与推理链，等待真人输入。"""

    def decide(self, outcome: ReviewOutcome) -> str:
        print("\n" + "=" * 56)
        print("⚠️  需人工复核（置信度低于阈值或高风险）")
        print("=" * 56)
        print(f"初判: {outcome.final_verdict}  置信度: {outcome.confidence}")
        print("\n违规项:")
        for v in outcome.violations:
            print(f"  - [{v.get('expert')}] {v.get('rule_name', v.get('rule_id'))}: "
                  f"{v.get('evidence', '')} → {v.get('suggestion', '')}")
        print("\n推理链:")
        for step in outcome.reasoning_chain:
            print(f"  {step}")
        print("-" * 56)

        while True:
            ans = input("裁决 [APPROVE=确认违规 / REJECT=误报放行]: ").strip().upper()
            if ans in ("APPROVE", "REJECT"):
                return ans
            print("请输入 APPROVE 或 REJECT")


def apply_decision(outcome: ReviewOutcome, decision: str) -> ReviewOutcome:
    """把人工裁决应用到结论上（纯函数，离线可测）。"""
    outcome.reasoning_chain.append(f"[人工裁决] {decision}")
    outcome.needs_human = False
    if decision == "APPROVE":
        outcome.final_verdict = "VIOLATION"
    elif decision == "REJECT":
        outcome.final_verdict = "PASS"
        outcome.reasoning_chain.append("[人工裁决] 判定为误报，已放行")
    return outcome
