"""
Proactive event queue with a claim / complete / release lifecycle.

An agent polls for unprocessed events and receives a *lease* on each one. A
lease is what makes the queue safe to poll from a process that can crash: if the
agent dies mid-triage, the lease lapses and the event returns to the queue
instead of being stranded in ``CLAIMED`` forever.

Storage is an in-process list, which is appropriate for a reference
implementation and for local development. It does not survive a restart and is
not shared between replicas.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

#: Bounded so a long-lived process cannot grow without limit.
_MAX_QUEUE_SIZE = 10_000

_MOCK_EVENT_STORE: list[dict[str, Any]] = [
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
            "status": "pending_validation",
        },
        "status": "UNPROCESSED",
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
            "issue": "mismatched_ad_group_membership",
        },
        "status": "UNPROCESSED",
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
            "status": "HEALTHY",
        },
        "status": "UNPROCESSED",
    },
]

_TERMINAL_STATUSES = frozenset({"PROCESSED", "ESCALATED", "DISCARDED"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _reclaim_expired_leases() -> int:
    """Return events whose lease lapsed to the unprocessed pool."""
    now = _now()
    reclaimed = 0
    for item in _MOCK_EVENT_STORE:
        if item["status"] != "CLAIMED":
            continue
        lease_expires = item.get("lease_expires_at")
        if lease_expires and now > datetime.fromisoformat(lease_expires):
            item["status"] = "UNPROCESSED"
            item.pop("claimed_at", None)
            item.pop("lease_expires_at", None)
            item["lease_expired_count"] = item.get("lease_expired_count", 0) + 1
            reclaimed += 1
    return reclaimed


def _find(event_id: str) -> dict[str, Any] | None:
    for item in _MOCK_EVENT_STORE:
        if item["id"] == event_id:
            return item
    return None


def poll_event_queue(
    queue_name: str = "default",
    max_items: int = 5,
    filter_severity: str = "all",
    lease_seconds: int = 300,
) -> dict[str, Any]:
    """
    Claim up to ``max_items`` unprocessed events and take a lease on each.

    Events are returned in queue order, filtered by severity. An invalid
    severity is rejected by argument validation before this function runs, so
    the value is known-good here.
    """
    reclaimed = _reclaim_expired_leases()
    now = _now()
    lease_expires = now + timedelta(seconds=lease_seconds)

    matched: list[dict[str, Any]] = []
    for item in _MOCK_EVENT_STORE:
        if item["status"] != "UNPROCESSED":
            continue
        if filter_severity != "all" and item["severity"] != filter_severity:
            continue
        matched.append(item)
        if len(matched) >= max_items:
            break

    for item in matched:
        item["status"] = "CLAIMED"
        item["claimed_at"] = now.isoformat()
        item["lease_expires_at"] = lease_expires.isoformat()

    return {
        "queue_name": queue_name,
        "polled_at": now.isoformat(),
        "lease_seconds": lease_seconds,
        "lease_expires_at": lease_expires.isoformat() if matched else None,
        "leases_reclaimed_this_poll": reclaimed,
        "total_unprocessed_found": len(matched),
        "items": matched,
        "action_required": len(matched) > 0,
        "recommended_next_step": (
            "Evaluate document payloads with evaluate_document_compliance, then "
            "settle each event with complete_event or release_event."
            if matched
            else "Nothing to do. Sleep until the next scheduled poll."
        ),
    }


def complete_event(
    event_id: str,
    outcome: str = "PROCESSED",
    note: str = "",
) -> dict[str, Any]:
    """Settle a claimed event, or push a fresh observation onto the queue."""
    item = _find(event_id)
    if item is None:
        return {"status": "NOT_FOUND", "error": f"Event '{event_id}' not found."}

    if item["status"] not in {"CLAIMED", "UNPROCESSED"}:
        return {
            "status": "CONFLICT",
            "error": (
                f"Event '{event_id}' is in state '{item['status']}' and cannot be settled again."
            ),
        }

    now = _now().isoformat()
    item["status"] = outcome
    item["settled_at"] = now
    item.pop("lease_expires_at", None)
    if note:
        item["note"] = note

    return {"status": "OK", "event_id": event_id, "outcome": outcome, "settled_at": now}


def release_event(event_id: str) -> dict[str, Any]:
    """Hand a claimed event back to the queue without settling it."""
    item = _find(event_id)
    if item is None:
        return {"status": "NOT_FOUND", "error": f"Event '{event_id}' not found."}

    if item["status"] != "CLAIMED":
        return {
            "status": "CONFLICT",
            "error": f"Event '{event_id}' is not currently claimed.",
        }

    item["status"] = "UNPROCESSED"
    item.pop("claimed_at", None)
    item.pop("lease_expires_at", None)
    item["released_count"] = item.get("released_count", 0) + 1

    return {"status": "OK", "event_id": event_id, "released": True}


def push_event(
    event_type: str,
    severity: str,
    payload: dict[str, Any],
    source: str = "agent_proactive_runtime",
) -> dict[str, Any]:
    """Record an observation the agent made, so it becomes visible to the queue."""
    if len(_MOCK_EVENT_STORE) >= _MAX_QUEUE_SIZE:
        return {
            "status": "REJECTED",
            "error": f"Queue is full ({_MAX_QUEUE_SIZE} events); drain it first.",
        }

    event_id = f"evt-{uuid.uuid4().hex[:6]}"
    record = {
        "id": event_id,
        "timestamp": _now().isoformat(),
        "source": source,
        "severity": severity,
        "type": event_type,
        "payload": payload,
        "status": "UNPROCESSED",
    }
    _MOCK_EVENT_STORE.append(record)
    return {"status": "SUCCESS", "event_id": event_id, "record": record}


def queue_stats() -> dict[str, Any]:
    """Counts by status, for the health resource and operational tooling."""
    _reclaim_expired_leases()
    counts: dict[str, int] = {}
    for item in _MOCK_EVENT_STORE:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {
        "total": len(_MOCK_EVENT_STORE),
        "by_status": counts,
        "unprocessed": counts.get("UNPROCESSED", 0),
        "claimed": counts.get("CLAIMED", 0),
        "max_size": _MAX_QUEUE_SIZE,
    }
