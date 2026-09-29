"""
Human-in-the-loop authorization: the security properties the gate claims.

v1.0.0 shipped a gate that could be walked straight through, and a test that
reached into the server's private ticket store to fetch the expected code, which
verified the HMAC round-trip while proving nothing about the boundary. The cases
below assert the properties that actually matter.
"""

import ast
import hashlib
import hmac
import inspect
import os
import subprocess
import sys
import unittest
from pathlib import Path

from proactive_agent_mcp.tools import guardrails
from proactive_agent_mcp.tools.guardrails import (
    _APPROVAL_TICKETS,
    generate_confirmation_code,
    normalize_confirmation_code,
    request_human_approval,
    verify_approval_token,
)
from tests.helpers import StateResetTestCase

GUARDRAILS_SOURCE = Path(guardrails.__file__)


def code_for(ticket_id, action_name, parameters, expires_at):
    """Recompute a ticket's code the way an out-of-band channel legitimately would."""
    return generate_confirmation_code(ticket_id, action_name, parameters, expires_at)


class TestSecretHandling(unittest.TestCase):
    def test_regression_no_hardcoded_default_secret(self):
        """
        Regression: v1.0.0 read os.environ.get("MCP_SIGNING_SECRET", <literal>).
        Because the repository is public, that literal let anyone compute a
        valid approval code for any ticket and defeat the gate entirely.
        """
        tree = ast.parse(GUARDRAILS_SOURCE.read_text(encoding="utf-8"))
        getenv_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and ast.unparse(node.func.value) == "os.environ"
            and node.args
            and ast.unparse(node.args[0]) == "'MCP_SIGNING_SECRET'"
        ]
        self.assertEqual(len(getenv_calls), 1, "expected exactly one MCP_SIGNING_SECRET lookup")
        self.assertEqual(
            len(getenv_calls[0].args),
            1,
            "MCP_SIGNING_SECRET must be read with no default value; a fallback "
            "secret published in the repository makes every approval forgeable.",
        )

    def test_no_secret_literal_anywhere_in_the_module(self):
        source = GUARDRAILS_SOURCE.read_text(encoding="utf-8")
        for suspect in ("internal-secret", "insecure", "change-in-production", "dev-secret"):
            self.assertNotIn(
                suspect, source.lower(), f"a hardcoded secret marker {suspect!r} is present"
            )

    def test_unset_secret_yields_a_random_ephemeral_one_per_process(self):
        """
        With no secret configured, two separate processes must not share a key.
        """
        script = (
            "from proactive_agent_mcp.tools import guardrails as g;print(g._SIGNING_SECRET.hex())"
        )
        env = {k: v for k, v in os.environ.items() if k != "MCP_SIGNING_SECRET"}
        first = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, env=env
        )
        second = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, env=env
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertNotEqual(
            first.stdout.strip(),
            second.stdout.strip(),
            "an unset MCP_SIGNING_SECRET must not produce a predictable key",
        )


class TestApprovalTicketFlow(StateResetTestCase):
    def test_request_returns_a_ticket_but_never_the_code(self):
        result = request_human_approval(
            "wipe_endpoint_storage", {"endpoint": "WS-099"}, "deprovisioning cycle"
        )
        self.assertEqual(result["status"], "APPROVAL_REQUIRED")
        self.assertNotIn("expected_confirmation_code", result)
        self.assertNotIn("confirmation_code", result)
        # The stored record must not carry a reusable code either.
        self.assertNotIn("expected_confirmation_code", _APPROVAL_TICKETS[result["ticket_id"]])

    def test_valid_code_authorizes(self):
        ticket = request_human_approval("delete_record", {"id": 7}, "cleanup")
        stored = _APPROVAL_TICKETS[ticket["ticket_id"]]
        code = code_for(
            stored["ticket_id"],
            stored["action_name"],
            stored["action_parameters"],
            stored["expires_at"],
        )
        result = verify_approval_token(ticket["ticket_id"], code)
        self.assertTrue(result["authorized"])
        self.assertEqual(result["status"], "AUTHORIZED_FOR_DISPATCH")
        self.assertEqual(result["action_parameters"], {"id": 7})

    def test_wrong_code_is_rejected(self):
        ticket = request_human_approval("delete_record", {"id": 7}, "cleanup")
        result = verify_approval_token(ticket["ticket_id"], "WRONG-CODE")
        self.assertFalse(result["authorized"])
        self.assertEqual(result["reason"], "INVALID_CODE")

    def test_code_is_formatting_insensitive(self):
        ticket = request_human_approval("delete_record", {"id": 7}, "cleanup")
        stored = _APPROVAL_TICKETS[ticket["ticket_id"]]
        code = code_for(
            stored["ticket_id"],
            stored["action_name"],
            stored["action_parameters"],
            stored["expires_at"],
        )
        messy = code.lower().replace("-", " ")
        self.assertEqual(normalize_confirmation_code(messy), normalize_confirmation_code(code))
        self.assertTrue(verify_approval_token(ticket["ticket_id"], messy)["authorized"])

    def test_regression_codes_are_not_truncated(self):
        """
        Regression: v1.0.0 used hexdigest()[:12], cutting the 256-bit MAC down to
        48 bits.
        """
        code = generate_confirmation_code("TICK-1", "action", {}, "2030-01-01T00:00:00+00:00")
        self.assertEqual(
            len(normalize_confirmation_code(code)), 52, "expected a full 256-bit MAC in base32"
        )

    def test_regression_a_code_for_one_action_cannot_approve_another(self):
        """Regression: v1.0.0 signed only (ticket_id, action_name)."""
        benign = request_human_approval("read_report", {"id": 1}, "routine")
        stored = _APPROVAL_TICKETS[benign["ticket_id"]]
        stolen = code_for(
            stored["ticket_id"],
            stored["action_name"],
            stored["action_parameters"],
            stored["expires_at"],
        )
        # Re-point the same ticket at a destructive action after the fact.
        stored["action_name"] = "wipe_all_endpoints"
        result = verify_approval_token(benign["ticket_id"], stolen)
        self.assertFalse(result["authorized"])

    def test_regression_parameters_are_bound_into_the_signature(self):
        """
        Regression: the signed payload omitted action_parameters, so a ticket
        could be edited after approval was obtained.
        """
        ticket = request_human_approval("delete_record", {"id": 7, "confirm": False}, "cleanup")
        stored = _APPROVAL_TICKETS[ticket["ticket_id"]]
        code = code_for(
            stored["ticket_id"],
            stored["action_name"],
            stored["action_parameters"],
            stored["expires_at"],
        )
        stored["action_parameters"] = {"id": 7, "confirm": True}
        result = verify_approval_token(ticket["ticket_id"], code)
        self.assertFalse(result["authorized"])
        self.assertEqual(result["reason"], "INVALID_CODE")

    def test_expiry_is_bound_into_the_signature(self):
        ticket = request_human_approval("delete_record", {"id": 7}, "cleanup")
        stored = _APPROVAL_TICKETS[ticket["ticket_id"]]
        code = code_for(
            stored["ticket_id"],
            stored["action_name"],
            stored["action_parameters"],
            stored["expires_at"],
        )
        stored["expires_at"] = "2099-01-01T00:00:00+00:00"
        self.assertFalse(verify_approval_token(ticket["ticket_id"], code)["authorized"])

    def test_ticket_is_single_use(self):
        ticket = request_human_approval("delete_record", {"id": 7}, "cleanup")
        stored = _APPROVAL_TICKETS[ticket["ticket_id"]]
        code = code_for(
            stored["ticket_id"],
            stored["action_name"],
            stored["action_parameters"],
            stored["expires_at"],
        )
        self.assertTrue(verify_approval_token(ticket["ticket_id"], code)["authorized"])
        replay = verify_approval_token(ticket["ticket_id"], code)
        self.assertFalse(replay["authorized"])
        self.assertEqual(replay["reason"], "ALREADY_CONSUMED")

    def test_expired_ticket_is_refused(self):
        ticket = request_human_approval("delete_record", {"id": 7}, "cleanup", ttl_hours=1)
        stored = _APPROVAL_TICKETS[ticket["ticket_id"]]
        code = code_for(
            stored["ticket_id"],
            stored["action_name"],
            stored["action_parameters"],
            stored["expires_at"],
        )
        stored["expires_at"] = "2000-01-01T00:00:00+00:00"
        result = verify_approval_token(ticket["ticket_id"], code)
        self.assertFalse(result["authorized"])
        self.assertEqual(result["reason"], "EXPIRED")

    def test_unknown_ticket(self):
        result = verify_approval_token("TICK-NOPE", "ANYTHING")
        self.assertFalse(result["authorized"])
        self.assertEqual(result["reason"], "NOT_FOUND")

    def test_codes_differ_between_tickets_for_the_same_action(self):
        first = request_human_approval("delete_record", {"id": 1}, "cleanup")
        second = request_human_approval("delete_record", {"id": 1}, "cleanup")
        a = _APPROVAL_TICKETS[first["ticket_id"]]
        b = _APPROVAL_TICKETS[second["ticket_id"]]
        code_a = code_for(a["ticket_id"], a["action_name"], a["action_parameters"], a["expires_at"])
        code_b = code_for(b["ticket_id"], b["action_name"], b["action_parameters"], b["expires_at"])
        self.assertNotEqual(code_a, code_b)

    def test_tickets_are_garbage_collected_once_settled(self):
        """
        v1.0.0 marked expired tickets but never removed them, so a long-running
        process grew without bound.
        """
        from datetime import datetime, timedelta, timezone

        ticket = request_human_approval("delete_record", {"id": 7}, "cleanup")
        _APPROVAL_TICKETS[ticket["ticket_id"]]["status"] = "EXECUTED"
        _APPROVAL_TICKETS[ticket["ticket_id"]]["settled_at"] = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()
        request_human_approval("another", {}, "top up the store")
        self.assertNotIn(ticket["ticket_id"], _APPROVAL_TICKETS)

    def test_forgery_attempt_using_a_guessed_secret_is_rejected(self):
        """
        The shape of the v1.0.0 attack, run against the new implementation.
        """
        ticket = request_human_approval("wipe_all_endpoints", {}, "exercise")
        guessed_secret = b"proactive-agent-mcp-internal-secret-2026"
        forged = (
            hmac.new(
                guessed_secret,
                f"{ticket['ticket_id']}:wipe_all_endpoints".encode(),
                hashlib.sha256,
            )
            .hexdigest()[:12]
            .upper()
        )
        self.assertFalse(verify_approval_token(ticket["ticket_id"], forged)["authorized"])


class TestModuleSurface(unittest.TestCase):
    def test_module_does_not_configure_root_logging_at_import(self):
        """
        v1.0.0 called logging.basicConfig() at module scope, so importing the
        library reconfigured the host application's logging.
        """
        source = inspect.getsource(guardrails)
        self.assertNotIn("basicConfig", source)

    def test_package_init_installs_a_null_handler(self):
        import proactive_agent_mcp

        handlers = proactive_agent_mcp.logging.getLogger("proactive_agent_mcp").handlers
        self.assertTrue(
            any(isinstance(h, proactive_agent_mcp.logging.NullHandler) for h in handlers),
            "the package must attach a NullHandler so it cannot hijack host logging",
        )


if __name__ == "__main__":
    unittest.main()
