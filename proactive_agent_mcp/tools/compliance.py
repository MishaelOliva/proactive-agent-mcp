"""
Document compliance evaluation.

Checks an extracted document against a declared schema and reports what is
missing, what fails a pattern, and how confident the evaluation is.

Scoring
-------
``confidence_score`` is the fraction of the schema's *required* fields that
present and satisfied their pattern:

    confidence = valid_fields / required_fields

A fully conforming document scores exactly ``1.0``. Pattern rules are
attributes of required fields rather than additional requirements, so counting
them again on top of ``required_fields`` would both double-count them and put a
ceiling below 1.0 on a perfect document.
"""

from __future__ import annotations

import re
from typing import Any

SCHEMAS: dict[str, dict[str, Any]] = {
    "asset_handover": {
        "required_fields": ["employee_id", "serial_number", "department", "custody_date"],
        "patterns": {
            "employee_id": r"^EMP-\d{4,6}$",
            "serial_number": r"^[A-Z0-9-]{6,16}$",
            "custody_date": r"^\d{4}-\d{2}-\d{2}$",
        },
    },
    "it_security_audit": {
        "required_fields": ["endpoint_id", "os_version", "antivirus_status", "encryption_enabled"],
        "patterns": {
            "endpoint_id": r"^[A-Z0-9-_]{4,20}$",
        },
    },
}


def evaluate_document_compliance(
    document_payload: dict[str, Any],
    schema_type: str = "asset_handover",
    strict_mode: bool = True,
) -> dict[str, Any]:
    """
    Evaluate an extracted document against a compliance schema.

    Parameters
    ----------
    document_payload:
        Key/value pairs extracted from the document under review.
    schema_type:
        Which schema to evaluate against.
    strict_mode:
        When ``True`` (default) a pattern violation fails the document, matching
        the behaviour of a hard validation gate. When ``False`` pattern
        violations are reported as warnings and only absent required fields fail
        the document, which suits a first-pass triage sweep over noisy OCR.
    """
    if schema_type not in SCHEMAS:
        return {
            "schema_type": schema_type,
            "is_compliant": False,
            "error": (f"Unknown schema_type '{schema_type}'. Supported: {sorted(SCHEMAS)}"),
            "confidence_score": 0.0,
        }

    schema = SCHEMAS[schema_type]
    required: list[str] = schema["required_fields"]
    patterns: dict[str, str] = schema.get("patterns", {})

    missing_fields: list[str] = []
    pattern_violations: list[dict[str, str]] = []
    valid_fields: list[str] = []

    for field_name in required:
        # Strip before testing for emptiness: a whitespace-only OCR cell is
        # truthy in Python but is not a value.
        value = str(document_payload.get(field_name, "")).strip()
        if not value:
            missing_fields.append(field_name)
            continue

        pattern = patterns.get(field_name)
        if pattern and not re.match(pattern, value):
            pattern_violations.append(
                {"field": field_name, "value": value, "expected_pattern": pattern}
            )
            continue

        valid_fields.append(field_name)

    # Confidence is the share of required fields that fully passed. Optional
    # fields beyond the schema are not part of the denominator.
    confidence = len(valid_fields) / len(required) if required else 1.0

    # Strict mode treats a malformed value as a failure; relaxed mode only
    # requires the field to be present.
    blocking_violations = pattern_violations if strict_mode else []
    is_compliant = not missing_fields and not blocking_violations

    if is_compliant:
        risk_level = "LOW"
    elif len(missing_fields) > 1:
        risk_level = "HIGH"
    else:
        risk_level = "MEDIUM"

    result: dict[str, Any] = {
        "schema_type": schema_type,
        "strict_mode": strict_mode,
        "is_compliant": is_compliant,
        "confidence_score": round(confidence, 3),
        "required_fields": len(required),
        "valid_fields": valid_fields,
        "missing_fields": missing_fields,
        "pattern_violations": pattern_violations,
        "risk_level": risk_level,
        "triage_verdict": "APPROVED_AUTO_PASS" if is_compliant else "REQUIRES_HUMAN_CORRECTION",
    }

    if pattern_violations and not strict_mode:
        result["note"] = (
            "Pattern violations were downgraded to warnings because strict_mode is disabled."
        )

    return result
