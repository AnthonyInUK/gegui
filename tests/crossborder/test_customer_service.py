from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from crossborder.customer_service.agent import respond_to_customer  # noqa: E402
from crossborder.schemas import CustomerServiceRequest  # noqa: E402


class CustomerServiceAgentTest(unittest.TestCase):
    def test_refund_request_drafts_reply_and_gates_refund(self):
        req = CustomerServiceRequest.model_validate(
            {
                "platform": "amazon",
                "market": "US",
                "workflow_id": "wf_customer_refund_test",
                "seller_id": "seller_demo",
                "order_id": "ORDER-1",
                "product_title": "Silicone Cable Organizer",
                "buyer_message": "I am very disappointed. The adhesive falls off and I want a refund.",
                "days_since_delivery": 8,
                "metadata": {"permissions": ["customer_message"]},
            }
        )

        result = respond_to_customer(req)

        self.assertEqual(result.intent, "refund_request")
        self.assertEqual(result.decision, "requires_human_review")
        self.assertIn("refund request", result.draft_reply.lower())
        self.assertTrue(any(action["action_type"] == "refund_order" for action in result.gated_actions))
        self.assertTrue(any(action["gate_decision"] == "requires_human_review" for action in result.gated_actions))

    def test_general_question_can_send_reply_with_permission(self):
        req = CustomerServiceRequest.model_validate(
            {
                "buyer_message": "Hi, does this work on a small desk?",
                "product_title": "Silicone Cable Organizer",
                "metadata": {"permissions": ["customer_message"]},
            }
        )

        result = respond_to_customer(req)

        self.assertEqual(result.intent, "general_question")
        self.assertEqual(result.decision, "pass")
        self.assertTrue(result.gated_actions[0]["allowed"])

    def test_delivery_delay_does_not_auto_promise_date(self):
        req = CustomerServiceRequest.model_validate(
            {
                "buyer_message": "Where is my package? It is late and I am upset.",
                "delivery_status": "delayed",
                "metadata": {"permissions": ["customer_message"]},
            }
        )

        result = respond_to_customer(req)

        self.assertEqual(result.intent, "delivery_delay")
        self.assertTrue(result.human_review_required)
        self.assertTrue(any(action["action_type"] == "promise_delivery_date" for action in result.gated_actions))
        self.assertFalse(any(action["allowed"] for action in result.gated_actions if action["action_type"] == "promise_delivery_date"))


if __name__ == "__main__":
    unittest.main()
