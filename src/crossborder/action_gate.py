"""Permission gate for high-risk ecommerce workflow actions."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from uuid import uuid4

from crossborder.schemas import ActionDecision, ActionGateRequest, ActionGateResult


HIGH_RISK_ACTIONS = {
    "publish_listing",
    "delete_listing",
    "change_price",
    "increase_budget",
    "refund_order",
    "compensate_buyer",
    "promise_delivery_date",
    "submit_appeal",
}

BLOCKED_ACTIONS = {
    "delete_listing",
    "submit_appeal",
}

ACTION_PERMISSIONS = {
    "request_order_info": [],
    "send_reply": ["customer_message"],
    "publish_listing": ["publish"],
    "change_price": ["pricing"],
    "increase_budget": ["ads_budget"],
    "pause_campaign": ["ads_manage"],
    "add_negative_keyword": ["ads_manage"],
    "monitor_campaign": [],
    "refund_order": ["refund"],
    "compensate_buyer": ["compensation"],
    "promise_delivery_date": ["customer_commitment"],
    "submit_appeal": ["appeal"],
    "delete_listing": ["admin"],
}


def evaluate_action_gate(req: ActionGateRequest) -> ActionGateResult:
    required = ACTION_PERMISSIONS.get(req.action_type, ["execute"])
    missing = [permission for permission in required if permission not in req.permissions]
    reasons: list[str] = []

    if req.action_type in BLOCKED_ACTIONS:
        reasons.append("This action is blocked for autonomous agents and must be handled by a workflow owner.")
        return _result(req, ActionDecision.blocked, required, reasons)

    if req.action_type in HIGH_RISK_ACTIONS:
        reasons.append("High-risk marketplace/customer action requires human approval.")

    if missing:
        reasons.append(f"Missing required permissions: {', '.join(missing)}.")

    if req.risk_level in {"high", "critical"}:
        reasons.append(f"Risk level is {req.risk_level}; route to human review.")

    if reasons:
        return _result(req, ActionDecision.requires_human_review, required, reasons)

    return _result(req, ActionDecision.allowed, required, ["Action allowed by workflow gate."])


def _result(
    req: ActionGateRequest,
    decision: ActionDecision,
    required_permissions: list[str],
    reasons: list[str],
) -> ActionGateResult:
    return ActionGateResult(
        decision=decision,
        action_type=req.action_type,
        allowed=decision == ActionDecision.allowed,
        human_review_required=decision == ActionDecision.requires_human_review,
        reasons=reasons,
        required_permissions=required_permissions,
        audit={
            "gate_id": f"gate_{uuid4().hex[:12]}",
            "workflow_id": req.workflow_id,
            "actor_agent": req.actor_agent,
            "input_hash": _hash(req),
            "created_at": datetime.now(UTC).isoformat(),
            "version": "action-gate-v1",
        },
    )


def _hash(req: ActionGateRequest) -> str:
    payload = json.dumps(req.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return sha256(payload.encode("utf-8")).hexdigest()
