"""
Interactive end-to-end client demo.

Spawns the server as a subprocess and walks a realistic triage session over
newline-delimited JSON-RPC, printing each step. Run it with:

    python examples/run_client_demo.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# The demo acts as both the agent and, for the final step, the supervisor. A
# real deployment delivers the confirmation over an authenticated channel the
# agent cannot reach; sharing the secret here keeps the demo self-contained.
os.environ.setdefault("MCP_SIGNING_SECRET", "demo-only-secret-not-for-production")

from proactive_agent_mcp.tools import guardrails  # noqa: E402


def rule(title: str) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def main() -> int:
    process = subprocess.Popen(
        [sys.executable, "-m", "proactive_agent_mcp.server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
        cwd=REPO_ROOT,
    )
    next_id = [0]

    def rpc(method, params=None):
        next_id[0] += 1
        message = {"jsonrpc": "2.0", "id": next_id[0], "method": method}
        if params is not None:
            message["params"] = params
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
        return json.loads(process.stdout.readline())

    def notify(method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def tool(name, arguments=None):
        params = {"name": name}
        if arguments is not None:
            params["arguments"] = arguments
        response = rpc("tools/call", params)
        return json.loads(response["result"]["content"][0]["text"])

    try:
        rule("1. INITIALIZE  (negotiating the protocol version)")
        init = rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "demo-agent-client", "version": "1.0.0"},
            },
        )
        notify("notifications/initialized")
        result = init["result"]
        print(f"server      : {result['serverInfo']['name']} v{result['serverInfo']['version']}")
        print(f"protocol    : {result['protocolVersion']}")
        print(f"capabilities: {', '.join(sorted(result['capabilities']))}")

        rule("2. DISCOVER TOOLS")
        tools = rpc("tools/list")["result"]["tools"]
        for tool_spec in tools:
            print(f"  - {tool_spec['name']}")
        print(f"\n{len(tools)} tools exposed.")

        rule("3. PROACTIVE POLL  (claiming queue work under a lease)")
        polled = tool("poll_event_queue", {"max_items": 2, "lease_seconds": 300})
        for item in polled["items"]:
            print(f"  {item['id']}  {item['severity']:<8} {item['type']}")
        print(f"\nlease expires at {polled['lease_expires_at']}")

        rule("4. COMPLIANCE EVALUATION  (deterministic schema validation)")
        handover = next(
            (i for i in polled["items"] if i["type"] == "UNVERIFIED_ASSET_HANDOVER"),
            polled["items"][0],
        )
        compliant = tool(
            "evaluate_document_compliance",
            {
                "document_payload": {
                    "employee_id": handover["payload"]["employee_id"],
                    "serial_number": handover["payload"]["device_serial"],
                    "department": "Field Operations",
                    "custody_date": "2026-09-24",
                },
                "schema_type": "asset_handover",
            },
        )
        print(f"  verdict    : {compliant['triage_verdict']}")
        print(f"  confidence : {compliant['confidence_score']}")
        print(f"  risk level : {compliant['risk_level']}")

        print("\n  Now the same document with a malformed employee id:")
        malformed = tool(
            "evaluate_document_compliance",
            {
                "document_payload": {
                    "employee_id": "not-an-id",
                    "serial_number": handover["payload"]["device_serial"],
                    "department": "Field Operations",
                    "custody_date": "2026-09-24",
                },
            },
        )
        print(f"  verdict    : {malformed['triage_verdict']}")
        print(f"  confidence : {malformed['confidence_score']}")
        for violation in malformed["pattern_violations"]:
            print(f"  violation  : {violation['field']} -> {violation['expected_pattern']}")

        rule("5. GROUNDED RETRIEVAL  (TF-IDF vectors, cosine similarity)")
        retrieved = tool("query_rag_knowledge", {"query": "human approval for destructive actions"})
        print(f"  method     : {retrieved['retrieval_method']}")
        print(f"  grounding  : {retrieved['grounding_status']}")
        print(f"  latency    : {retrieved['retrieval_latency_ms']} ms (measured)")
        for hit in retrieved["results"]:
            print(f"  [{hit['similarity_score']}] {hit['title']}")

        print("\n  And a query with nothing in common with the corpus:")
        nonsense = tool("query_rag_knowledge", {"query": "quantum blockchain lobster"})
        print(
            f"  grounding  : {nonsense['grounding_status']} (results: {nonsense['results_count']})"
        )

        rule("6. SETTLE THE EVENT  (so the lease is not left dangling)")
        settled = tool(
            "complete_event",
            {
                "event_id": handover["id"],
                "outcome": "PROCESSED",
                "note": "schema validation passed",
            },
        )
        print(f"  {settled['event_id']} -> {settled['outcome']}")

        rule("7. HUMAN-IN-THE-LOOP GATE  (parking a destructive action)")
        ticket = tool(
            "request_human_approval",
            {
                "action_name": "wipe_endpoint_storage",
                "action_parameters": {"endpoint": handover["payload"]["device_serial"]},
                "rationale": "Device unaccounted for after a failed handover.",
                "urgency": "high",
            },
        )
        print(f"  ticket     : {ticket['ticket_id']}")
        print(f"  status     : {ticket['status']}")
        print(f"  expires    : {ticket['expires_at']}")
        print("  note       : the confirmation code is NOT in this response.")

        rule("8. THE AGENT CANNOT SELF-AUTHORIZE")
        attempt = tool(
            "verify_approval_token",
            {"ticket_id": ticket["ticket_id"], "confirmation_code": "I-APPROVED-THIS-MYSELF"},
        )
        print(f"  authorized : {attempt['authorized']}")
        print(f"  reason     : {attempt['reason']}")
        print(f"  {attempt['error']}")

        rule("9. SUPERVISOR AUTHORIZES  (code from an out-of-band channel)")
        # A real supervisor never sends this through the agent; the demo does so
        # only to show the full loop. A deployment would inject it directly.
        code = guardrails.generate_confirmation_code(
            ticket["ticket_id"],
            ticket["action_name"],
            {"endpoint": handover["payload"]["device_serial"]},
            ticket["expires_at"],
        )
        print(
            f"  code       : {code[:20]}... ({len(code.replace('-', ''))} chars, full 256-bit MAC)"
        )
        approved = tool(
            "verify_approval_token",
            {"ticket_id": ticket["ticket_id"], "confirmation_code": code},
        )
        print(f"  authorized : {approved['authorized']}")
        print(f"  status     : {approved['status']}")

        print("\n  Attempting to replay the same code:")
        replay = tool(
            "verify_approval_token",
            {"ticket_id": ticket["ticket_id"], "confirmation_code": code},
        )
        print(f"  authorized : {replay['authorized']}  reason: {replay['reason']}")

        rule("10. BUDGET GUARD  (enforcement, not advice)")
        tool("set_active_session", {"session_id": "demo-session"})
        cost = tool(
            "track_cost_budget",
            {
                "session_id": "demo-session",
                "prompt_tokens": 50_000,
                "completion_tokens": 20_000,
                "model_name": "gpt-4o",
                "session_budget_usd": 5.0,
            },
        )
        print(f"  spend      : ${cost['total_cost_usd']} of ${cost['session_budget_usd']}")
        print(f"  status     : {cost['status']}")

        print("\n  Booking a very large call to exhaust it:")
        blown = tool(
            "track_cost_budget",
            {
                "session_id": "demo-session",
                "prompt_tokens": 5_000_000,
                "completion_tokens": 5_000_000,
                "model_name": "claude-3-5-sonnet",
            },
        )
        print(f"  spend      : ${blown['total_cost_usd']}")
        print(f"  status     : {blown['status']}")

        blocked = tool("poll_event_queue", {"max_items": 1})
        print(f"\n  next tool call -> {blocked['status']}")
        print(f"  {blocked['error']}")

        rule("11. HEALTH RESOURCE")
        health = json.loads(
            rpc("resources/read", {"uri": "system://health"})["result"]["contents"][0]["text"]
        )
        print(f"  uptime       : {health['uptime_seconds']}s")
        print(f"  active session: {health['active_session_id']}")
        print(
            f"  budget       : ${health['budget']['total_cost_usd']} / ${health['budget']['session_budget_usd']}"
        )
        print(f"  event queue  : {health['event_queue']['by_status']}")
        print(f"  ephemeral key: {health['signing_secret_is_ephemeral']}")

        rule("DEMO COMPLETE")
        print("Every step above ran over real JSON-RPC on stdio against a real server process.")
        return 0

    finally:
        try:
            process.stdin.close()
        except Exception:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
