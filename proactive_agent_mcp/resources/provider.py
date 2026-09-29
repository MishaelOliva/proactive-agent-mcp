"""
Resource providers for Proactive Agent MCP Server.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import time
from typing import Any

from ..protocol import Resource

logger = logging.getLogger(__name__)

_START_MONOTONIC = time.monotonic()

RESOURCES: list[Resource] = [
    Resource(
        uri="system://health",
        name="System Health & Runtime Telemetry",
        description=(
            "Uptime, process resource usage, negotiated protocol version, budget "
            "and approval-ticket counters, and triage queue depth."
        ),
        mimeType="application/json",
    ),
    Resource(
        uri="compliance://standards",
        name="Organizational Compliance Policies",
        description=(
            "Compliance requirements for asset onboarding, agent governance, and data handling."
        ),
        mimeType="text/markdown",
    ),
]


def _peak_memory_mb() -> float | None:
    """
    Peak resident set size in megabytes, or ``None`` where unavailable.

    ``ru_maxrss`` is reported in kilobytes on Linux and in bytes on macOS, so
    the unit is normalised per platform. Windows has no ``resource`` module, and
    rather than guess we report nothing at all.
    """
    try:
        import resource
    except ImportError:
        return None

    raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return round(raw / (1024 * 1024), 2)
    return round(raw / 1024, 2)


def _health_payload() -> dict[str, Any]:
    # Imported here rather than at module scope: the tools package imports this
    # provider's package, so a top-level import would be circular.
    from ..tools import get_active_session
    from ..tools.guardrails import COST_GUARD, pending_approval_tickets
    from ..tools.triage import queue_stats

    session_id = get_active_session()
    memory = _peak_memory_mb()
    approvals = pending_approval_tickets()

    payload: dict[str, Any] = {
        "server": "proactive-agent-mcp",
        "status": "HEALTHY",
        "uptime_seconds": round(time.monotonic() - _START_MONOTONIC, 2),
        "host_os": f"{platform.system()} {platform.release()}",
        "python_version": platform.python_version(),
        "pid": os.getpid(),
        "active_session_id": session_id,
        "budget": COST_GUARD.status(session_id),
        "approvals": approvals,
        "event_queue": queue_stats(),
        "signing_secret_is_ephemeral": approvals["secret_is_ephemeral"],
    }

    if memory is not None:
        payload["peak_memory_mb"] = memory
    else:
        payload["peak_memory_mb"] = None
        payload["peak_memory_note"] = "Not reported on this platform."

    return payload


def read_resource(uri: str) -> dict[str, Any]:
    if uri == "system://health":
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(_health_payload(), indent=2, default=str),
                }
            ]
        }

    if uri == "compliance://standards":
        text = (
            "# Enterprise AI & Asset Compliance Standards\n"
            "\n"
            "1. **Asset handover:** Provisioned endpoints require disk encryption, a "
            "directory account binding, and a signed accountability record.\n"
            "2. **Agent governance:** Autonomous agents are limited to queue triage "
            "and schema validation. Destructive actions require a human approval "
            "ticket whose confirmation code is delivered out of band.\n"
            "3. **Data handling:** Credentials and identifiers must be redacted "
            "before they reach a third-party model endpoint.\n"
        )
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": text}]}

    raise ValueError(f"Resource with URI '{uri}' not found.")
