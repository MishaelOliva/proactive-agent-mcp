"""
MCP prompt templates for agentic runtimes.

Prompt arguments are validated here, because ``prompts/get`` is the one place a
client can inject free text into a runbook that the model will follow. Undefined
arguments are rejected rather than silently defaulted.
"""

from __future__ import annotations

from typing import Any

from ..protocol import Prompt, PromptArgument

PROMPTS: list[Prompt] = [
    Prompt(
        name="autonomous_triage_loop",
        description=(
            "Runbook for a proactive triage pass: claim queue events, validate "
            "documents, settle what was handled, and escalate what was not."
        ),
        arguments=[
            PromptArgument(name="queue_name", description="Queue to poll.", required=False),
            PromptArgument(
                name="severity_filter",
                description="Lowest severity to act on: low, medium, high, or critical.",
                required=False,
            ),
        ],
    ),
    Prompt(
        name="compliance_audit_brief",
        description="Generate an executive discrepancy brief for one evaluated document.",
        arguments=[
            PromptArgument(
                name="document_id", description="Identifier of the document.", required=True
            )
        ],
    ),
]

VALID_SEVERITIES = ("low", "medium", "high", "critical")


def _require(arguments: dict[str, str], name: str) -> str:
    value = (arguments.get(name) or "").strip()
    if not value:
        raise ValueError(f"Prompt argument '{name}' is required.")
    return value


def _user_message(description: str, text: str) -> dict[str, Any]:
    return {
        "description": description,
        "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
    }


def get_prompt_message(name: str, arguments: dict[str, str]) -> dict[str, Any]:
    if name == "autonomous_triage_loop":
        queue = (arguments.get("queue_name") or "default").strip() or "default"
        severity = (arguments.get("severity_filter") or "all").strip().lower() or "all"
        if severity != "all" and severity not in VALID_SEVERITIES:
            raise ValueError(
                f"Invalid severity_filter '{severity}'. "
                f"Expected 'all' or one of {list(VALID_SEVERITIES)}."
            )

        return _user_message(
            "Proactive autonomous triage loop",
            f"""You are operating as a proactive operations agent over the Model Context Protocol.

Runbook for this pass, targeting queue '{queue}' at severity '{severity}':

1. Call `poll_event_queue` with queue_name='{queue}', filter_severity='{severity}',
   and a lease you can comfortably finish inside. The response includes
   lease_expires_at.
2. For each claimed event, take exactly one of these paths:
   - It carries a document payload: call `evaluate_document_compliance`. Report
     confidence, missing fields, and risk level.
   - It is an alert: state the diagnosis and the recommended next action.
3. Settle every event you handled with `complete_event`. Use
   outcome='ESCALATED' if a human needs to look at it. Call `release_event` if you
   could not finish, so the work returns to the queue instead of waiting for the
   lease to lapse.
4. Before any destructive or configuration-changing action, call
   `request_human_approval` and stop. Do not attempt to derive or guess the
   confirmation code; it must come from a human over an authenticated channel.
5. Book token usage with `track_cost_budget` as you go. If it reports
   HALT_BUDGET_EXCEEDED, stop calling tools and summarise the session.

Do not claim an action was completed when it was only staged.""",
        )

    if name == "compliance_audit_brief":
        document_id = _require(arguments, "document_id")
        return _user_message(
            "Compliance audit brief",
            f"""Produce an executive compliance brief for document '{document_id}'.

- Re-evaluate it with `evaluate_document_compliance`, or reuse the recorded result.
- Cross-check against the `compliance://standards` resource.
- State the confidence score, each missing field or pattern violation, and the
  assigned risk level.
- Distinguish what the schema actually verified from what it did not cover.
  Required-field validation says nothing about whether the values are truthful.
- Close with the specific remediation a document owner should perform.""",
        )

    raise ValueError(f"Prompt '{name}' not found.")
