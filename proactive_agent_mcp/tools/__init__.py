"""
Tool registry and dispatcher.

Every tool carries a JSON Schema for its arguments that is enforced at the
protocol boundary by :mod:`proactive_agent_mcp.validation`, so a malformed
``tools/call`` is rejected with JSON-RPC ``Invalid params`` rather than raising
a ``TypeError`` deep inside a handler.

Descriptions state what a tool actually does. Where a tool approximates a
capability the description says so, because a tool contract that overstates
itself is worse than one that admits its limits.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..protocol import Tool
from ..validation import ToolInputError, validate_arguments
from .compliance import evaluate_document_compliance
from .guardrails import (
    COST_GUARD,
    BudgetExceeded,
    pending_approval_tickets,
    request_human_approval,
    track_cost_budget,
    verify_approval_token,
)
from .knowledge import query_rag_knowledge
from .triage import complete_event, poll_event_queue, push_event, release_event

#: Every tool returns a JSON object. Declaring it explicitly lets clients on
#: protocol 2025-06-18 consume ``structuredContent`` without guessing.
OBJECT_OUTPUT: dict[str, Any] = {"type": "object"}

TOOLS: list[Tool] = [
    Tool(
        name="poll_event_queue",
        description=(
            "Claim unprocessed events from the proactive triage queue and take a "
            "time-boxed lease on each. Events whose lease lapses return to the "
            "queue automatically, so a crashed agent does not strand work."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "queue_name": {"type": "string", "default": "default", "maxLength": 128},
                "max_items": {"type": "integer", "default": 5, "minimum": 1, "maximum": 100},
                "filter_severity": {
                    "type": "string",
                    "enum": ["all", "low", "medium", "high", "critical"],
                    "default": "all",
                },
                "lease_seconds": {
                    "type": "integer",
                    "default": 300,
                    "minimum": 30,
                    "maximum": 86400,
                },
            },
            "additionalProperties": False,
        },
        outputSchema=OBJECT_OUTPUT,
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False},
    ),
    Tool(
        name="complete_event",
        description=(
            "Settle a claimed event with an outcome and an optional note. Use this "
            "once triage of an event has finished."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "maxLength": 64},
                "outcome": {
                    "type": "string",
                    "enum": ["PROCESSED", "ESCALATED", "DISCARDED"],
                    "default": "PROCESSED",
                },
                "note": {"type": "string", "default": "", "maxLength": 500},
            },
            "required": ["event_id"],
            "additionalProperties": False,
        },
        outputSchema=OBJECT_OUTPUT,
        annotations={"destructiveHint": False, "idempotentHint": True},
    ),
    Tool(
        name="release_event",
        description=(
            "Return a claimed event to the unprocessed pool without settling it, so "
            "another worker can pick it up immediately instead of waiting for the "
            "lease to lapse."
        ),
        inputSchema={
            "type": "object",
            "properties": {"event_id": {"type": "string", "maxLength": 64}},
            "required": ["event_id"],
            "additionalProperties": False,
        },
        outputSchema=OBJECT_OUTPUT,
        annotations={"destructiveHint": False, "idempotentHint": True},
    ),
    Tool(
        name="push_event",
        description=(
            "Record an observation the agent made onto the triage queue so it "
            "becomes visible to other workers. Rejected when the queue is full."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "maxLength": 128},
                "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                "payload": {"type": "object"},
                "source": {
                    "type": "string",
                    "default": "agent_proactive_runtime",
                    "maxLength": 128,
                },
            },
            "required": ["event_type", "severity", "payload"],
            "additionalProperties": False,
        },
        outputSchema=OBJECT_OUTPUT,
        annotations={"destructiveHint": False, "idempotentHint": False},
    ),
    Tool(
        name="evaluate_document_compliance",
        description=(
            "Check an extracted document against a declared schema. Reports missing "
            "required fields, pattern violations, a confidence score, and a triage "
            "verdict. This is deterministic field validation over regex rules, not "
            "document understanding."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "document_payload": {
                    "type": "object",
                    "description": "Key-value fields extracted from the document.",
                },
                "schema_type": {
                    "type": "string",
                    "enum": ["asset_handover", "it_security_audit"],
                    "default": "asset_handover",
                },
                "strict_mode": {
                    "type": "boolean",
                    "default": True,
                    "description": "When true a pattern violation fails the document; when false it is downgraded to a warning.",
                },
            },
            "required": ["document_payload"],
            "additionalProperties": False,
        },
        outputSchema=OBJECT_OUTPUT,
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    ),
    Tool(
        name="query_rag_knowledge",
        description=(
            "Rank the built-in knowledge corpus against a query using sparse "
            "TF-IDF vectors and cosine similarity. Lexical rather than semantic: it "
            "matches vocabulary, so paraphrased queries retrieve poorly. Returns "
            "measured retrieval latency and an explicit grounding verdict."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                "top_k": {"type": "integer", "default": 3, "minimum": 1, "maximum": 25},
                "min_score_threshold": {
                    "type": "number",
                    "default": 0.10,
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        outputSchema=OBJECT_OUTPUT,
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
    ),
    Tool(
        name="request_human_approval",
        description=(
            "Park a sensitive action behind a human decision and return an "
            "authorization ticket. The confirmation code is never returned here: it "
            "must be supplied by an authorized human over an authenticated "
            "out-of-band channel, otherwise the gate proves nothing."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "action_name": {"type": "string", "maxLength": 128},
                "action_parameters": {"type": "object"},
                "rationale": {"type": "string", "minLength": 1, "maxLength": 2000},
                "urgency": {
                    "type": "string",
                    "enum": ["low", "normal", "high"],
                    "default": "normal",
                },
                "ttl_hours": {"type": "integer", "default": 24, "minimum": 1, "maximum": 168},
            },
            "required": ["action_name", "action_parameters", "rationale"],
            "additionalProperties": False,
        },
        outputSchema=OBJECT_OUTPUT,
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False},
    ),
    Tool(
        name="verify_approval_token",
        description=(
            "Verify a supervisor's confirmation code against a ticket and consume the "
            "ticket on success. The code is bound to the action name, a digest of the "
            "action parameters, and the expiry, and each ticket is single-use."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "maxLength": 64},
                "confirmation_code": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 256,
                    "description": "Hyphen grouping is optional; the code is case-insensitive.",
                },
            },
            "required": ["ticket_id", "confirmation_code"],
            "additionalProperties": False,
        },
        outputSchema=OBJECT_OUTPUT,
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    ),
    Tool(
        name="track_cost_budget",
        description=(
            "Book token spend against a session budget. Once a session exceeds its "
            "budget the server refuses further tool calls for it until the budget is "
            "raised; enforcement is server-side, not advisory."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "maxLength": 128},
                "prompt_tokens": {"type": "integer", "minimum": 0},
                "completion_tokens": {"type": "integer", "minimum": 0},
                "model_name": {"type": "string", "default": "gemini-2.5-flash", "maxLength": 128},
                "session_budget_usd": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "Session ceiling in USD. Applies immediately, including mid-session.",
                },
            },
            "required": ["session_id", "prompt_tokens", "completion_tokens"],
            "additionalProperties": False,
        },
        outputSchema=OBJECT_OUTPUT,
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False},
    ),
    Tool(
        name="set_active_session",
        description=(
            "Select which session the server's budget guard charges. The server "
            "refuses non-guardrail tool calls for any session that has exhausted its "
            "budget."
        ),
        inputSchema={
            "type": "object",
            "properties": {"session_id": {"type": "string", "maxLength": 128}},
            "required": ["session_id"],
            "additionalProperties": False,
        },
        outputSchema=OBJECT_OUTPUT,
        annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True},
    ),
]

TOOL_HANDLERS: dict[str, Callable[..., Any]] = {
    "poll_event_queue": poll_event_queue,
    "complete_event": complete_event,
    "release_event": release_event,
    "push_event": push_event,
    "evaluate_document_compliance": evaluate_document_compliance,
    "query_rag_knowledge": query_rag_knowledge,
    "request_human_approval": request_human_approval,
    "verify_approval_token": verify_approval_token,
    "track_cost_budget": track_cost_budget,
    "set_active_session": lambda session_id: _set_active_session(session_id),
}

#: Tools that stay callable after a session exhausts its budget, so the agent can
#: still inspect and repair its own accounting instead of dead-ending.
BUDGET_EXEMPT_TOOLS = frozenset(
    {"track_cost_budget", "set_active_session", "request_human_approval"}
)

#: Injected by the server so the active session is owned in one place.
_ACTIVE_SESSION_ID = "default"


def _set_active_session(session_id: str) -> dict[str, Any]:
    global _ACTIVE_SESSION_ID
    previous = _ACTIVE_SESSION_ID
    _ACTIVE_SESSION_ID = session_id
    return {
        "status": "OK",
        "previous_session_id": previous,
        "active_session_id": session_id,
        "budget_status": COST_GUARD.status(session_id),
    }


def get_active_session() -> str:
    return _ACTIVE_SESSION_ID


def set_active_session_id(session_id: str) -> None:
    global _ACTIVE_SESSION_ID
    _ACTIVE_SESSION_ID = session_id


def enforce_budget(session_id: str | None = None) -> None:
    """Raise :class:`BudgetExceeded` when the session has no budget remaining."""
    COST_GUARD.enforce(session_id or _ACTIVE_SESSION_ID)


def list_tool_names() -> list[str]:
    return [tool.name for tool in TOOLS]


def approval_overview() -> dict[str, Any]:
    return pending_approval_tickets()


__all__ = [
    "TOOLS",
    "TOOL_HANDLERS",
    "BUDGET_EXEMPT_TOOLS",
    "ToolInputError",
    "BudgetExceeded",
    "dispatch_tool",
    "enforce_budget",
    "get_active_session",
    "set_active_session_id",
    "list_tool_names",
    "approval_overview",
]


def dispatch_tool(name: str, arguments: dict[str, Any] | None = None) -> Any:
    """
    Validate arguments and invoke a tool handler.

    Raises :class:`ToolInputError` when the tool is unknown or the arguments
    violate the declared schema; the server maps that to JSON-RPC
    ``Invalid params``.
    """
    validated = validate_arguments(name, arguments)
    handler = TOOL_HANDLERS.get(name)
    if handler is None:  # pragma: no cover - registry is validated at import
        raise ToolInputError(f"Tool '{name}' not found.")
    return handler(**validated)
