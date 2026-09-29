"""
Tool behaviour tests.

Several of these are regression guards for defects that shipped in v1.0.0 and
are named accordingly, so a future change that reintroduces one fails loudly
rather than quietly.
"""

import unittest

from proactive_agent_mcp.tools import triage
from proactive_agent_mcp.tools.compliance import evaluate_document_compliance
from proactive_agent_mcp.tools.knowledge import query_rag_knowledge
from proactive_agent_mcp.tools.triage import (
    complete_event,
    poll_event_queue,
    push_event,
    queue_stats,
    release_event,
)
from tests.helpers import StateResetTestCase

VALID_HANDOVER = {
    "employee_id": "EMP-9021",
    "serial_number": "PF-999-LTP",
    "department": "Engineering",
    "custody_date": "2026-09-24",
}


class TestComplianceEvaluation(StateResetTestCase):
    def test_fully_compliant_document_scores_full_confidence(self):
        """
        Regression: v1.0.0 double-counted pattern rules, capping a perfect
        document at 0.571 while reporting it APPROVED_AUTO_PASS.
        """
        result = evaluate_document_compliance(VALID_HANDOVER)
        self.assertTrue(result["is_compliant"])
        self.assertEqual(result["confidence_score"], 1.0)
        self.assertEqual(result["risk_level"], "LOW")
        self.assertEqual(result["triage_verdict"], "APPROVED_AUTO_PASS")

    def test_confidence_is_the_share_of_satisfied_required_fields(self):
        result = evaluate_document_compliance({"department": "Engineering"})
        # Only 1 of 4 required fields is present and valid.
        self.assertEqual(result["confidence_score"], 0.25)
        self.assertEqual(len(result["missing_fields"]), 3)
        self.assertEqual(result["risk_level"], "HIGH")
        self.assertEqual(result["triage_verdict"], "REQUIRES_HUMAN_CORRECTION")

    def test_pattern_violation_is_reported_and_fails_in_strict_mode(self):
        payload = dict(VALID_HANDOVER, employee_id="not-an-id")
        result = evaluate_document_compliance(payload, strict_mode=True)
        self.assertFalse(result["is_compliant"])
        self.assertEqual(len(result["pattern_violations"]), 1)
        self.assertEqual(result["pattern_violations"][0]["field"], "employee_id")
        self.assertEqual(result["confidence_score"], 0.75)

    def test_strict_mode_false_downgrades_violations_to_warnings(self):
        payload = dict(VALID_HANDOVER, employee_id="not-an-id")
        result = evaluate_document_compliance(payload, strict_mode=False)
        self.assertTrue(result["is_compliant"])
        self.assertEqual(len(result["pattern_violations"]), 1)
        self.assertIn("note", result)

    def test_strict_mode_false_still_fails_on_missing_fields(self):
        result = evaluate_document_compliance({"department": "Eng"}, strict_mode=False)
        self.assertFalse(result["is_compliant"])

    def test_empty_values_count_as_missing(self):
        result = evaluate_document_compliance(dict(VALID_HANDOVER, department="   "))
        self.assertIn("department", result["missing_fields"])

    def test_unknown_schema_type(self):
        result = evaluate_document_compliance(VALID_HANDOVER, schema_type="nope")
        self.assertFalse(result["is_compliant"])
        self.assertIn("error", result)
        self.assertEqual(result["confidence_score"], 0.0)

    def test_it_security_audit_schema(self):
        result = evaluate_document_compliance(
            {
                "endpoint_id": "WS-099",
                "os_version": "11",
                "antivirus_status": "on",
                "encryption_enabled": True,
            },
            schema_type="it_security_audit",
        )
        self.assertTrue(result["is_compliant"])
        self.assertEqual(result["confidence_score"], 1.0)


class TestRetrieval(StateResetTestCase):
    def test_relevant_query_ranks_the_matching_chunk_first(self):
        result = query_rag_knowledge("asset custody handover")
        self.assertGreater(result["results_count"], 0)
        self.assertEqual(result["results"][0]["chunk_id"], "kb-rag-001")
        self.assertEqual(result["grounding_status"], "CONFIDENT")

    def test_second_chunk_is_retrievable_by_its_own_topic(self):
        result = query_rag_knowledge("human approval for destructive actions")
        self.assertEqual(result["results"][0]["chunk_id"], "kb-rag-002")

    def test_unrelated_query_returns_nothing_rather_than_the_closest_guess(self):
        result = query_rag_knowledge("quantum blockchain lobster")
        self.assertEqual(result["results_count"], 0)
        self.assertEqual(result["grounding_status"], "NO_MATCH")

    def test_similarity_is_a_bounded_cosine(self):
        result = query_rag_knowledge("asset custody", min_score_threshold=0.0)
        for hit in result["results"]:
            self.assertGreaterEqual(hit["similarity_score"], 0.0)
            self.assertLessEqual(hit["similarity_score"], 1.0)

    def test_regression_retrieval_latency_is_measured_not_a_constant(self):
        """
        Regression: v1.0.0 returned a hardcoded 4.2 ms and the old suite
        asserted that constant was small, which tested nothing.
        """
        first = query_rag_knowledge("asset custody")["retrieval_latency_ms"]
        self.assertIsInstance(first, float)
        self.assertGreaterEqual(first, 0.0)
        # Real measurement over a tiny in-memory corpus is sub-millisecond; the
        # point is that it is a clock reading, not the fabricated 4.2.
        self.assertLess(first, 4.2)

    def test_regression_no_fabricated_benchmark_content(self):
        """
        Regression: v1.0.0 shipped an invented benchmark chunk claiming sub-7ms
        retrieval and 100% precision, which the server then presented to the
        model as grounded fact.
        """
        result = query_rag_knowledge("latency precision benchmark", min_score_threshold=0.0)
        blob = " ".join(hit["content"] for hit in result["results"]).lower()
        self.assertNotIn("100%", blob)
        self.assertNotIn("precision", blob)

    def test_retrieval_declares_its_method_and_limits(self):
        result = query_rag_knowledge("asset")
        self.assertEqual(result["retrieval_method"], "tf_idf_cosine")
        self.assertIn("caveat", result)


class TestEventQueueLifecycle(StateResetTestCase):
    def test_poll_claims_events_and_takes_a_lease(self):
        result = poll_event_queue(max_items=2)
        self.assertEqual(result["total_unprocessed_found"], 2)
        for item in result["items"]:
            self.assertEqual(item["status"], "CLAIMED")
            self.assertIn("lease_expires_at", item)
        self.assertIsNotNone(result["lease_expires_at"])

    def test_claimed_events_are_not_handed_out_twice(self):
        first = {i["id"] for i in poll_event_queue(max_items=2)["items"]}
        second = {i["id"] for i in poll_event_queue(max_items=5)["items"]}
        self.assertEqual(len(first), 2)
        self.assertTrue(first.isdisjoint(second), "a leased event was re-issued")

    def test_severity_filter(self):
        result = poll_event_queue(filter_severity="critical", max_items=5)
        self.assertEqual(result["total_unprocessed_found"], 0)

    def test_release_returns_an_event_immediately(self):
        claimed = poll_event_queue(max_items=1)["items"][0]["id"]
        self.assertTrue(release_event(claimed)["released"])
        again = poll_event_queue(max_items=1)["items"][0]["id"]
        self.assertEqual(again, claimed)

    def test_release_of_an_unclaimed_event_is_rejected(self):
        result = release_event("evt-9041")
        self.assertEqual(result["status"], "CONFLICT")

    def test_complete_settles_an_event(self):
        claimed = poll_event_queue(max_items=1)["items"][0]["id"]
        result = complete_event(claimed, outcome="ESCALATED", note="needs a human")
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["outcome"], "ESCALATED")

    def test_regression_an_event_cannot_be_settled_twice(self):
        claimed = poll_event_queue(max_items=1)["items"][0]["id"]
        complete_event(claimed)
        self.assertEqual(complete_event(claimed)["status"], "CONFLICT")

    def test_regression_expired_lease_returns_work_to_the_queue(self):
        """
        Regression: v1.0.0 flipped events to CLAIMED permanently, so an agent
        that crashed mid-triage stranded the event forever.
        """
        claimed = poll_event_queue(max_items=1, lease_seconds=30)["items"][0]
        record = next(i for i in triage._MOCK_EVENT_STORE if i["id"] == claimed["id"])
        record["lease_expires_at"] = "2000-01-01T00:00:00+00:00"

        result = poll_event_queue(max_items=5)
        self.assertEqual(result["leases_reclaimed_this_poll"], 1)
        self.assertIn(claimed["id"], [i["id"] for i in result["items"]])

    def test_push_event_adds_to_the_queue(self):
        result = push_event("SYNTHETIC_ALERT", "low", {"detail": "test"})
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(queue_stats()["total"], 4)

    def test_unknown_event_operations_report_not_found(self):
        self.assertEqual(complete_event("evt-does-not-exist")["status"], "NOT_FOUND")
        self.assertEqual(release_event("evt-does-not-exist")["status"], "NOT_FOUND")

    def test_empty_queue_recommends_idle(self):
        for event in triage._MOCK_EVENT_STORE:
            event["status"] = "PROCESSED"
        result = poll_event_queue()
        self.assertFalse(result["action_required"])
        self.assertIn("Sleep", result["recommended_next_step"])


if __name__ == "__main__":
    unittest.main()
