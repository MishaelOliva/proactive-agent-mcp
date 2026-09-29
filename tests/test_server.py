import unittest
import json
from proactive_agent_mcp.server import MCPServer

class TestMCPServerCalls(unittest.TestCase):
    def setUp(self):
        self.server = MCPServer()

    def test_call_tool_poll_event_queue(self):
        req = {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/call",
            "params": {
                "name": "poll_event_queue",
                "arguments": {"max_items": 1}
            }
        }
        res = self.server.handle_request(req)
        self.assertFalse(res["result"]["isError"])
        content_text = res["result"]["content"][0]["text"]
        data = json.loads(content_text)
        self.assertIn("items", data)

    def test_call_tool_unknown(self):
        req = {
            "jsonrpc": "2.0",
            "id": 102,
            "method": "tools/call",
            "params": {
                "name": "non_existent_tool",
                "arguments": {}
            }
        }
        res = self.server.handle_request(req)
        self.assertTrue(res["result"]["isError"])
        self.assertIn("not found", res["result"]["content"][0]["text"])

    def test_call_tool_invalid_arguments(self):
        req = {
            "jsonrpc": "2.0",
            "id": 103,
            "method": "tools/call",
            "params": {
                "name": "evaluate_document_compliance",
                "arguments": {"document_payload": {}}
            }
        }
        res = self.server.handle_request(req)
        self.assertFalse(res["result"]["isError"])
        content = json.loads(res["result"]["content"][0]["text"])
        self.assertFalse(content["is_compliant"])

    def test_unknown_or_missing_method(self):
        req = {
            "jsonrpc": "2.0",
            "id": 104,
            "method": "invalid/method"
        }
        res = self.server.handle_request(req)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -32601)

    def test_read_resource_unknown_uri(self):
        req = {
            "jsonrpc": "2.0",
            "id": 105,
            "method": "resources/read",
            "params": {"uri": "unknown://resource"}
        }
        res = self.server.handle_request(req)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -32602)

    def test_get_prompt_unknown(self):
        req = {
            "jsonrpc": "2.0",
            "id": 106,
            "method": "prompts/get",
            "params": {"name": "non_existent_prompt"}
        }
        res = self.server.handle_request(req)
        self.assertIn("error", res)
        self.assertEqual(res["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
