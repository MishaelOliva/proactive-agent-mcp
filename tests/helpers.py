"""
Shared test fixtures.

The tool layer keeps process-wide state (event queue, approval tickets, budget
ledger) because that is what a single-process server does. Tests reset it
between cases so ordering cannot mask a failure.
"""

import copy
import unittest

from proactive_agent_mcp.tools import guardrails, set_active_session_id, triage


def reset_state() -> None:
    """Return all mutable server state to a known baseline."""
    triage._MOCK_EVENT_STORE.clear()
    triage._MOCK_EVENT_STORE.extend(copy.deepcopy(_PRISTINE_EVENTS))
    guardrails._APPROVAL_TICKETS.clear()
    guardrails.COST_GUARD._sessions.clear()
    set_active_session_id("default")


# Captured once, at import, before any test mutates the queue.
_PRISTINE_EVENTS = copy.deepcopy(triage._MOCK_EVENT_STORE)


class StateResetTestCase(unittest.TestCase):
    """Base class that isolates each test from process-wide state."""

    def setUp(self) -> None:
        reset_state()
        self.addCleanup(reset_state)
