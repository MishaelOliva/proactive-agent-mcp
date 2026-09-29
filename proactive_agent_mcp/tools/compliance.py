"""
Document Compliance & Structural Schema Evaluation Tooling.
Validates unstructured or semi-structured data against organizational compliance policies.
"""

from typing import Any, Dict, List
import re

SCHEMAS = {
    "asset_handover": {
        "required_fields": ["employee_id", "serial_number", "department", "custody_date"],
        "patterns": {
            "employee_id": r"^EMP-\d{4,6}$",
            "serial_number": r"^[A-Z0-9-]{6,16}$",
            "custody_date": r"^\d{4}-\d{2}-\d{2}$"
        }
    },
    "it_security_audit": {
        "required_fields": ["endpoint_id", "os_version", "antivirus_status", "encryption_enabled"],
        "patterns": {
            "endpoint_id": r"^[A-Z0-9-_]{4,20}$"
        }
    }
}


def evaluate_document_compliance(
    document_payload: Dict[str, Any],
    schema_type: str = "asset_handover",
    strict_mode: bool = True
) -> Dict[str, Any]:
    """
    Evaluates an extracted document against compliance schemas, outputting confidence and discrepancies.
    """
    if schema_type not in SCHEMAS:
        return {
            "compliant": False,
            "error": f"Unknown schema_type '{schema_type}'. Supported: {list(SCHEMAS.keys())}",
            "confidence_score": 0.0
        }

    schema = SCHEMAS[schema_type]
    missing_fields: List[str] = []
    invalid_patterns: List[Dict[str, str]] = []
    valid_fields: List[str] = []

    # Check required fields
    for field in schema["required_fields"]:
        if field not in document_payload or not document_payload[field]:
            missing_fields.append(field)
        else:
            val = str(document_payload[field]).strip()
            # Check regex pattern if defined
            pattern = schema.get("patterns", {}).get(field)
            if pattern and not re.match(pattern, val):
                invalid_patterns.append({
                    "field": field,
                    "value": val,
                    "expected_pattern": pattern
                })
            else:
                valid_fields.append(field)

    total_requirements = len(schema["required_fields"]) + len(schema.get("patterns", {}))
    met_requirements = (len(valid_fields) * 2) - len(invalid_patterns)
    confidence = max(0.0, min(1.0, met_requirements / max(1, total_requirements * 2)))

    is_compliant = (len(missing_fields) == 0 and len(invalid_patterns) == 0)

    return {
        "schema_type": schema_type,
        "is_compliant": is_compliant,
        "confidence_score": round(confidence, 3),
        "valid_fields": valid_fields,
        "missing_fields": missing_fields,
        "pattern_violations": invalid_patterns,
        "risk_level": "LOW" if is_compliant else ("HIGH" if len(missing_fields) > 1 else "MEDIUM"),
        "triage_verdict": "APPROVED_AUTO_PASS" if is_compliant else "REQUIRES_HUMAN_CORRECTION"
    }
