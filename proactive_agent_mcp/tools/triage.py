"""
Proactive Event Queue & Task Inspection Tooling.
Enables agents to autonomously discover and triage incoming events without user prompting.
"""

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional

# In-memory mock queue state (persisted per server lifecycle)
_MOCK_EVENT_STORE: List[Dict[str, Any]] = [
    {
        "id": "evt-9041",
        "timestamp": "2026-09-24T04:15:00Z",
        "source": "ingestion_observer",
        "severity": "high",
        "type": "UNVERIFIED_ASSET_HANDOVER",
        "payload": {
            "document_id": "doc-handover-8821.pdf",
            "employee_id": "EMP-4102",
            "device_serial": "PF-20X9-A089",
            "status": "pending_validation"
        },
        "status": "UNPROCESSED"
    },
    {
        "id": "evt-9042",
        "timestamp": "2026-09-24T04:18:30Z",
        "source": "network_sentinel",
        "severity": "medium",
        "type": "VPN_POLICY_ANOMALY",
        "payload": {
            "endpoint_id": "WS-TAGUIG-042",
            "ip_range": "10.240.12.0/24",
            "issue": "mismatched_ad_group_membership"
        },
        "status": "UNPROCESSED"
    },
    {
        "id": "evt-9043",
        "timestamp": "2026-09-24T04:22:10Z",
        "source": "heartbeat_monitor",
        "severity": "low",
        "type": "SERVICE_HEALTH_CHECK",
        "payload": {
            "service": "documind_vector_indexer",
            "latency_ms": 6.8,
            "status": "HEALTHY"
        },
        "status": "UNPROCESSED"
    }
]


def poll_event_queue(
    queue_name: str = "default",
    max_items: int = 5,
    filter_severity: str = "all"
) -> Dict[str, Any]:
    """
    Poll the proactive event queue for unhandled items requiring autonomous agent intervention.
    """
    valid_severities = {"all", "low", "medium", "high", "critical"}
    if filter_severity not in valid_severities:
        filter_severity = "all"

    matched = []
    for item in _MOCK_EVENT_STORE:
        if item["status"] != "UNPROCESSED":
            continue
        if filter_severity != "all" and item["severity"] != filter_severity:
            continue
        matched.append(item)
        if len(matched) >= max_items:
            break

    # Mark returned items as CLAIMED
    for m in matched:
        m["status"] = "CLAIMED"
        m["claimed_at"] = datetime.now(timezone.utc).isoformat()

    return {
        "queue_name": queue_name,
        "polled_at": datetime.now(timezone.utc).isoformat(),
        "total_unprocessed_found": len(matched),
        "items": matched,
        "action_required": len(matched) > 0,
        "recommended_next_step": "Dispatch evaluate_document_compliance for doc payloads or triage alerts." if matched else "Sleep until next scheduled poll."
    }


def push_event(
    event_type: str,
    severity: str,
    payload: Dict[str, Any],
    source: str = "agent_proactive_runtime"
) -> Dict[str, Any]:
    """
    Pushes an event into the server's internal observation queue.
    """
    evt_id = f"evt-{uuid.uuid4().hex[:6]}"
    record = {
        "id": evt_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "severity": severity,
        "type": event_type,
        "payload": payload,
        "status": "UNPROCESSED"
    }
    _MOCK_EVENT_STORE.append(record)
    return {"status": "SUCCESS", "event_id": evt_id, "record": record}
