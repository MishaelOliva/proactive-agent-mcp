"""
Tool registry and dispatcher for Proactive Agent MCP Server.
"""

from typing import Any, Callable, Dict, List, Tuple
from ..protocol import Tool
from .triage import poll_event_queue, push_event
from .compliance import evaluate_document_compliance
from .knowledge import query_rag_knowledge
from .guardrails import request_human_approval, verify_approval_token, track_cost_budget

TOOLS: List[Tool] = [
    Tool(
        name="poll_event_queue",
        description="Autonomously poll unhandled events, document drops, and triage queues without waiting for user requests.",
        inputSchema={
            "type": "object",
            "properties": {
                "queue_name": {"type": "string", "description": "Queue identifier to poll.", "default": "default"},
                "max_items": {"type": "integer", "description": "Maximum events to claim.", "default": 5},
                "filter_severity": {"type": "string", "enum": ["all", "low", "medium", "high", "critical"], "default": "all"}
            }
        }
    ),
    Tool(
        name="evaluate_document_compliance",
        description="Evaluate document structure, mandatory fields, and regex policies with confidence scoring.",
        inputSchema={
            "type": "object",
            "properties": {
                "document_payload": {"type": "object", "description": "Key-value dictionary of extracted document fields."},
                "schema_type": {"type": "string", "enum": ["asset_handover", "it_security_audit"], "default": "asset_handover"},
                "strict_mode": {"type": "boolean", "default": True}
            },
            "required": ["document_payload"]
        }
    ),
    Tool(
        name="query_rag_knowledge",
        description="Search enterprise knowledge base using semantic vector retrieval and cosine similarity ranking.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language query."},
                "top_k": {"type": "integer", "description": "Number of top matching chunks.", "default": 3},
                "min_score_threshold": {"type": "number", "description": "Minimum similarity score threshold.", "default": 0.3}
            },
            "required": ["query"]
        }
    ),
    Tool(
        name="request_human_approval",
        description="Create an authorization ticket for high-stakes actions requiring Human-in-the-Loop review.",
        inputSchema={
            "type": "object",
            "properties": {
                "action_name": {"type": "string", "description": "Name of the sensitive action."},
                "action_parameters": {"type": "object", "description": "Parameters proposed for execution."},
                "rationale": {"type": "string", "description": "Detailed explanation of why this action is required."},
                "urgency": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"}
            },
            "required": ["action_name", "action_parameters", "rationale"]
        }
    ),
    Tool(
        name="verify_approval_token",
        description="Verify human approval authorization code before dispatching sensitive actions.",
        inputSchema={
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "Ticket identifier (e.g. TICK-XXXX)."},
                "confirmation_code": {"type": "string", "description": "HMAC token provided by human supervisor."}
            },
            "required": ["ticket_id", "confirmation_code"]
        }
    ),
    Tool(
        name="track_cost_budget",
        description="Track real-time token spend per session and enforce cost budgets across LLM providers.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session tracking ID."},
                "prompt_tokens": {"type": "integer", "description": "Tokens consumed in prompt."},
                "completion_tokens": {"type": "integer", "description": "Tokens consumed in generation."},
                "model_name": {"type": "string", "description": "Model identifier.", "default": "gemini-1.5-flash"},
                "session_budget_usd": {"type": "number", "description": "Budget limit in USD.", "default": 5.0}
            },
            "required": ["session_id", "prompt_tokens", "completion_tokens"]
        }
    )
]

TOOL_HANDLERS: Dict[str, Callable[..., Any]] = {
    "poll_event_queue": poll_event_queue,
    "evaluate_document_compliance": evaluate_document_compliance,
    "query_rag_knowledge": query_rag_knowledge,
    "request_human_approval": request_human_approval,
    "verify_approval_token": verify_approval_token,
    "track_cost_budget": track_cost_budget
}


def dispatch_tool(name: str, arguments: Dict[str, Any]) -> Any:
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        raise ValueError(f"Tool '{name}' not found.")
    return handler(**arguments)
