"""
Declared tool input schemas, enforced at the protocol boundary.

The JSON Schema advertised through ``tools/list`` describes the contract to the
client and to the model. This module enforces that same contract server-side
with pydantic, so a malformed or hostile ``tools/call`` is rejected with a
JSON-RPC ``Invalid params`` error instead of surfacing later as a Python
``TypeError``.

Both layers are kept in sync deliberately: ``extra="forbid"`` means a client
that sends an undeclared argument is rejected rather than silently ignored.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Severity = Literal["low", "medium", "high", "critical"]
Urgency = Literal["low", "normal", "high"]


class _Args(BaseModel):
    """Base config shared by every argument model."""

    model_config = ConfigDict(extra="forbid")


class PollEventQueueArgs(_Args):
    queue_name: str = Field("default", min_length=1, max_length=128)
    max_items: int = Field(5, ge=1, le=100)
    filter_severity: Literal["all", "low", "medium", "high", "critical"] = "all"
    lease_seconds: int = Field(300, ge=30, le=86_400)


class CompleteEventArgs(_Args):
    event_id: str = Field(min_length=1, max_length=64)
    outcome: Literal["PROCESSED", "ESCALATED", "DISCARDED"] = "PROCESSED"
    note: str = Field("", max_length=500)


class ReleaseEventArgs(_Args):
    event_id: str = Field(min_length=1, max_length=64)


class PushEventArgs(_Args):
    event_type: str = Field(min_length=1, max_length=128)
    severity: Severity
    payload: dict[str, Any]
    source: str = Field("agent_proactive_runtime", max_length=128)


class EvaluateDocumentComplianceArgs(_Args):
    document_payload: dict[str, Any]
    schema_type: Literal["asset_handover", "it_security_audit"] = "asset_handover"
    strict_mode: bool = True


class QueryRagKnowledgeArgs(_Args):
    query: str = Field(min_length=1, max_length=2_000)
    top_k: int = Field(3, ge=1, le=25)
    min_score_threshold: float = Field(0.10, ge=0.0, le=1.0)


class RequestHumanApprovalArgs(_Args):
    action_name: str = Field(min_length=1, max_length=128)
    action_parameters: dict[str, Any]
    rationale: str = Field(min_length=1, max_length=2_000)
    urgency: Urgency = "normal"
    ttl_hours: int = Field(24, ge=1, le=168)


class VerifyApprovalTokenArgs(_Args):
    ticket_id: str = Field(min_length=1, max_length=64)
    confirmation_code: str = Field(min_length=1, max_length=256)


class TrackCostBudgetArgs(_Args):
    session_id: str = Field(min_length=1, max_length=128)
    prompt_tokens: int = Field(ge=0, le=100_000_000)
    completion_tokens: int = Field(ge=0, le=100_000_000)
    model_name: str = Field("gemini-2.5-flash", min_length=1, max_length=128)
    session_budget_usd: float | None = Field(None, gt=0.0, le=1_000_000.0)


class SetActiveSessionArgs(_Args):
    session_id: str = Field(min_length=1, max_length=128)


ARG_MODELS: dict[str, type[_Args]] = {
    "poll_event_queue": PollEventQueueArgs,
    "complete_event": CompleteEventArgs,
    "release_event": ReleaseEventArgs,
    "push_event": PushEventArgs,
    "evaluate_document_compliance": EvaluateDocumentComplianceArgs,
    "query_rag_knowledge": QueryRagKnowledgeArgs,
    "request_human_approval": RequestHumanApprovalArgs,
    "verify_approval_token": VerifyApprovalTokenArgs,
    "track_cost_budget": TrackCostBudgetArgs,
    "set_active_session": SetActiveSessionArgs,
}


class ToolInputError(ValueError):
    """
    Raised when tool arguments do not satisfy the declared schema.

    Carries a machine-readable ``problems`` list so the caller is told exactly
    which field failed and why, rather than only that something did.
    """

    def __init__(self, message: str, problems: list[dict[str, str]] | None = None):
        super().__init__(message)
        self.problems: list[dict[str, str]] = problems or []


def _format_errors(exc: ValidationError) -> list[dict[str, str]]:
    formatted: list[dict[str, str]] = []
    for err in exc.errors():
        location = ".".join(str(part) for part in err["loc"]) or "<root>"
        formatted.append({"field": location, "error": err["msg"], "type": err["type"]})
    return formatted


def validate_arguments(tool_name: str, arguments: Any) -> dict[str, Any]:
    """
    Validate and normalise the ``arguments`` object for ``tool_name``.

    Returns keyword arguments ready to splat into the tool handler, with
    defaults applied. Raises :class:`ToolInputError` with a machine-readable
    ``problems`` list on any schema violation.
    """
    model = ARG_MODELS.get(tool_name)
    if model is None:
        raise ToolInputError(
            f"Tool '{tool_name}' not found.",
            problems=[{"field": "<tool>", "error": "unknown tool", "type": "unknown_tool"}],
        )

    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ToolInputError(
            "Tool arguments must be a JSON object.",
            problems=[{"field": "<root>", "error": "expected object", "type": "type_error"}],
        )

    try:
        parsed = model.model_validate(arguments)
    except ValidationError as exc:
        raise ToolInputError(
            f"Invalid arguments for tool '{tool_name}'.",
            problems=_format_errors(exc),
        ) from exc

    return parsed.model_dump()
