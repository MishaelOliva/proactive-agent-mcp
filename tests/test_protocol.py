"""
JSON-RPC 2.0 and MCP protocol conformance.

These cases cover the parts of the specification a real client depends on and
that are easy to get subtly wrong: notification handling, initialisation
gating, version negotiation, batching, and error codes.
"""

import io
import json
import sys
import unittest

from proactive_agent_mcp.protocol import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    LEGACY_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    SUPPORTED_PROTOCOL_VERSIONS,
    is_notification,
)
from proactive_agent_mcp.server import MCPServer

INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}


def request(method, params=None, req_id=99):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


class TestProtocolVersionNegotiation(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer()

    def test_defaults_to_newest_supported_version(self):
        result = self.server.handle_message(INIT)["result"]
        self.assertEqual(result["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertIn(result["protocolVersion"], SUPPORTED_PROTOCOL_VERSIONS)

    def test_echoes_a_supported_requested_version(self):
        for version in SUPPORTED_PROTOCOL_VERSIONS:
            with self.subTest(version=version):
                result = self.server.handle_message(
                    {**INIT, "params": {"protocolVersion": version}}
                )["result"]
                self.assertEqual(result["protocolVersion"], version)

    def test_unknown_version_falls_back_to_newest(self):
        result = self.server.handle_message({**INIT, "params": {"protocolVersion": "1999-01-01"}})[
            "result"
        ]
        self.assertEqual(result["protocolVersion"], MCP_PROTOCOL_VERSION)

    def test_legacy_client_is_not_upgraded_against_its_will(self):
        result = self.server.handle_message(
            {**INIT, "params": {"protocolVersion": LEGACY_PROTOCOL_VERSION}}
        )["result"]
        self.assertEqual(result["protocolVersion"], LEGACY_PROTOCOL_VERSION)

    def test_structured_output_only_offered_to_clients_that_understand_it(self):
        modern = MCPServer()
        modern.handle_message({**INIT, "params": {"protocolVersion": "2025-06-18"}})
        modern.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = modern.handle_message(request("tools/list"))["result"]["tools"]
        self.assertIn("outputSchema", tools[0])

        legacy = MCPServer()
        legacy.handle_message({**INIT, "params": {"protocolVersion": LEGACY_PROTOCOL_VERSION}})
        legacy.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = legacy.handle_message(request("tools/list"))["result"]["tools"]
        self.assertNotIn("outputSchema", tools[0])


class TestNotificationHandling(unittest.TestCase):
    """
    JSON-RPC 2.0: a server MUST NOT reply to a notification.

    MCP clients emit notifications/cancelled whenever a user interrupts a tool
    call, so answering them corrupts the client's request/response pairing.
    """

    def setUp(self):
        self.server = MCPServer()
        self.server.handle_message(INIT)

    def test_is_notification_helper(self):
        self.assertTrue(is_notification({"jsonrpc": "2.0", "method": "ping"}))
        self.assertFalse(is_notification({"jsonrpc": "2.0", "id": 1, "method": "ping"}))

    def test_known_notifications_get_no_response(self):
        for method in (
            "notifications/initialized",
            "notifications/cancelled",
            "notifications/progress",
            "notifications/roots/list_changed",
        ):
            with self.subTest(method=method):
                self.assertIsNone(self.server.handle_message({"jsonrpc": "2.0", "method": method}))

    def test_unknown_notification_gets_no_response(self):
        self.assertIsNone(
            self.server.handle_message({"jsonrpc": "2.0", "method": "notifications/nope"})
        )

    def test_unknown_notification_never_emits_an_error_envelope(self):
        response = self.server.handle_message({"jsonrpc": "2.0", "method": "totally/unknown"})
        self.assertIsNone(response)

    def test_batch_omits_notification_responses(self):
        response = self.server.handle_message(
            [
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 5, "method": "ping"},
            ]
        )
        self.assertIsInstance(response, list)
        self.assertEqual(len(response), 1)
        self.assertEqual(response[0]["id"], 5)

    def test_batch_of_only_notifications_returns_nothing(self):
        self.assertIsNone(
            self.server.handle_message([{"jsonrpc": "2.0", "method": "notifications/initialized"}])
        )

    def test_empty_batch_is_rejected(self):
        response = self.server.handle_message([])
        self.assertEqual(response["error"]["code"], INVALID_REQUEST)


class TestInitializationGating(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer()

    def test_requests_before_initialize_are_refused(self):
        for method in ("tools/list", "tools/call", "resources/list", "prompts/list"):
            with self.subTest(method=method):
                response = self.server.handle_message(request(method))
                self.assertEqual(response["error"]["code"], INVALID_REQUEST)

    def test_ping_is_allowed_before_initialize(self):
        self.assertIn("result", self.server.handle_message(request("ping")))

    def test_initialized_notification_opens_the_gate(self):
        self.assertFalse(self.server.initialized)
        self.server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertTrue(self.server.initialized)
        self.assertIn("result", self.server.handle_message(request("tools/list")))


class TestErrorHandling(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer()
        self.server.handle_message(INIT)
        self.server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def test_unknown_method(self):
        response = self.server.handle_message(request("does/not/exist"))
        self.assertEqual(response["error"]["code"], METHOD_NOT_FOUND)

    def test_missing_jsonrpc_version(self):
        response = self.server.handle_message({"id": 1, "method": "ping"})
        self.assertEqual(response["error"]["code"], INVALID_REQUEST)

    def test_wrong_jsonrpc_version(self):
        response = self.server.handle_message({"jsonrpc": "1.0", "id": 1, "method": "ping"})
        self.assertEqual(response["error"]["code"], INVALID_REQUEST)

    def test_missing_method(self):
        response = self.server.handle_message({"jsonrpc": "2.0", "id": 1})
        self.assertEqual(response["error"]["code"], INVALID_REQUEST)

    def test_non_object_message(self):
        response = self.server.handle_message("just a string")
        self.assertEqual(response["error"]["code"], INVALID_REQUEST)

    def test_params_must_be_an_object(self):
        response = self.server.handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": [1, 2, 3]}
        )
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    def test_every_error_carries_a_code_and_message(self):
        for bad in (request("nope"), {"jsonrpc": "2.0", "id": 1}):
            with self.subTest(message=bad):
                error = self.server.handle_message(bad)["error"]
                self.assertIsInstance(error["code"], int)
                self.assertTrue(error["message"])


class TestListingAndPagination(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer()
        self.server.handle_message(INIT)
        self.server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def test_tools_list_shape(self):
        tools = self.server.handle_message(request("tools/list"))["result"]["tools"]
        self.assertGreater(len(tools), 0)
        for tool in tools:
            self.assertIn("name", tool)
            self.assertIn("description", tool)
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_pagination_cursor_walks_the_full_list(self):
        seen, cursor = [], None
        while True:
            params = {"cursor": cursor} if cursor else {}
            page = self.server.handle_message(request("tools/list", params))["result"]
            seen.extend(t["name"] for t in page["tools"])
            cursor = page.get("nextCursor")
            if not cursor:
                break
        self.assertEqual(len(seen), len(set(seen)), "no tool should be listed twice")
        self.assertGreater(len(seen), 1)

    def test_invalid_cursor_is_rejected(self):
        response = self.server.handle_message(request("tools/list", {"cursor": "abc"}))
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    def test_out_of_range_cursor_is_rejected(self):
        response = self.server.handle_message(request("tools/list", {"cursor": "99999"}))
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    def test_resources_and_prompts_list(self):
        resources = self.server.handle_message(request("resources/list"))["result"]
        self.assertTrue(any(r["uri"] == "system://health" for r in resources["resources"]))

        prompts = self.server.handle_message(request("prompts/list"))["result"]
        names = [p["name"] for p in prompts["prompts"]]
        self.assertIn("autonomous_triage_loop", names)
        self.assertIn("compliance_audit_brief", names)

    def test_prompt_names_match_the_documented_names(self):
        """The README quotes these names; a drift here breaks the docs."""
        prompts = self.server.handle_message(request("prompts/list"))["result"]
        names = {p["name"] for p in prompts["prompts"]}
        self.assertEqual(names, {"autonomous_triage_loop", "compliance_audit_brief"})


class TestResourceAndPromptDispatch(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer()
        self.server.handle_message(INIT)
        self.server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def test_read_health_resource(self):
        result = self.server.handle_message(request("resources/read", {"uri": "system://health"}))[
            "result"
        ]
        body = json.loads(result["contents"][0]["text"])
        self.assertEqual(body["server"], "proactive-agent-mcp")
        self.assertIn("uptime_seconds", body)
        self.assertIn("budget", body)

    def test_unknown_resource_uri(self):
        response = self.server.handle_message(request("resources/read", {"uri": "nope://x"}))
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    def test_missing_resource_uri(self):
        response = self.server.handle_message(request("resources/read", {}))
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    def test_get_prompt(self):
        result = self.server.handle_message(
            request("prompts/get", {"name": "autonomous_triage_loop", "arguments": {}})
        )["result"]
        self.assertIn("messages", result)

    def test_prompt_requires_its_mandatory_argument(self):
        response = self.server.handle_message(
            request("prompts/get", {"name": "compliance_audit_brief", "arguments": {}})
        )
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    def test_prompt_rejects_an_invalid_severity_filter(self):
        response = self.server.handle_message(
            request(
                "prompts/get",
                {"name": "autonomous_triage_loop", "arguments": {"severity_filter": "urgent"}},
            )
        )
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    def test_unknown_prompt(self):
        response = self.server.handle_message(request("prompts/get", {"name": "no_such_prompt"}))
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)

    def test_logging_set_level(self):
        result = self.server.handle_message(request("logging/setLevel", {"level": "debug"}))[
            "result"
        ]
        self.assertEqual(result, {})
        self.assertEqual(self.server.log_level, "debug")

    def test_logging_set_level_rejects_nonsense(self):
        response = self.server.handle_message(request("logging/setLevel", {"level": "chatty"}))
        self.assertEqual(response["error"]["code"], INVALID_PARAMS)


class TestStdioLoop(unittest.TestCase):
    def test_parse_error_is_reported_without_crashing(self):
        from proactive_agent_mcp import server as server_module

        stdin = io.StringIO("this is not json\n" + json.dumps(INIT) + "\n")
        stdout = io.StringIO()
        old_in, old_out = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = stdin, stdout
        try:
            server_module.MCPServer().run_stdio()
        finally:
            sys.stdin, sys.stdout = old_in, old_out

        lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual(lines[0]["error"]["code"], -32700)
        self.assertIn("result", lines[1])

    def test_notifications_produce_no_stdout_output(self):
        from proactive_agent_mcp import server as server_module

        stdin = io.StringIO(
            json.dumps(INIT)
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled"})
            + "\n"
            + json.dumps(request("ping"))
            + "\n"
        )
        stdout = io.StringIO()
        old_in, old_out = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = stdin, stdout
        try:
            server_module.MCPServer().run_stdio()
        finally:
            sys.stdin, sys.stdout = old_in, old_out

        lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual(len(lines), 2, "cancellation notification must not emit a line")
        for line in lines:
            self.assertIsNotNone(line["id"])


if __name__ == "__main__":
    unittest.main()
