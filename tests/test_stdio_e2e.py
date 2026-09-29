"""
End-to-end check of the stdio transport.

Spawns the server as a real subprocess and exchanges newline-delimited JSON-RPC
with it, which is the only way to confirm that stdout carries protocol traffic
only, that stderr never leaks into it, and that the exit path is clean.
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class StdioClient:
    """Minimal JSON-RPC client over the server's stdin/stdout pipes."""

    def __init__(self, env_extra=None):
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        env.update(env_extra or {})
        self.process = subprocess.Popen(
            [sys.executable, "-m", "proactive_agent_mcp.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=REPO_ROOT,
            env=env,
        )
        self.stderr_chunks: list[str] = []

    def send(self, payload):
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()

    def send_raw(self, line):
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def read_response(self):
        line = self.process.stdout.readline()
        if not line:
            return None
        return json.loads(line)

    def call(self, method, params=None, req_id=1, expect_response=True):
        message = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)
        return self.read_response() if expect_response else None

    def close(self):
        try:
            self.process.stdin.close()
        except Exception:
            pass
        try:
            _, stderr = self.process.communicate(timeout=10)
            self.stderr_chunks.append(stderr or "")
        except subprocess.TimeoutExpired:
            self.process.kill()
            _, stderr = self.process.communicate()
            self.stderr_chunks.append(stderr or "")
        return self.process.returncode


class TestStdioTransport(unittest.TestCase):
    def setUp(self):
        self.client = StdioClient({"MCP_SIGNING_SECRET": "e2e-test-secret"})
        self.addCleanup(self.client.close)

    def initialize(self):
        response = self.client.call(
            "initialize",
            {"protocolVersion": "2025-06-18", "clientInfo": {"name": "e2e", "version": "1"}},
            req_id=1,
        )
        self.client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return response

    def test_full_session_over_stdio(self):
        init = self.initialize()
        self.assertEqual(init["result"]["serverInfo"]["name"], "proactive-agent-mcp")

        tools = self.client.call("tools/list", req_id=2)
        names = [t["name"] for t in tools["result"]["tools"]]
        self.assertIn("poll_event_queue", names)

        result = self.client.call(
            "tools/call",
            {
                "name": "evaluate_document_compliance",
                "arguments": {
                    "document_payload": {
                        "employee_id": "EMP-4019",
                        "serial_number": "PF-20X9-A089",
                        "department": "Engineering Operations",
                        "custody_date": "2026-09-24",
                    }
                },
            },
            req_id=3,
        )
        payload = json.loads(result["result"]["content"][0]["text"])
        self.assertTrue(payload["is_compliant"])
        self.assertEqual(payload["confidence_score"], 1.0)

        self.assertEqual(self.client.close(), 0)

    def test_logs_go_to_stderr_and_never_pollute_stdout(self):
        """
        The whole protocol depends on stdout carrying nothing but JSON-RPC.
        Logging to stdout would corrupt the stream for a real client.
        """
        self.initialize()
        self.client.call("tools/list", req_id=2)
        self.client.call("tools/call", {"name": "poll_event_queue", "arguments": {}}, req_id=3)
        self.client.close()

        for chunk in self.client.stderr_chunks:
            if chunk.strip():
                self.assertIn("[MCP]", chunk, "expected structured logs on stderr")

        # If any log line had reached stdout, a client reading one response per
        # request would desynchronise. Prove stdout is exactly one JSON doc per
        # response by checking the transport still responds in lockstep.
        client = StdioClient({"MCP_SIGNING_SECRET": "e2e"})
        self.addCleanup(client.close)
        client.call("initialize", {"protocolVersion": "2025-06-18"}, req_id=1)
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        for expected in range(2, 6):
            self.assertEqual(client.call("ping", req_id=expected)["id"], expected)

    def test_cancellation_notification_yields_no_response(self):
        self.initialize()
        self.client.call("ping", req_id=2)
        # Send a cancellation; the next response must belong to the next request.
        self.client.send(
            {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 2}}
        )
        following = self.client.call("ping", req_id=3)
        self.assertEqual(following["id"], 3)

    def test_malformed_json_does_not_kill_the_process(self):
        self.initialize()
        self.client.send_raw("{ not valid json")
        error = self.client.read_response()
        self.assertEqual(error["error"]["code"], -32700)
        self.assertIsNone(error["id"])

        alive = self.client.call("ping", req_id=9)
        self.assertEqual(alive["id"], 9)

    def test_blank_lines_are_ignored(self):
        self.initialize()
        self.client.send_raw("")
        self.client.send_raw("   ")
        self.assertEqual(self.client.call("ping", req_id=4)["id"], 4)

    def test_shutdown_is_clean_on_stdin_close(self):
        self.initialize()
        self.assertEqual(self.client.close(), 0)


class TestStartupWithoutConfiguredSecret(unittest.TestCase):
    def test_server_still_starts_and_warns_loudly(self):
        env = {k: v for k, v in os.environ.items() if k != "MCP_SIGNING_SECRET"}
        process = subprocess.Popen(
            [sys.executable, "-m", "proactive_agent_mcp.server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=REPO_ROOT,
            env=env,
        )
        try:
            init = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            }
            process.stdin.write(json.dumps(init) + "\n")
            process.stdin.flush()
            response = json.loads(process.stdout.readline())
            self.assertIn("result", response)

            process.stdin.close()
            _, stderr = process.communicate(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

        self.assertIn("MCP_SIGNING_SECRET is not set", stderr)


if __name__ == "__main__":
    unittest.main()
