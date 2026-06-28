"""
Strands Hook：高风险工具守卫（agent 自主调工具的场景用）

与 approval.py 的区别：
  - approval.py  = 编排器主导流程的确定性审批闸门（当前 MVP 主路径）
  - hooks.py     = agent **自主**决定调用敏感工具时，用 Strands 原生 hook 拦截

典型用途：某专家 agent 被赋予「写回知识库 / 提交工单」等危险工具，
模型自行决定调用时，BeforeToolCallEvent 触发 interrupt() 暂停，等人工放行。
这是 Strands human-in-loop 一等公民机制的真实落地。
"""

from __future__ import annotations

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry


class HighRiskToolGuard(HookProvider):
    """守卫指定的高风险工具：调用前触发人工审批 interrupt。"""

    def __init__(self, guarded_tools: set[str] | None = None):
        # 默认守卫这些"会产生外部副作用"的工具名
        self.guarded_tools = guarded_tools or {
            "submit_review_ticket",
            "write_knowledge_base",
            "auto_takedown",
        }

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._guard)

    def _guard(self, event: BeforeToolCallEvent) -> None:
        tool_name = event.tool_use["name"]
        if tool_name not in self.guarded_tools:
            return
        # 触发中断：抛 InterruptException，冒泡到调用方等待人工放行
        approval = event.interrupt(
            name=f"approve_{tool_name}",
            reason=f"高风险工具 `{tool_name}` 调用前需人工审批，输入: "
            f"{event.tool_use.get('input')}",
        )
        if approval != "APPROVE":
            event.cancel_tool = f"人工未批准调用 {tool_name}（裁决: {approval}）"
