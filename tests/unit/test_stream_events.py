"""Unit tests for streaming event extraction.

Tests _node_event_summary() for every node type and validates that
stream event models carry the correct api_version and event discriminator.
No infrastructure required — all tests are pure Python.
"""
from __future__ import annotations

import json

import pytest

from finance_analytics.agents.supervisor import _node_event_summary
from finance_analytics.schemas.agent_outputs import (
    CypherContextOutput,
    ReflectionOutput,
    RefinerOutput,
    SQLQueryOutput,
    ValidatorOutput,
)
from finance_analytics.schemas.stream_events import ErrorEvent, NodeDoneEvent, ResultEvent


# ── _node_event_summary: check_cache ──────────────────────────────────────────

def test_check_cache_hit_says_hit():
    assert "hit" in _node_event_summary("check_cache", {"cached": True}).lower()


def test_check_cache_miss_says_miss():
    assert "miss" in _node_event_summary("check_cache", {"cached": False}).lower()


# ── _node_event_summary: refiner ──────────────────────────────────────────────

def _make_refiner_output(terms: list[str], requires_solver: bool) -> RefinerOutput:
    return RefinerOutput(
        refined_question="q",
        domain_terms=terms,
        requires_solver=requires_solver,
        max_retries=2,
    )


def test_refiner_shows_term_count():
    ro = _make_refiner_output(["revenue", "margin", "churn"], requires_solver=False)
    summary = _node_event_summary("refiner", {"refiner_output": ro})
    assert "3" in summary


def test_refiner_shows_solver_required():
    ro = _make_refiner_output(["dcf"], requires_solver=True)
    summary = _node_event_summary("refiner", {"refiner_output": ro})
    assert "solver" in summary.lower()
    assert "required" in summary.lower()


def test_refiner_shows_no_solver():
    ro = _make_refiner_output(["revenue"], requires_solver=False)
    summary = _node_event_summary("refiner", {"refiner_output": ro})
    assert "no solver" in summary.lower()


def test_refiner_missing_output_is_graceful():
    summary = _node_event_summary("refiner", {})
    assert summary  # non-empty


# ── _node_event_summary: text_to_cypher ───────────────────────────────────────

def _make_cypher_ctx(n_rules: int, n_anomalies: int, n_concepts: int) -> CypherContextOutput:
    return CypherContextOutput(
        business_rules=[{"id": f"BR-{i}"} for i in range(n_rules)],
        known_anomalies=[{"id": f"KA-{i}"} for i in range(n_anomalies)],
        concepts=[{"name": f"c{i}"} for i in range(n_concepts)],
        cypher_used="",
    )


def test_cypher_summary_shows_rule_count():
    ctx = _make_cypher_ctx(3, 1, 2)
    summary = _node_event_summary("text_to_cypher", {"cypher_context": ctx})
    assert "3" in summary


def test_cypher_summary_shows_concept_count():
    ctx = _make_cypher_ctx(0, 0, 5)
    summary = _node_event_summary("text_to_cypher", {"cypher_context": ctx})
    assert "5" in summary


def test_cypher_missing_output_is_graceful():
    summary = _node_event_summary("text_to_cypher", {})
    assert summary


# ── _node_event_summary: text_to_sql ──────────────────────────────────────────

def test_sql_summary_shows_row_count_and_ms():
    sql = SQLQueryOutput(sql="SELECT 1", rows=[{"a": 1}], row_count=1, execution_ms=42)
    summary = _node_event_summary("text_to_sql", {"sql_result": sql})
    assert "1" in summary
    assert "42" in summary


def test_sql_missing_output_is_graceful():
    summary = _node_event_summary("text_to_sql", {})
    assert summary


# ── _node_event_summary: python_executor ──────────────────────────────────────

def test_python_executor_with_result():
    from finance_analytics.schemas.agent_outputs import PythonExecutorOutput
    po = PythonExecutorOutput(code="x=1", result=1, stdout="", execution_ms=10)
    summary = _node_event_summary("python_executor", {"python_result": po})
    assert "executed" in summary.lower()


def test_python_executor_skipped():
    summary = _node_event_summary("python_executor", {})
    assert "skip" in summary.lower()


# ── _node_event_summary: validator ────────────────────────────────────────────

def test_validator_passed():
    vo = ValidatorOutput(passed=True, issues=[], confidence_components={})
    summary = _node_event_summary("validator", {"validator_output": vo})
    assert "passed" in summary.lower()


def test_validator_failed_shows_first_issue():
    vo = ValidatorOutput(
        passed=False,
        issues=["no cypher_context reference", "missing sql_rows"],
        confidence_components={},
    )
    summary = _node_event_summary("validator", {"validator_output": vo})
    assert "failed" in summary.lower()
    assert "cypher_context" in summary


def test_validator_failed_caps_at_two_issues():
    issues = [f"issue_{i}" for i in range(5)]
    vo = ValidatorOutput(passed=False, issues=issues, confidence_components={})
    summary = _node_event_summary("validator", {"validator_output": vo})
    assert "issue_0" in summary
    assert "issue_2" not in summary


# ── _node_event_summary: reflection ───────────────────────────────────────────

def test_reflection_shows_confidence_pct():
    ro = ReflectionOutput(
        addresses_question=True, reasoning="ok",
        citations=[], confidence_score=0.85,
    )
    summary = _node_event_summary("reflection", {"reflection_output": ro})
    assert "85%" in summary


def test_reflection_low_confidence():
    ro = ReflectionOutput(
        addresses_question=False, reasoning="uncertain",
        citations=[], confidence_score=0.4,
    )
    summary = _node_event_summary("reflection", {"reflection_output": ro})
    assert "40%" in summary


# ── _node_event_summary: write_cache and unknown ──────────────────────────────

def test_write_cache_summary():
    summary = _node_event_summary("write_cache", {})
    assert summary


def test_unknown_node_returns_node_name():
    summary = _node_event_summary("mystery_node", {})
    assert summary == "mystery_node"


# ── Stream event model contracts ──────────────────────────────────────────────

def test_node_done_event_fields():
    e = NodeDoneEvent(node="refiner", summary="2 terms; no solver")
    assert e.event == "node_done"
    assert e.api_version == "2"
    assert e.node == "refiner"


def test_result_event_fields():
    e = ResultEvent(
        summary="Revenue grew 12% YoY.",
        citations=[],
        confidence_score=0.9,
        requires_solver=False,
        low_confidence=False,
    )
    assert e.event == "result"
    assert e.api_version == "2"
    assert e.enrichment_task_id is None
    assert e.cached is False


def test_error_event_fields():
    e = ErrorEvent(message="Neo4j timeout")
    assert e.event == "error"
    assert e.api_version == "2"


def test_result_event_cached_flag():
    e = ResultEvent(
        summary="ok", citations=[], confidence_score=0.95,
        requires_solver=False, low_confidence=False, cached=True,
    )
    assert e.cached is True


# ── SSE wire format ───────────────────────────────────────────────────────────

def test_node_done_serialises_to_valid_sse():
    e = NodeDoneEvent(node="text_to_cypher", summary="3 rule(s), 0 anomaly/ies, 2 concept(s)")
    line = f"data: {e.model_dump_json()}\n\n"
    assert line.startswith("data: ")
    assert line.endswith("\n\n")
    payload = json.loads(line[len("data: "):].strip())
    assert payload["event"] == "node_done"
    assert payload["api_version"] == "2"


def test_result_serialises_to_valid_sse():
    e = ResultEvent(
        summary="Net margin compressed 200bps.",
        citations=[],
        confidence_score=0.88,
        requires_solver=True,
        low_confidence=False,
    )
    line = f"data: {e.model_dump_json()}\n\n"
    payload = json.loads(line[len("data: "):].strip())
    assert payload["event"] == "result"
    assert payload["confidence_score"] == pytest.approx(0.88)
