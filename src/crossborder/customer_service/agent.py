"""Controlled customer service reply drafting with Action Gate integration."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from crossborder.action_gate import evaluate_action_gate
from crossborder.schemas import (
    ActionGateRequest,
    CustomerServiceRequest,
    CustomerServiceResult,
)


INTENT_KEYWORDS = {
    "refund_request": {"refund", "money back", "chargeback", "return my money"},
    "return_request": {"return", "send it back", "exchange"},
    "delivery_delay": {"late", "delay", "delayed", "not arrived", "where is", "tracking"},
    "product_issue": {"broken", "defective", "doesn't work", "not working", "damaged", "missing part"},
    "cancel_request": {"cancel", "cancellation"},
    "negative_feedback": {"bad review", "one star", "complaint", "report", "scam"},
}

NEGATIVE_WORDS = {"angry", "upset", "disappointed", "terrible", "bad", "horrible", "refund", "broken", "late", "complaint"}
POSITIVE_WORDS = {"thanks", "thank you", "great", "love", "good"}


def respond_to_customer(req: CustomerServiceRequest) -> CustomerServiceResult:
    intent = _classify_intent(req.buyer_message)
    sentiment = _sentiment(req.buyer_message)
    urgency = _urgency(intent, sentiment, req)
    issues = _issues(req, intent, urgency)
    suggested_actions = _suggest_actions(req, intent)
    gated_actions = _gate_actions(req, suggested_actions, urgency)
    draft_reply = _draft_reply(req, intent, sentiment)
    human_review = urgency == "high" or any(action["human_review_required"] for action in gated_actions)
    decision = "requires_human_review" if human_review else "pass"

    return CustomerServiceResult(
        decision=decision,
        intent=intent,
        sentiment=sentiment,
        urgency=urgency,
        draft_reply=draft_reply,
        issues=issues,
        suggested_actions=suggested_actions,
        gated_actions=gated_actions,
        human_review_required=human_review,
        audit={
            "response_id": f"cs_{uuid4().hex[:12]}",
            "workflow_id": req.workflow_id,
            "tool": "crossborder.customer_service.respond",
            "runtime": "deterministic_intent_rules",
            "input_hash": _hash(req),
            "created_at": datetime.now(UTC).isoformat(),
            "version": "customer-service-v1",
        },
    )


def _classify_intent(message: str) -> str:
    text = message.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return intent
    return "general_question"


def _sentiment(message: str) -> str:
    text = message.lower()
    negative = sum(1 for word in NEGATIVE_WORDS if word in text)
    positive = sum(1 for word in POSITIVE_WORDS if word in text)
    if negative > positive:
        return "negative"
    if positive > negative:
        return "positive"
    return "neutral"


def _urgency(intent: str, sentiment: str, req: CustomerServiceRequest) -> str:
    if intent in {"refund_request", "negative_feedback"}:
        return "high"
    if sentiment == "negative" and intent in {"delivery_delay", "product_issue"}:
        return "high"
    if intent in {"delivery_delay", "product_issue", "return_request", "cancel_request"}:
        return "medium"
    return "low"


def _issues(req: CustomerServiceRequest, intent: str, urgency: str) -> list[dict]:
    issues = []
    if intent in {"refund_request", "return_request"} and req.days_since_delivery is not None:
        if req.days_since_delivery > req.return_window_days:
            issues.append(
                {
                    "category": "outside_return_window",
                    "severity": "medium",
                    "reason": "Buyer request may be outside configured return window.",
                    "suggestion": "Route to human review before promising refund or return approval.",
                }
            )
    if urgency == "high":
        issues.append(
            {
                "category": "high_touch_customer_case",
                "severity": "high",
                "reason": "Message indicates refund, complaint, negative sentiment, or product failure risk.",
                "suggestion": "Use draft reply only; route monetary or delivery commitments through Action Gate.",
            }
        )
    return issues


def _suggest_actions(req: CustomerServiceRequest, intent: str) -> list[dict]:
    actions = [
        {
            "action_type": "send_reply",
            "reason": "Send or queue the drafted customer service response.",
            "requires_human_review": intent in {"refund_request", "negative_feedback", "product_issue"},
        }
    ]
    if intent == "refund_request":
        actions.append(
            {
                "action_type": "refund_order",
                "reason": "Buyer explicitly requested a refund.",
                "requires_human_review": True,
            }
        )
    elif intent == "return_request":
        actions.append(
            {
                "action_type": "request_order_info",
                "reason": "Collect return reason/order details before any refund commitment.",
                "requires_human_review": False,
            }
        )
    elif intent == "delivery_delay":
        actions.append(
            {
                "action_type": "promise_delivery_date",
                "reason": "Delivery timing commitments must be verified before sending.",
                "requires_human_review": True,
            }
        )
    elif intent == "product_issue":
        actions.append(
            {
                "action_type": "compensate_buyer",
                "reason": "Product issue may require replacement, refund, or compensation.",
                "requires_human_review": True,
            }
        )
    return actions


def _gate_actions(req: CustomerServiceRequest, suggested_actions: list[dict], urgency: str) -> list[dict]:
    permissions = list(req.metadata.get("permissions") or [])
    gated = []
    for action in suggested_actions:
        risk_level = "high" if action.get("requires_human_review") or urgency == "high" else "low"
        gate = evaluate_action_gate(
            ActionGateRequest(
                action_type=action["action_type"],
                actor_agent="CustomerServiceAgent",
                workflow_id=req.workflow_id,
                seller_id=req.seller_id,
                platform=req.platform,
                market=req.market,
                payload={"order_id": req.order_id, **action},
                reason=action.get("reason", ""),
                risk_level=risk_level,
                permissions=permissions,
            )
        )
        gated.append(
            {
                "action_type": action["action_type"],
                "suggested_action": action,
                "gate_decision": gate.decision.value,
                "allowed": gate.allowed,
                "human_review_required": gate.human_review_required,
                "reasons": gate.reasons,
                "required_permissions": gate.required_permissions,
                "gate_id": gate.audit.get("gate_id", ""),
            }
        )
    return gated


def _draft_reply(req: CustomerServiceRequest, intent: str, sentiment: str) -> str:
    greeting = "Hello, thank you for contacting us."
    product = f" about {req.product_title}" if req.product_title else ""
    if intent == "refund_request":
        return (
            f"{greeting} I am sorry to hear there is an issue{product}. "
            "We have received your refund request and will review the order details according to the marketplace policy. "
            "Please do not send the item back until we confirm the next step."
        )
    if intent == "return_request":
        return (
            f"{greeting} We can help review your return request{product}. "
            "Please share the order details and reason for return so we can check the applicable return options."
        )
    if intent == "delivery_delay":
        return (
            f"{greeting} I am sorry the delivery is not meeting expectations. "
            "We will check the latest tracking information and follow up with the next available update."
        )
    if intent == "product_issue":
        return (
            f"{greeting} I am sorry the product did not arrive or perform as expected. "
            "Please share a short description and photo of the issue so we can review the best resolution."
        )
    if intent == "cancel_request":
        return (
            f"{greeting} We received your cancellation request. "
            "We will check whether the order can still be cancelled before shipment and update you shortly."
        )
    if intent == "negative_feedback":
        return (
            f"{greeting} I am sorry for the frustrating experience. "
            "We take this seriously and will review the order details before proposing a resolution."
        )
    return (
        f"{greeting} We received your message and will help with your question{product}. "
        "Please share any additional order details if available."
    )


def _hash(req: CustomerServiceRequest) -> str:
    payload = json.dumps(req.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python src/crossborder/customer_service/agent.py <request.json>")
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    result = respond_to_customer(CustomerServiceRequest.model_validate(payload))
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
