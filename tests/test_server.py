"""
Server dispatch behaviour: tool calls, argument validation, and budget
enforcement.
"""

import json
import unittest

from proactive_agent_mcp.server import MCPServer
from tests.helpers import StateResetTestCase


def call(server, name, arguments=None, req_id=1):
    params = {"name": name}
    if arguments is not None:
        params["arguments"] = arguments
    response = server.handle_message(
        {"jsonrpc": "2.0", "id": req_id, "method": "tools/call", "params": params}
    )
    body = json.loads(response["result"]["content"][0]["text"])
    return response["result"], body


def ready_server():
    server = MCPServer()
    server.handle_message({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
    server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return server


class TestToolDispatch(StateResetTestCase):
    def setUp(self):
        super().setUp()
        self.server = ready_server()

    def test_successful_call_is_not_an_error(self):
        result, body = call(self.server, "poll_event_queue", {"max_items": 1})
        self.assertFalse(result["isError"])
        self.assertIn("items", body)

    def test_structured_content_is_returned_to_modern_clients(self):
        result, _ = call(self.server, "poll_event_queue", {"max_items": 1})
        self.assertIn("structuredContent", result)
        self.assertIsInstance(result["structuredContent"], dict)

    def test_legacy_clients_get_text_content_only(self):
        server = MCPServer()
        server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {"protocolVersion": "2024-11-05"},
            }
        )
        server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
        result, _ = call(server, "poll_event_queue", {"max_items": 1})
        self.assertNotIn("structuredContent", result)
        self.assertEqual(result["content"][0]["type"], "text")

    def test_unknown_tool_is_reported_as_a_tool_error(self):
        result, body = call(self.server, "no_such_tool", {})
        self.assertTrue(result["isError"])
        self.assertIn("not found", body["error"])

    def test_missing_tool_name_is_a_protocol_error(self):
        response = self.server.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}
        )
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32602)

    def test_every_registered_tool_is_callable(self):
        for tool in self.server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[
            "result"
        ]["tools"]:
            with self.subTest(tool=tool["name"]):
                result, _ = call(self.server, tool["name"], {})
                # Reachable and validated; a missing-argument complaint is a
                # correct answer, an unknown-tool complaint is not.
                self.assertNotIn("not found", result["content"][0]["text"])


class TestArgumentValidation(StateResetTestCase):
    """
    Regression: v1.0.0 called handlers with **arguments, so a bad type or an
    undeclared key surfaced as a Python TypeError instead of a protocol error.
    """

    def setUp(self):
        super().setUp()
        self.server = ready_server()

    def test_out_of_range_argument_is_rejected_with_field_detail(self):
        result, body = call(self.server, "poll_event_queue", {"max_items": 9999})
        self.assertTrue(result["isError"])
        self.assertEqual(body["problems"][0]["field"], "max_items")

    def test_undeclared_argument_is_rejected_rather_than_ignored(self):
        result, body = call(self.server, "poll_event_queue", {"surprise": True})
        self.assertTrue(result["isError"])
        self.assertEqual(body["problems"][0]["field"], "surprise")

    def test_wrong_type_is_rejected(self):
        result, body = call(self.server, "poll_event_queue", {"max_items": "many"})
        self.assertTrue(result["isError"])
        self.assertEqual(body["problems"][0]["field"], "max_items")

    def test_invalid_enum_value_is_rejected_not_coerced(self):
        """v1.0.0 silently rewrote an invalid severity to 'all'."""
        result, body = call(self.server, "poll_event_queue", {"filter_severity": "urgent"})
        self.assertTrue(result["isError"])
        self.assertEqual(body["problems"][0]["field"], "filter_severity")

    def test_missing_required_argument_is_reported(self):
        result, body = call(self.server, "evaluate_document_compliance", {})
        self.assertTrue(result["isError"])
        self.assertEqual(body["problems"][0]["field"], "document_payload")

    def test_negative_token_counts_are_rejected(self):
        result, body = call(
            self.server,
            "track_cost_budget",
            {"session_id": "s1", "prompt_tokens": -5, "completion_tokens": 0},
        )
        self.assertTrue(result["isError"])
        self.assertEqual(body["problems"][0]["field"], "prompt_tokens")

    def test_empty_query_is_rejected(self):
        result, _ = call(self.server, "query_rag_knowledge", {"query": ""})
        self.assertTrue(result["isError"])

    def test_omitted_arguments_object_is_treated_as_empty(self):
        response = self.server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "poll_event_queue"},
            }
        )
        self.assertFalse(response["result"]["isError"])


class TestBudgetEnforcement(StateResetTestCase):
    """
    Regression: v1.0.0 returned a HALT_BUDGET_EXCEEDED string and left the
    decision to the model, which is the failure a budget guard exists to stop.
    """

    def setUp(self):
        super().setUp()
        self.server = ready_server()

    def _blow_budget(self, session="burner"):
        call(self.server, "set_active_session", {"session_id": session})
        _, body = call(
            self.server,
            "track_cost_budget",
            {
                "session_id": session,
                "prompt_tokens": 10_000_000,
                "completion_tokens": 10_000_000,
                "model_name": "claude-3-5-sonnet",
                "session_budget_usd": 1.0,
            },
        )
        return body

    def test_exhausted_budget_blocks_further_tool_calls(self):
        self._blow_budget()
        result, body = call(self.server, "poll_event_queue", {"max_items": 1})
        self.assertTrue(result["isError"])
        self.assertEqual(body["status"], "HALT_BUDGET_EXCEEDED")

    def test_blocking_reports_the_budget_that_stopped_it(self):
        self._blow_budget()
        _, body = call(self.server, "query_rag_knowledge", {"query": "asset"})
        self.assertGreaterEqual(body["budget"]["total_cost_usd"], 1.0)
        self.assertIn("session_id", body)

    def test_budget_tools_stay_reachable_so_the_agent_is_not_dead_ended(self):
        self._blow_budget()
        result, _ = call(
            self.server,
            "track_cost_budget",
            {
                "session_id": "burner",
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "session_budget_usd": 1000.0,
            },
        )
        self.assertFalse(result["isError"])

    def test_raising_the_budget_unblocks_the_session(self):
        self._blow_budget()
        # Spend is well above $1, so the new ceiling has to clear it.
        call(
            self.server,
            "track_cost_budget",
            {
                "session_id": "burner",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "session_budget_usd": 1000.0,
            },
        )
        result, _ = call(self.server, "poll_event_queue", {"max_items": 1})
        self.assertFalse(result["isError"])

    def test_raising_the_budget_below_current_spend_stays_blocked(self):
        """A ceiling under what has already been spent must not unblock work."""
        self._blow_budget()
        call(
            self.server,
            "track_cost_budget",
            {
                "session_id": "burner",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "session_budget_usd": 1.5,
            },
        )
        result, body = call(self.server, "poll_event_queue", {"max_items": 1})
        self.assertTrue(result["isError"])
        self.assertEqual(body["status"], "HALT_BUDGET_EXCEEDED")

    def test_one_exhausted_session_does_not_block_another(self):
        self._blow_budget("burner")
        call(self.server, "set_active_session", {"session_id": "healthy"})
        result, _ = call(self.server, "poll_event_queue", {"max_items": 1})
        self.assertFalse(result["isError"])

    def test_regression_budget_change_applies_mid_session(self):
        """
        Regression: v1.0.0 wrote session_budget_usd only on first use, so
        tightening a budget after the first call was silently ignored.
        """
        from proactive_agent_mcp.tools.guardrails import COST_GUARD

        _, first = call(
            self.server,
            "track_cost_budget",
            {"session_id": "s", "prompt_tokens": 1000, "completion_tokens": 1000},
        )
        self.assertEqual(first["session_budget_usd"], 5.0)

        COST_GUARD.reset("s")
        call(
            self.server,
            "track_cost_budget",
            {
                "session_id": "s",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "session_budget_usd": 0.5,
            },
        )
        _, second = call(
            self.server,
            "track_cost_budget",
            {"session_id": "s", "prompt_tokens": 0, "completion_tokens": 0},
        )
        self.assertEqual(second["session_budget_usd"], 0.5)

    def test_budget_accounting_is_correct(self):
        from proactive_agent_mcp.tools.guardrails import COST_GUARD

        COST_GUARD.reset("maths")
        status = COST_GUARD.record(
            session_id="maths",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            model_name="gpt-4o",
            session_budget_usd=100.0,
        )
        # 1M prompt @ 0.00250/1k = 2.50; 1M completion @ 0.01000/1k = 10.00
        self.assertAlmostEqual(status["call_cost_usd"], 12.5, places=4)
        self.assertEqual(status["total_tokens_consumed"], 2_000_000)
        self.assertEqual(status["status"], "OK")

    def test_local_model_is_free(self):
        from proactive_agent_mcp.tools.guardrails import COST_GUARD

        COST_GUARD.reset("local")
        status = COST_GUARD.record(
            session_id="local",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            model_name="local-ollama",
            session_budget_usd=1.0,
        )
        self.assertEqual(status["call_cost_usd"], 0.0)
        self.assertEqual(status["status"], "OK")


if __name__ == "__main__":
    unittest.main()
