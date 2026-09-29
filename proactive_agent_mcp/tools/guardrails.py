"""
Safety Guardrails: human-in-the-loop authorization and cost enforcement.

Human-in-the-loop approval
--------------------------
A sensitive action is parked in a *ticket* that carries a confirmation code
signed with HMAC-SHA256. The signed payload binds the ticket id, the action
name, a digest of the proposed action parameters, and the absolute expiry, so a
code minted for one action cannot be re-pointed at another, swapped for
different parameters, or replayed after the ticket expires.

Two properties are worth calling out:

1. The confirmation code is **recomputed** from the stored ticket at verification
   time rather than read from a stored "expected answer". A tampered ticket
   record therefore invalidates its own code instead of silently validating.
2. The signing secret comes from ``MCP_SIGNING_SECRET``. When that variable is
   absent the server generates a random ephemeral secret at start-up rather
   than falling back to a value published in this source tree. A hard-coded
   default secret would make every approval code forgeable by anyone who can
   read the repository, which would render the gate decorative.

.. warning::
   This is a worked *pattern* for gating autonomous actions, not a production
   identity or authorization system. A real deployment must additionally bind
   each approval to an authenticated human principal, persist tickets in a
   shared transactional store so restarts and replicas agree, and deliver the
   confirmation over an authenticated channel.

Cost enforcement
----------------
:class:`CostGuard` accumulates spend per session and is consulted by the server
*before* dispatching a tool. Once a session crosses its budget the server
refuses further work rather than returning a status string and trusting the
model to respect it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Signing secret
# --------------------------------------------------------------------------


def _load_signing_secret() -> tuple[bytes, bool]:
    """
    Return ``(secret, is_ephemeral)``.

    An unset ``MCP_SIGNING_SECRET`` produces a random per-process secret. This
    is the fail-closed choice: the server still works for local development,
    but approval codes can no longer be minted from knowledge of this repo.
    """
    raw = os.environ.get("MCP_SIGNING_SECRET")
    if raw and raw.strip():
        return raw.strip().encode("utf-8"), False

    logger.warning(
        "MCP_SIGNING_SECRET is not set; using a random ephemeral signing "
        "secret for this process. Approval tokens will not survive a restart "
        "and cannot be reproduced by third parties. Set MCP_SIGNING_SECRET "
        "explicitly for any non-local deployment."
    )
    return secrets.token_bytes(32), True


_SIGNING_SECRET, _SIGNING_SECRET_IS_EPHEMERAL = _load_signing_secret()

#: Bumped if the signed payload layout ever changes, so old codes stop matching.
_TOKEN_VERSION = "v1"

# --------------------------------------------------------------------------
# Approval tickets
# --------------------------------------------------------------------------

_APPROVAL_TICKETS: dict[str, dict[str, Any]] = {}
_TERMINAL_STATUSES = frozenset({"EXECUTED", "EXPIRED", "DENIED"})

#: Terminal tickets are dropped once they have been settled this long, which
#: keeps a long-lived process from growing without bound.
_TERMINAL_RETENTION = timedelta(hours=6)


def _canonical_params(action_parameters: dict[str, Any]) -> str:
    return json.dumps(action_parameters, sort_keys=True, separators=(",", ":"), default=str)


def _params_digest(action_parameters: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_params(action_parameters).encode("utf-8")).hexdigest()


def generate_confirmation_code(
    ticket_id: str,
    action_name: str,
    action_parameters: dict[str, Any],
    expires_at: str,
) -> str:
    """
    Build the HMAC-SHA256 confirmation code for a ticket.

    The full 256-bit digest is encoded rather than truncated: cutting a MAC
    down to a handful of hex characters is what turns an authorization token
    into a guessable one. The result is base32 and hyphen-grouped purely for
    legibility; :func:`normalize_confirmation_code` accepts any formatting.
    """
    message = "|".join(
        [_TOKEN_VERSION, ticket_id, action_name, _params_digest(action_parameters), expires_at]
    ).encode("utf-8")
    mac = hmac.new(_SIGNING_SECRET, message, hashlib.sha256).digest()
    b32 = base64.b32encode(mac).decode("ascii").rstrip("=")
    return "-".join(b32[i : i + 4] for i in range(0, len(b32), 4))


def normalize_confirmation_code(code: str) -> str:
    """Strip formatting so ``ABCD-EFGH`` and ``abcd efgh`` compare equal."""
    return code.strip().upper().replace("-", "").replace(" ", "")


def _sweep_tickets() -> None:
    """Expire overdue tickets and drop settled ones past the retention window."""
    now = datetime.now(timezone.utc)
    cutoff = now - _TERMINAL_RETENTION

    for ticket_id, ticket in list(_APPROVAL_TICKETS.items()):
        if ticket["status"] in _TERMINAL_STATUSES:
            if datetime.fromisoformat(ticket.get("settled_at", now.isoformat())) < cutoff:
                del _APPROVAL_TICKETS[ticket_id]
            continue
        if now > datetime.fromisoformat(ticket["expires_at"]):
            ticket["status"] = "EXPIRED"
            ticket["settled_at"] = now.isoformat()


def request_human_approval(
    action_name: str,
    action_parameters: dict[str, Any],
    rationale: str,
    urgency: str = "normal",
    ttl_hours: int = 24,
) -> dict[str, Any]:
    """
    Park a sensitive action behind a human decision and return the ticket.

    The confirmation code is deliberately **not** included in the response: it
    must reach the operator through an authenticated channel outside this
    agent's control, otherwise the agent could approve its own work.
    """
    _sweep_tickets()

    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=ttl_hours)).isoformat()
    ticket_id = f"TICK-{uuid.uuid4().hex[:8].upper()}"

    _APPROVAL_TICKETS[ticket_id] = {
        "ticket_id": ticket_id,
        "action_name": action_name,
        "action_parameters": action_parameters,
        "rationale": rationale,
        "urgency": urgency,
        "status": "AWAITING_HUMAN_CONFIRMATION",
        "created_at": now.isoformat(),
        "expires_at": expires_at,
    }

    return {
        "status": "APPROVAL_REQUIRED",
        "ticket_id": ticket_id,
        "action_name": action_name,
        "urgency": urgency,
        "message": (f"Action '{action_name}' is parked pending supervisor authorization."),
        "expires_at": expires_at,
        "ttl_hours": ttl_hours,
        "instructions": (
            "A human supervisor must review the action and rationale, then submit "
            f"the confirmation code for ticket '{ticket_id}' to verify_approval_token "
            "over an authenticated out-of-band channel. Do not attempt to derive or "
            "guess the code."
        ),
    }


def verify_approval_token(ticket_id: str, confirmation_code: str) -> dict[str, Any]:
    """
    Check a supervisor's confirmation code and consume the ticket on success.

    Enforces ticket existence, terminal state, expiry, and parameter binding, and
    compares codes in constant time.
    """
    _sweep_tickets()

    ticket = _APPROVAL_TICKETS.get(ticket_id)
    if ticket is None:
        return {
            "authorized": False,
            "error": f"Ticket '{ticket_id}' not found.",
            "reason": "NOT_FOUND",
        }

    if ticket["status"] == "EXECUTED":
        return {
            "authorized": False,
            "error": f"Ticket '{ticket_id}' has already been consumed.",
            "reason": "ALREADY_CONSUMED",
        }

    if ticket["status"] == "EXPIRED":
        return {
            "authorized": False,
            "error": f"Ticket '{ticket_id}' has expired.",
            "reason": "EXPIRED",
        }

    if datetime.now(timezone.utc) > datetime.fromisoformat(ticket["expires_at"]):
        ticket["status"] = "EXPIRED"
        ticket["settled_at"] = datetime.now(timezone.utc).isoformat()
        return {
            "authorized": False,
            "error": f"Ticket '{ticket_id}' has expired.",
            "reason": "EXPIRED",
        }

    # Recomputed rather than read back, so a mutated ticket record cannot
    # validate against a code captured before the mutation.
    expected = generate_confirmation_code(
        ticket["ticket_id"],
        ticket["action_name"],
        ticket["action_parameters"],
        ticket["expires_at"],
    )

    if not hmac.compare_digest(
        normalize_confirmation_code(confirmation_code),
        normalize_confirmation_code(expected),
    ):
        logger.warning("Rejected confirmation code for ticket %s", ticket_id)
        return {
            "authorized": False,
            "error": "Invalid confirmation code. Authorization rejected.",
            "reason": "INVALID_CODE",
        }

    now = datetime.now(timezone.utc)
    ticket["status"] = "EXECUTED"
    ticket["executed_at"] = now.isoformat()
    ticket["settled_at"] = now.isoformat()

    return {
        "authorized": True,
        "ticket_id": ticket_id,
        "action_name": ticket["action_name"],
        "action_parameters": ticket["action_parameters"],
        "executed_at": now.isoformat(),
        "status": "AUTHORIZED_FOR_DISPATCH",
    }


def pending_approval_tickets() -> dict[str, Any]:
    """Introspection helper for tests, the demo, and operational tooling."""
    _sweep_tickets()
    return {
        "total": len(_APPROVAL_TICKETS),
        "awaiting": sum(
            1 for t in _APPROVAL_TICKETS.values() if t["status"] == "AWAITING_HUMAN_CONFIRMATION"
        ),
        "secret_is_ephemeral": _SIGNING_SECRET_IS_EPHEMERAL,
    }


# --------------------------------------------------------------------------
# Cost guard
# --------------------------------------------------------------------------

#: Illustrative USD per 1,000 tokens. Real deployments should load these from a
#: pricing service; treat them as configuration, not as ground truth.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.0-flash": {"prompt": 0.00010, "completion": 0.00040},
    "gemini-1.5-flash": {"prompt": 0.000075, "completion": 0.00030},
    "claude-3-5-sonnet": {"prompt": 0.00300, "completion": 0.01500},
    "gpt-4o": {"prompt": 0.00250, "completion": 0.01000},
    "local-ollama": {"prompt": 0.0, "completion": 0.0},
}
PRICING_LAST_CHECKED = "2026-09"
_UNKNOWN_MODEL = "gemini-2.0-flash"

#: Per-session ceiling used when the caller does not supply one.
DEFAULT_SESSION_BUDGET_USD = float(os.environ.get("MCP_SESSION_BUDGET_USD", "5.0"))

#: Cap on retained sessions, so a long-lived process cannot grow without bound.
_MAX_TRACKED_SESSIONS = 500


class BudgetExceeded(RuntimeError):
    """Raised when a session has no budget left. Refused by the server."""

    def __init__(self, status: dict[str, Any]):
        super().__init__(status.get("reason", "session budget exceeded"))
        self.status = status


class CostGuard:
    """
    Accumulates token spend per session and decides whether work may proceed.

    The guard is consulted by the server before dispatch so that an exhausted
    budget actually stops work. Returning a status flag and hoping the model
    reads it is precisely the failure mode a budget guard exists to prevent.
    """

    def __init__(self, default_budget_usd: float = DEFAULT_SESSION_BUDGET_USD):
        self._default_budget_usd = default_budget_usd
        self._sessions: dict[str, dict[str, Any]] = {}

    def _resolve_budget(self, session_id: str, requested_budget: float | None) -> dict[str, Any]:
        record = self._sessions.get(session_id)
        if record is None:
            record = {
                "session_id": session_id,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_cost_usd": 0.0,
                "session_budget_usd": (
                    requested_budget if requested_budget is not None else self._default_budget_usd
                ),
                "calls_recorded": 0,
                "blocked": False,
            }
            self._sessions[session_id] = record
            self._evict_oldest_if_needed()
        elif requested_budget is not None and requested_budget != record["session_budget_usd"]:
            # Applied on every call, not just at creation, so tightening a budget
            # mid-session actually takes effect.
            record["session_budget_usd"] = requested_budget
            if record["total_cost_usd"] <= requested_budget:
                record["blocked"] = False
        return record

    def _evict_oldest_if_needed(self) -> None:
        if len(self._sessions) <= _MAX_TRACKED_SESSIONS:
            return
        oldest = sorted(self._sessions.items(), key=lambda kv: kv[1]["calls_recorded"])[0]
        self._sessions.pop(oldest[0], None)

    def rates_for(self, model_name: str) -> dict[str, float]:
        return MODEL_PRICING.get(model_name, MODEL_PRICING[_UNKNOWN_MODEL])

    def status(self, session_id: str, requested_budget: float | None = None) -> dict[str, Any]:
        record = self._resolve_budget(session_id, requested_budget)
        remaining = round(record["session_budget_usd"] - record["total_cost_usd"], 6)
        return {
            "session_id": session_id,
            "total_prompt_tokens": record["total_prompt_tokens"],
            "total_completion_tokens": record["total_completion_tokens"],
            "total_tokens_consumed": record["total_prompt_tokens"]
            + record["total_completion_tokens"],
            "total_cost_usd": record["total_cost_usd"],
            "session_budget_usd": record["session_budget_usd"],
            "remaining_budget_usd": max(0.0, remaining),
            "calls_recorded": record["calls_recorded"],
            "blocked": record["blocked"],
            "budget_exceeded": remaining <= 0.0,
        }

    def record(
        self,
        session_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        model_name: str = _UNKNOWN_MODEL,
        session_budget_usd: float | None = None,
    ) -> dict[str, Any]:
        """Book a call's cost against the session and return the new status."""
        record = self._resolve_budget(session_id, session_budget_usd)
        rates = self.rates_for(model_name)

        call_cost = (prompt_tokens / 1000.0) * rates["prompt"] + (
            completion_tokens / 1000.0
        ) * rates["completion"]

        record["total_prompt_tokens"] += prompt_tokens
        record["total_completion_tokens"] += completion_tokens
        record["total_cost_usd"] = round(record["total_cost_usd"] + call_cost, 6)
        record["calls_recorded"] += 1

        remaining = round(record["session_budget_usd"] - record["total_cost_usd"], 6)
        record["blocked"] = remaining <= 0.0

        return {
            "call_cost_usd": round(call_cost, 6),
            "model_name": model_name,
            "pricing_last_checked": PRICING_LAST_CHECKED,
            "status": "HALT_BUDGET_EXCEEDED" if record["blocked"] else "OK",
            **self.status(session_id),
        }

    def is_blocked(self, session_id: str) -> bool:
        return self._sessions.get(session_id, {}).get("blocked", False)

    def enforce(self, session_id: str) -> None:
        """Raise :class:`BudgetExceeded` when the session has no budget left."""
        if self.is_blocked(session_id):
            current = self.status(session_id)
            raise BudgetExceeded(
                {
                    "reason": "SESSION_BUDGET_EXCEEDED",
                    "session_id": session_id,
                    "error": (
                        f"Session '{session_id}' exceeded its token budget "
                        f"(${current['total_cost_usd']} spent of "
                        f"${current['session_budget_usd']}). Further tool calls are "
                        "refused until the budget is raised."
                    ),
                    **current,
                }
            )

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


#: Process-wide guard consulted by the server dispatcher.
COST_GUARD = CostGuard()


def track_cost_budget(
    session_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    model_name: str = _UNKNOWN_MODEL,
    session_budget_usd: float | None = None,
) -> dict[str, Any]:
    """
    Book a call's token spend against a session budget.

    Thin wrapper over the process-wide :data:`COST_GUARD`, which the server also
    consults directly when deciding whether to dispatch a tool at all.
    """
    return COST_GUARD.record(
        session_id=session_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        model_name=model_name,
        session_budget_usd=session_budget_usd,
    )
