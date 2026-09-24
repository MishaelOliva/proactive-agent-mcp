import unittest
from proactive_agent_mcp.server import MCPServer
from proactive_agent_mcp.protocol import (
    MCP_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    PARSE_ERROR
)

class TestMCPProtocol(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer()

    def test_initialize_handshake(self):
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {}
            }
        }
        res = self.server.handle_request(req)
        self.assertIsNotNone(res)
        self.assertEqual(res["id"], 1)
        self.assertIn("result", res)
        self.assertEqual(res["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertIn("tools", res["result"]["capabilities"])
        self.assertIn("resources", res["result"]["capabilities"])
        self.assertIn("prompts", res["result"]["capabilities"])

    def test_ping(self):
        req = {
            "jsonrpc": "2.0",
            "id": "ping-01",
            "method": "ping"
        }
        res = self.server.handle_request(req)
        self.assertEqual(res["id"], "ping-01")
        self.assertEqual(res["result"], {})

    def test_unknown_method(self):
        req = {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "non_existent_method"
        }
        res = self.server.handle_request(req)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], METHOD_NOT_FOUND)

    def test_tools_list(self):
        req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list"
        }
        res = self.server.handle_request(req)
        tools = res["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("poll_event_queue", tool_names)
        self.assertIn("evaluate_document_compliance", tool_names)
        self.assertIn("query_rag_knowledge", tool_names)
        self.assertIn("request_human_approval", tool_names)
        self.assertIn("verify_approval_token", tool_names)
        self.assertIn("track_cost_budget", tool_names)

    def test_resources_list_and_read(self):
        req_list = {"jsonrpc": "2.0", "id": 3, "method": "resources/list"}
        res_list = self.server.handle_request(req_list)
        self.assertTrue(len(res_list["result"]["resources"]) >= 2)

        req_read = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "resources/read",
            "params": {"uri": "system://health"}
        }
        res_read = self.server.handle_request(req_read)
        self.assertIn("contents", res_read["result"])
        self.assertEqual(res_read["result"]["contents"][0]["uri"], "system://health")

    def test_prompts_list_and_get(self):
        req_list = {"jsonrpc": "2.0", "id": 5, "method": "prompts/list"}
        res_list = self.server.handle_request(req_list)
        self.assertTrue(len(res_list["result"]["prompts"]) >= 1)

        req_get = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "prompts/get",
            "params": {"name": "autonomous_triage_loop", "arguments": {}}
        }
        res_get = self.server.handle_request(req_get)
        self.assertIn("messages", res_get["result"])


if __name__ == "__main__":
    unittest.main()
