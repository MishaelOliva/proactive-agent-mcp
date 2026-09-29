"""
End-to-end demonstration of a full HITL-gated triage session.

Runs the real server as a subprocess and walks the workflow a reviewer is most
likely to ask about: poll the queue, evaluate a document, park a destructive
action for human approval, and show that the agent cannot authorize it alone.
"""

import json
import os
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Stand in for the supervisor's out-of-band channel. A real deployment would
# deliver the confirmation over an authenticated path the agent cannot reach;
# sharing the secret here is the closest equivalent that stays inside one test
# process, and it must be set before the guardrails module is imported.
os.environ["MCP_SIGNING_SECRET"] = "demo-secret-abc"

from proactive_agent_mcp.tools import guardrails  # noqa: E402
from tests.test_stdio_e2e import StdioClient  # noqa: E402


def supervisor_code(ticket_id, action_name, action_parameters, expires_at):
    """Mint a confirmation the way an authorized human channel would."""
    return guardrails.generate_confirmation_code(
        ticket_id, action_name, action_parameters, expires_at
    )


class TestHumanGatedSession(unittest.TestCase):
    def setUp(self):
        self.client = StdioClient({"MCP_SIGNING_SECRET": "demo-secret-abc"})
        self.addCleanup(self.client.close)
        self.client.call(
            "initialize",
            {"protocolVersion": "2025-06-18", "clientInfo": {"name": "demo", "version": "1"}},
            req_id=1,
        )
        self.client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._id = 100

    def next_id(self):
        self._id += 1
        return self._id

    def call_tool(self, name, arguments=None):
        params = {"name": name}
        if arguments is not None:
            params["arguments"] = arguments
        response = self.client.call("tools/call", params, req_id=self.next_id())
        return json.loads(response["result"]["content"][0]["text"])

    def test_full_triage_and_approval_session(self):
        # 1. The agent claims queue work under a lease.
        polled = self.call_tool("poll_event_queue", {"max_items": 2, "lease_seconds": 300})
        self.assertEqual(polled["total_unprocessed_found"], 2)
        document_event = next(
            item for item in polled["items"] if item["type"] == "UNVERIFIED_ASSET_HANDOVER"
        )

        # 2. It evaluates the extracted document against the handover schema.
        compliance = self.call_tool(
            "evaluate_document_compliance",
            {
                "document_payload": {
                    "employee_id": "EMP-4102",
                    "serial_number": "PF-20X9-A089",
                    "department": "Field Operations",
                    "custody_date": "2026-09-24",
                },
                "schema_type": "asset_handover",
            },
        )
        self.assertTrue(compliance["is_compliant"])
        self.assertEqual(compliance["confidence_score"], 1.0)
        self.assertEqual(compliance["triage_verdict"], "APPROVED_AUTO_PASS")

        # 3. It settles the event rather than leaving it leased.
        settled = self.call_tool(
            "complete_event",
            {"event_id": document_event["id"], "outcome": "PROCESSED", "note": "schema passed"},
        )
        self.assertEqual(settled["status"], "OK")

        # 4. A destructive action is parked for a human.
        ticket = self.call_tool(
            "request_human_approval",
            {
                "action_name": "wipe_endpoint_storage",
                "action_parameters": {"endpoint": document_event["payload"]["device_serial"]},
                "rationale": "Device is unaccounted for after a failed handover.",
                "urgency": "high",
            },
        )
        self.assertEqual(ticket["status"], "APPROVAL_REQUIRED")
        self.assertNotIn("confirmation_code", ticket)

        # 5. The agent cannot authorize itself. It has no code to submit.
        guess = self.call_tool(
            "verify_approval_token",
            {"ticket_id": ticket["ticket_id"], "confirmation_code": "GUESSED-BY-THE-AGENT"},
        )
        self.assertFalse(guess["authorized"])
        self.assertEqual(guess["reason"], "INVALID_CODE")

        # 6. The out-of-band code is minted by the supervisor's channel, which
        #    the agent has no access to. It authorizes the action exactly once.
        code = supervisor_code(
            ticket["ticket_id"],
            "wipe_endpoint_storage",
            {"endpoint": document_event["payload"]["device_serial"]},
            ticket["expires_at"],
        )
        approved = self.call_tool(
            "verify_approval_token",
            {"ticket_id": ticket["ticket_id"], "confirmation_code": code},
        )
        self.assertTrue(approved["authorized"])
        self.assertEqual(approved["status"], "AUTHORIZED_FOR_DISPATCH")

        # 7. And the ticket cannot be reused.
        replay = self.call_tool(
            "verify_approval_token",
            {"ticket_id": ticket["ticket_id"], "confirmation_code": code},
        )
        self.assertFalse(replay["authorized"])
        self.assertEqual(replay["reason"], "ALREADY_CONSUMED")

    def test_budget_stops_a_runaway_loop(self):
        self.call_tool("set_active_session", {"session_id": "runaway"})
        exhausted = self.call_tool(
            "track_cost_budget",
            {
                "session_id": "runaway",
                "prompt_tokens": 20_000_000,
                "completion_tokens": 20_000_000,
                "model_name": "claude-3-5-sonnet",
                "session_budget_usd": 2.0,
            },
        )
        self.assertTrue(exhausted["budget_exceeded"])
        self.assertEqual(exhausted["status"], "HALT_BUDGET_EXCEEDED")

        # Ordinary work is now refused rather than merely discouraged.
        blocked = self.call_tool("poll_event_queue", {"max_items": 1})
        self.assertEqual(blocked["status"], "HALT_BUDGET_EXCEEDED")

        # Accounting stays reachable so the agent can report honestly.
        status = self.call_tool(
            "track_cost_budget",
            {"session_id": "runaway", "prompt_tokens": 0, "completion_tokens": 0},
        )
        self.assertGreaterEqual(status["total_cost_usd"], 2.0)


if __name__ == "__main__":
    unittest.main()
