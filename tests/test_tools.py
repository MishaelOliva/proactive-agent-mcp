import unittest
from proactive_agent_mcp.tools.triage import poll_event_queue, push_event
from proactive_agent_mcp.tools.compliance import evaluate_document_compliance
from proactive_agent_mcp.tools.knowledge import query_rag_knowledge
from proactive_agent_mcp.tools.guardrails import (
    request_human_approval,
    verify_approval_token,
    track_cost_budget
)

class TestMCPTools(unittest.TestCase):
    def test_poll_event_queue(self):
        res = poll_event_queue(queue_name="test_q", max_items=2)
        self.assertIn("items", res)
        self.assertIn("total_unprocessed_found", res)
        self.assertTrue(len(res["items"]) <= 2)

    def test_compliance_valid_payload(self):
        valid_doc = {
            "employee_id": "EMP-9021",
            "serial_number": "PF-999-LTP",
            "department": "Engineering",
            "custody_date": "2026-09-24"
        }
        res = evaluate_document_compliance(valid_doc, schema_type="asset_handover")
        self.assertTrue(res["is_compliant"])
        self.assertEqual(res["triage_verdict"], "APPROVED_AUTO_PASS")
        self.assertEqual(len(res["missing_fields"]), 0)

    def test_compliance_missing_fields(self):
        invalid_doc = {
            "department": "IT Support"
        }
        res = evaluate_document_compliance(invalid_doc, schema_type="asset_handover")
        self.assertFalse(res["is_compliant"])
        self.assertIn("employee_id", res["missing_fields"])
        self.assertEqual(res["triage_verdict"], "REQUIRES_HUMAN_CORRECTION")

    def test_query_rag_knowledge(self):
        res = query_rag_knowledge("asset custody Entra ID Intune", top_k=2)
        self.assertGreater(res["results_count"], 0)
        self.assertIn("retrieval_latency_ms", res)
        self.assertLessEqual(res["retrieval_latency_ms"], 10.0)

    def test_approval_workflow(self):
        approval = request_human_approval(
            action_name="wipe_endpoint_storage",
            action_parameters={"endpoint": "WS-099"},
            rationale="Automated deprovisioning cycle."
        )
        self.assertEqual(approval["status"], "APPROVAL_REQUIRED")
        ticket_id = approval["ticket_id"]
        code = approval["confirmation_code"]

        # Bad code fails
        failed = verify_approval_token(ticket_id, "WRONG_CODE")
        self.assertFalse(failed["authorized"])

        # Good code passes
        verified = verify_approval_token(ticket_id, code)
        self.assertTrue(verified["authorized"])
        self.assertEqual(verified["status"], "AUTHORIZED_FOR_DISPATCH")

    def test_track_cost_budget(self):
        res1 = track_cost_budget("sess-test-1", 1000, 500, model_name="gemini-1.5-flash", session_budget_usd=1.0)
        self.assertEqual(res1["status"], "OK")
        self.assertFalse(res1["budget_exceeded"])
        self.assertGreater(res1["total_cost_usd"], 0)

        # Exceed budget
        res2 = track_cost_budget("sess-test-1", 50000000, 50000000, model_name="claude-3-5-sonnet", session_budget_usd=1.0)
        self.assertTrue(res2["budget_exceeded"])
        self.assertEqual(res2["status"], "HALT_BUDGET_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
