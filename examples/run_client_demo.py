"""
Interactive End-to-End Client Demo for Proactive Agent MCP Server.
Demonstrates standard JSON-RPC 2.0 stdio communication.
"""

import subprocess
import sys
import json

def run_mcp_exchange():
    process = subprocess.Popen(
        [sys.executable, "-m", "proactive_agent_mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    def send_recv(req: dict) -> dict:
        msg = json.dumps(req) + "\n"
        process.stdin.write(msg)
        process.stdin.flush()
        line = process.stdout.readline()
        return json.loads(line)

    print("=== 1. Initializing MCP Connection ===")
    init_res = send_recv({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "demo-agent-client", "version": "1.0.0"}
        }
    })
    print(f"Handshake Response: {json.dumps(init_res, indent=2)}\n")

    print("=== 2. Discovering Available Tools ===")
    tools_res = send_recv({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = [t["name"] for t in tools_res["result"]["tools"]]
    print(f"Exposed Tools ({len(tools)}): {tools}\n")

    print("=== 3. Executing Tool: poll_event_queue (Proactive Agent Trigger) ===")
    poll_res = send_recv({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "poll_event_queue",
            "arguments": {"max_items": 1}
        }
    })
    print(f"Tool Output:\n{poll_res['result']['content'][0]['text']}\n")

    print("=== 4. Executing Tool: evaluate_document_compliance ===")
    eval_res = send_recv({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "evaluate_document_compliance",
            "arguments": {
                "document_payload": {
                    "employee_id": "EMP-4019",
                    "serial_number": "PF-20X9-A089",
                    "department": "Engineering Operations",
                    "custody_date": "2026-09-24"
                },
                "schema_type": "asset_handover"
            }
        }
    })
    print(f"Compliance Output:\n{eval_res['result']['content'][0]['text']}\n")

    process.terminate()
    print("Demo completed successfully!")

if __name__ == "__main__":
    run_mcp_exchange()
