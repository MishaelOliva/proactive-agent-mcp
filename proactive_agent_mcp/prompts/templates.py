"""
Standardized MCP Prompt Templates for Agentic Runtimes (Claude Desktop, OpenClaw, Cursor).
"""

from typing import Any, Dict, List
from ..protocol import Prompt, PromptArgument

PROMPTS: List[Prompt] = [
    Prompt(
        name="autonomous_triage_loop",
        description="Instructional workflow guiding the agent through proactive queue discovery, schema validation, and escalation.",
        arguments=[
            PromptArgument(name="queue_name", description="Target queue to poll.", required=False),
            PromptArgument(name="urgency_filter", description="Severity threshold (e.g. high, critical).", required=False)
        ]
    ),
    Prompt(
        name="compliance_audit_brief",
        description="Template for generating executive discrepancy reports from evaluated documents.",
        arguments=[
            PromptArgument(name="document_id", description="ID of document evaluated.", required=True)
        ]
    )
]


def get_prompt_message(name: str, arguments: Dict[str, str]) -> Dict[str, Any]:
    if name == "autonomous_triage_loop":
        q = arguments.get("queue_name", "default")
        urgency = arguments.get("urgency_filter", "all")
        msg = f"""You are operating as an Autonomous Proactive Ops Agent connected via Model Context Protocol (MCP).

Follow this exact operational runbook:
1. Call `poll_event_queue` with queue_name='{q}' and filter_severity='{urgency}'.
2. For any document payload discovered:
   - Call `evaluate_document_compliance` with the extracted fields.
   - If compliant with high confidence, auto-stage the record and log an informational note.
   - If non-compliant or missing mandatory fields, identify the discrepancy.
3. For destructive or configuration changes:
   - DO NOT execute directly.
   - Call `request_human_approval` with clear rationale and await verification.
4. Record all token usage using `track_cost_budget` to enforce operational spend guardrails.
"""
        return {
            "description": "Proactive autonomous triage loop prompt",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": msg}
                }
            ]
        }

    elif name == "compliance_audit_brief":
        doc_id = arguments.get("document_id", "UNKNOWN")
        msg = f"Generate an executive compliance brief for document ID '{doc_id}'. Check against enterprise policy `compliance://standards` and report confidence, missing fields, and risk level."
        return {
            "description": "Compliance audit prompt",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": msg}
                }
            ]
        }

    else:
        raise ValueError(f"Prompt '{name}' not found.")
