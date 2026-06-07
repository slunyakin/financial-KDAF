"""Unit tests for query history — Question node write logic and response models.

No live Neo4j required. Tests cover:
  - write_question_node parameter correctness
  - cache-hit skip behaviour
  - QuestionHistoryItem / QueryHistoryResponse model contracts
  - _node_event_summary for write_question node
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from finance_analytics.agents.supervisor import _node_event_summary, write_question_node
from finance_analytics.schemas.agent_outputs import ReflectionOutput
from finance_analytics.schemas.query_response import QueryHistoryResponse, QuestionHistoryItem


# ── write_question_node: skips on cache hit ────────────────────────────────────

@pytest.mark.asyncio
async def test_write_question_skips_on_cache_hit():
    state = {
        "question": "What is our churn?",
        "user_id": "user-1",
        "user_roles": ["analyst"],
        "cached": True,
        "reflection_output": ReflectionOutput(
            addresses_question=True, reasoning="ok", citations=[], confidence_score=0.9
        ),
        "answer": {"confidence_score": 0.9},
    }
    with patch("finance_analytics.agents.supervisor.conn") as mock_conn:
        result = await write_question_node(state)

    mock_conn.get_neo4j.assert_not_called()
    assert result == {}


# ── write_question_node: skips when no reflection ────────────────────────────

@pytest.mark.asyncio
async def test_write_question_skips_without_reflection():
    state = {
        "question": "What is our churn?",
        "user_id": "user-1",
        "user_roles": [],
        "cached": False,
        "reflection_output": None,
        "answer": {},
    }
    with patch("finance_analytics.agents.supervisor.conn") as mock_conn:
        result = await write_question_node(state)

    mock_conn.get_neo4j.assert_not_called()
    assert result == {}


# ── write_question_node: writes correct params ────────────────────────────────

def _make_session_mock(run_result=None):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.run = AsyncMock(return_value=run_result or AsyncMock())
    return session


@pytest.mark.asyncio
async def test_write_question_correct_params():
    reflection = ReflectionOutput(
        addresses_question=True,
        reasoning="Revenue grew 12% YoY.",
        citations=[],
        confidence_score=0.88,
    )
    state = {
        "question": "What drove revenue growth?",
        "user_id": "user-42",
        "user_roles": ["analyst"],
        "cached": False,
        "reflection_output": reflection,
        "answer": {"confidence_score": 0.88, "enrichment_task_id": None},
    }

    session_mock = _make_session_mock()
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.agents.supervisor.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        result = await write_question_node(state)

    assert result == {}
    session_mock.run.assert_called_once()
    _, kwargs = session_mock.run.call_args
    assert kwargs["user_id"] == "user-42"
    assert kwargs["question_text"] == "What drove revenue growth?"
    assert kwargs["summary"] == "Revenue grew 12% YoY."
    assert kwargs["confidence_score"] == pytest.approx(0.88)
    assert kwargs["low_confidence"] is False
    assert kwargs["enrichment_task_id"] is None


@pytest.mark.asyncio
async def test_write_question_low_confidence_flag():
    reflection = ReflectionOutput(
        addresses_question=False, reasoning="Uncertain.", citations=[], confidence_score=0.5
    )
    state = {
        "question": "What is NRR?",
        "user_id": "user-7",
        "user_roles": [],
        "cached": False,
        "reflection_output": reflection,
        "answer": {"confidence_score": 0.5, "enrichment_task_id": "task-abc"},
    }

    session_mock = _make_session_mock()
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.agents.supervisor.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        await write_question_node(state)

    _, kwargs = session_mock.run.call_args
    assert kwargs["low_confidence"] is True
    assert kwargs["enrichment_task_id"] == "task-abc"


@pytest.mark.asyncio
async def test_write_question_swallows_neo4j_error():
    reflection = ReflectionOutput(
        addresses_question=True, reasoning="ok", citations=[], confidence_score=0.9
    )
    state = {
        "question": "Any question",
        "user_id": "user-1",
        "user_roles": [],
        "cached": False,
        "reflection_output": reflection,
        "answer": {"confidence_score": 0.9},
    }

    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.side_effect = RuntimeError("Neo4j down")

    with patch("finance_analytics.agents.supervisor.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        result = await write_question_node(state)  # must not raise

    assert result == {}


# ── QuestionHistoryItem model ──────────────────────────────────────────────────

def test_question_history_item_fields():
    item = QuestionHistoryItem(
        question_text="What is gross margin?",
        summary="Gross margin was 72%.",
        confidence_score=0.91,
        low_confidence=False,
        enrichment_task_id=None,
        created_at=datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert item.question_text == "What is gross margin?"
    assert item.confidence_score == pytest.approx(0.91)
    assert item.low_confidence is False
    assert item.enrichment_task_id is None


def test_question_history_item_with_enrichment_task():
    item = QuestionHistoryItem(
        question_text="What is NRR?",
        summary="Could not answer confidently.",
        confidence_score=0.45,
        low_confidence=True,
        enrichment_task_id="4:abc:0",
        created_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    assert item.low_confidence is True
    assert item.enrichment_task_id == "4:abc:0"


# ── QueryHistoryResponse model ────────────────────────────────────────────────

def test_query_history_response_api_version():
    resp = QueryHistoryResponse(items=[], total=0)
    assert resp.api_version == "1"
    assert resp.items == []
    assert resp.total == 0


def test_query_history_response_with_items():
    items = [
        QuestionHistoryItem(
            question_text=f"Question {i}",
            summary=f"Summary {i}",
            confidence_score=0.8,
            low_confidence=False,
            created_at=datetime(2026, 6, i + 1, tzinfo=timezone.utc),
        )
        for i in range(3)
    ]
    resp = QueryHistoryResponse(items=items, total=14)
    assert len(resp.items) == 3
    assert resp.total == 14


# ── _node_event_summary: write_question ───────────────────────────────────────

def test_write_question_node_summary():
    summary = _node_event_summary("write_question", {})
    assert "history" in summary.lower()
