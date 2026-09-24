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


if __name__ == "__main__":
    unittest.main()
