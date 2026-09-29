"""
Resource providers for Proactive Agent MCP Server.
"""

from datetime import datetime, timezone
import json
import platform
import time
from typing import Any, Dict, List
from ..protocol import Resource

_START_TIME = time.time()

RESOURCES: List[Resource] = [
    Resource(
        uri="system://health",
        name="System Health & Daemon Telemetry",
        description="Live uptime, process memory, operating environment, and background health status.",
        mimeType="application/json"
    ),
    Resource(
        uri="compliance://standards",
        name="Organizational Compliance Policies",
        description="Formal compliance requirements for asset onboarding, security policies, and schema boundaries.",
        mimeType="text/markdown"
    )
]


def read_resource(uri: str) -> Dict[str, Any]:
    if uri == "system://health":
        uptime_sec = round(time.time() - _START_TIME, 2)
        content = {
            "server": "proactive-agent-mcp",
            "version": "1.0.0",
            "status": "HEALTHY",
            "uptime_seconds": uptime_sec,
            "host_os": f"{platform.system()} {platform.release()}",
            "python_version": platform.python_version(),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(content, indent=2)
                }
            ]
        }

    elif uri == "compliance://standards":
        text = """# Enterprise AI & Asset Compliance Standards (2026)
1. **Zero-Trust Asset Handover:** All provisioned endpoints must have BitLocker, Entra ID join, and verified signatures.
2. **Autonomous Agent Governance:** Proactive agents are restricted to read-only queue triage and schema drafting. Destructive mutations require HITL authorization tokens.
3. **Data Residency & Privacy:** Sensitive PII must be scrubbed prior to dispatching to external frontier model endpoints.
"""
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "text/markdown",
                    "text": text
                }
            ]
        }

    else:
        raise ValueError(f"Resource with URI '{uri}' not found.")
