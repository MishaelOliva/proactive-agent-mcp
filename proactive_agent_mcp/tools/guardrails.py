"""
Safety Guardrails, Cost Management & Human-in-the-Loop (HITL) Tooling.
Enforces execution boundaries, token spend caps, and authorization tickets.
"""

from datetime import datetime, timezone, timedelta
import hashlib
import hmac
import uuid
from typing import Any, Dict, Optional

# Secret key for HMAC token signing (in production loaded from environment)
_SIGNING_SECRET = b"proactive-agent-mcp-internal-secret-2026"

# In-memory approval ticket registry
_APPROVAL_TICKETS: Dict[str, Dict[str, Any]] = {}

# In-memory token budget registry by session
_SESSION_BUDGETS: Dict[str, Dict[str, Any]] = {}

# Approximate token costs per 1,000 tokens (USD)
MODEL_PRICING = {
    "gemini-1.5-flash": {"prompt": 0.000075, "completion": 0.00030},
    "gemini-1.5-pro": {"prompt": 0.00125, "completion": 0.00500},
    "claude-3-5-sonnet": {"prompt": 0.00300, "completion": 0.01500},
    "gpt-4o": {"prompt": 0.00250, "completion": 0.01000},
    "local-ollama": {"prompt": 0.0, "completion": 0.0}
}


def _generate_hmac_token(ticket_id: str, action: str) -> str:
    msg = f"{ticket_id}:{action}".encode("utf-8")
    return hmac.new(_SIGNING_SECRET, msg, hashlib.sha256).hexdigest()[:12].upper()


def request_human_approval(
    action_name: str,
    action_parameters: Dict[str, Any],
    rationale: str,
    urgency: str = "normal"
) -> Dict[str, Any]:
    """
    Halts autonomous execution and requests explicit human authorization ticket for sensitive actions.
    """
    ticket_id = f"TICK-{uuid.uuid4().hex[:8].upper()}"
    token = _generate_hmac_token(ticket_id, action_name)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()

    ticket_record = {
        "ticket_id": ticket_id,
        "action_name": action_name,
        "action_parameters": action_parameters,
        "rationale": rationale,
        "urgency": urgency,
        "status": "AWAITING_HUMAN_CONFIRMATION",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,
        "expected_confirmation_code": token
    }
    _APPROVAL_TICKETS[ticket_id] = ticket_record

    return {
        "status": "APPROVAL_REQUIRED",
        "ticket_id": ticket_id,
        "message": f"Action '{action_name}' requires human approval before execution.",
        "confirmation_code": token,
        "expires_at": expires_at,
        "instructions": f"Human supervisor must review rationale and provide token '{token}' to continue."
    }


def verify_approval_token(
    ticket_id: str,
    confirmation_code: str
) -> Dict[str, Any]:
    """
    Verifies that a human has authorized an awaiting execution ticket.
    """
    if ticket_id not in _APPROVAL_TICKETS:
        return {"authorized": False, "error": f"Ticket '{ticket_id}' not found."}

    ticket = _APPROVAL_TICKETS[ticket_id]
    if ticket["status"] == "EXECUTED":
        return {"authorized": False, "error": f"Ticket '{ticket_id}' has already been consumed."}

    if confirmation_code.strip().upper() != ticket["expected_confirmation_code"]:
        return {"authorized": False, "error": "Invalid confirmation code. Authorization rejected."}

    ticket["status"] = "EXECUTED"
    ticket["executed_at"] = datetime.now(timezone.utc).isoformat()

    return {
        "authorized": True,
        "ticket_id": ticket_id,
        "action_name": ticket["action_name"],
        "action_parameters": ticket["action_parameters"],
        "status": "AUTHORIZED_FOR_DISPATCH"
    }


def track_cost_budget(
    session_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    model_name: str = "gemini-1.5-flash",
    session_budget_usd: float = 5.0
) -> Dict[str, Any]:
    """
    Tracks real-time token spend, prevents runaway agent loops, and enforces budget caps.
    """
    if session_id not in _SESSION_BUDGETS:
        _SESSION_BUDGETS[session_id] = {
            "session_id": session_id,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_cost_usd": 0.0,
            "session_budget_usd": session_budget_usd,
            "calls_recorded": 0
        }

    rates = MODEL_PRICING.get(model_name, MODEL_PRICING["gemini-1.5-flash"])
    call_cost = ((prompt_tokens / 1000.0) * rates["prompt"]) + ((completion_tokens / 1000.0) * rates["completion"])

    rec = _SESSION_BUDGETS[session_id]
    rec["total_prompt_tokens"] += prompt_tokens
    rec["total_completion_tokens"] += completion_tokens
    rec["total_cost_usd"] = round(rec["total_cost_usd"] + call_cost, 6)
    rec["calls_recorded"] += 1

    remaining_budget = round(rec["session_budget_usd"] - rec["total_cost_usd"], 6)
    budget_exceeded = remaining_budget <= 0.0

    return {
        "session_id": session_id,
        "model_name": model_name,
        "call_cost_usd": round(call_cost, 6),
        "total_cost_usd": rec["total_cost_usd"],
        "remaining_budget_usd": max(0.0, remaining_budget),
        "total_tokens_consumed": rec["total_prompt_tokens"] + rec["total_completion_tokens"],
        "budget_exceeded": budget_exceeded,
        "status": "HALT_BUDGET_EXCEEDED" if budget_exceeded else "OK"
    }
