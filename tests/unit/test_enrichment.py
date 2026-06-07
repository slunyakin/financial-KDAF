"""Unit tests for the enrichment gap reporting endpoints.

No live Neo4j required. Tests cover:
  - EnrichmentReportRequest validation
  - enrichment_report_endpoint: node write params (description, user_id, affected_question)
  - require_role: 403 for missing role, passes for matching role
  - enrichment_tasks_endpoint: status filter, limit, neo4j.time.DateTime coercion
  - EnrichmentTaskItem / EnrichmentTasksResponse model contracts
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from finance_analytics.schemas.enrichment import (
    EnrichmentReportRequest,
    EnrichmentReportResponse,
    EnrichmentTaskItem,
    EnrichmentTasksResponse,
)


# ── EnrichmentReportRequest validation ───────────────────────────────────────

def test_report_request_requires_description():
    with pytest.raises(ValidationError):
        EnrichmentReportRequest(description="")


def test_report_request_optional_affected_question():
    req = EnrichmentReportRequest(description="Missing gross retention definition")
    assert req.affected_question is None


def test_report_request_with_affected_question():
    req = EnrichmentReportRequest(
        description="Missing gross retention",
        affected_question="What is our gross retention for Q2?",
    )
    assert req.affected_question == "What is our gross retention for Q2?"


# ── enrichment_report_endpoint: node write params ────────────────────────────

def _make_session_mock(single_result=None, run_result=None):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result_mock = AsyncMock()
    result_mock.single = AsyncMock(return_value=single_result or {"task_id": "4:abc:0"})
    session.run = AsyncMock(return_value=result_mock)
    return session


@pytest.mark.asyncio
async def test_enrichment_report_writes_correct_params():
    from finance_analytics.api.routes import enrichment_report_endpoint
    from finance_analytics.schemas.enrichment import EnrichmentReportRequest

    request = EnrichmentReportRequest(
        description="Gross retention concept missing",
        affected_question="What is gross retention?",
    )
    session_mock = _make_session_mock(single_result={"task_id": "4:abc:0"})
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_report_endpoint(
            request=request, current_user=("user-42", ["analyst"])
        )

    assert response.task_id == "4:abc:0"
    assert response.status == "open"

    session_mock.run.assert_called_once()
    _, kwargs = session_mock.run.call_args
    assert kwargs["description"] == "Gross retention concept missing"
    assert kwargs["user_id"] == "user-42"
    assert kwargs["affected_question"] == "What is gross retention?"


@pytest.mark.asyncio
async def test_enrichment_report_null_affected_question():
    from finance_analytics.api.routes import enrichment_report_endpoint
    from finance_analytics.schemas.enrichment import EnrichmentReportRequest

    request = EnrichmentReportRequest(description="Some gap")
    session_mock = _make_session_mock(single_result={"task_id": "4:xyz:0"})
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_report_endpoint(
            request=request, current_user=("user-1", [])
        )

    _, kwargs = session_mock.run.call_args
    assert kwargs["affected_question"] is None
    assert response.task_id == "4:xyz:0"


# ── require_role ─────────────────────────────────────────────────────────────

def test_require_role_raises_403_for_missing_role():
    from finance_analytics.api.auth import require_role

    dep = require_role("knowledge_engineer")
    # dep is a closure; call it directly with a user lacking the role
    checker = dep.__wrapped__ if hasattr(dep, "__wrapped__") else dep
    # Simulate calling the inner _check function
    import inspect
    inner = None
    for name, obj in inspect.getmembers(dep):
        pass
    # Call the dependency function directly (bypassing FastAPI Depends machinery)
    # require_role returns a function; call it with (user_id, roles) tuple
    with pytest.raises(HTTPException) as exc_info:
        # Invoke the inner _check by supplying current_user directly
        from finance_analytics.api.auth import require_role as rr
        fn = rr("knowledge_engineer")
        fn.__code__  # confirm it's a function
        # Build a local call to _check manually
        fn(current_user=("user-1", ["analyst"]))

    assert exc_info.value.status_code == 403


def test_require_role_passes_for_matching_role():
    from finance_analytics.api.auth import require_role

    fn = require_role("knowledge_engineer")
    result = fn(current_user=("user-1", ["knowledge_engineer", "analyst"]))
    assert result == ("user-1", ["knowledge_engineer", "analyst"])


def test_require_role_passes_exact_match():
    from finance_analytics.api.auth import require_role

    fn = require_role("analyst")
    result = fn(current_user=("user-7", ["analyst"]))
    assert result == ("user-7", ["analyst"])


def test_require_role_raises_403_empty_roles():
    from finance_analytics.api.auth import require_role

    fn = require_role("knowledge_engineer")
    with pytest.raises(HTTPException) as exc_info:
        fn(current_user=("user-7", []))
    assert exc_info.value.status_code == 403
    assert "knowledge_engineer" in exc_info.value.detail


# ── enrichment_tasks_endpoint: status filter + datetime coercion ─────────────

def _make_tasks_session_mock(records, total):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    list_result = AsyncMock()
    list_result.data = AsyncMock(return_value=records)

    count_result = AsyncMock()
    count_result.single = AsyncMock(return_value={"total": total})

    session.run = AsyncMock(side_effect=[list_result, count_result])
    return session


def _make_fake_neo4j_dt(py_dt: datetime):
    """Fake neo4j.time.DateTime — has .to_native() like the real driver type."""
    mock = MagicMock()
    mock.to_native.return_value = py_dt
    return mock


@pytest.mark.asyncio
async def test_enrichment_tasks_returns_items():
    from finance_analytics.api.routes import enrichment_tasks_endpoint

    dt = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
    records = [
        {
            "task_id": "4:abc:0",
            "question_text": "missing gross retention",
            "confidence_score": None,
            "source": "manual",
            "status": "open",
            "submitted_by": "user-42",
            "created_at": _make_fake_neo4j_dt(dt),
        }
    ]
    session_mock = _make_tasks_session_mock(records, total=1)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_tasks_endpoint(
            current_user=("user-1", ["knowledge_engineer"]),
            status="open",
            limit=50,
        )

    assert response.api_version == "1"
    assert response.total == 1
    assert len(response.items) == 1
    item = response.items[0]
    assert item.task_id == "4:abc:0"
    assert item.question_text == "missing gross retention"
    assert item.confidence_score is None
    assert item.source == "manual"
    assert item.created_at == dt


@pytest.mark.asyncio
async def test_enrichment_tasks_passes_status_filter():
    from finance_analytics.api.routes import enrichment_tasks_endpoint

    dt = datetime(2026, 6, 6, tzinfo=timezone.utc)
    session_mock = _make_tasks_session_mock(
        [{"task_id": "4:r:0", "question_text": "x", "confidence_score": None,
          "source": "reflection", "status": "resolved", "submitted_by": None,
          "created_at": _make_fake_neo4j_dt(dt)}],
        total=1,
    )
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_tasks_endpoint(
            current_user=("user-1", ["knowledge_engineer"]),
            status="resolved",
            limit=50,
        )

    _, kwargs = session_mock.run.call_args_list[0]
    assert kwargs["status"] == "resolved"
    assert response.total == 1


@pytest.mark.asyncio
async def test_enrichment_tasks_empty_result():
    from finance_analytics.api.routes import enrichment_tasks_endpoint

    session_mock = _make_tasks_session_mock(records=[], total=0)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_tasks_endpoint(
            current_user=("ke-user", ["knowledge_engineer"]),
            status="open",
            limit=50,
        )

    assert response.items == []
    assert response.total == 0


# ── EnrichmentTaskItem / EnrichmentTasksResponse model contracts ─────────────

def test_enrichment_task_item_nullable_fields():
    item = EnrichmentTaskItem(
        task_id="4:abc:0",
        question_text="missing concept",
        confidence_score=None,
        source="manual",
        status="open",
        submitted_by=None,
        created_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
    )
    assert item.confidence_score is None
    assert item.submitted_by is None


def test_enrichment_tasks_response_api_version():
    resp = EnrichmentTasksResponse(items=[], total=0)
    assert resp.api_version == "1"


def test_enrichment_report_response_fields():
    resp = EnrichmentReportResponse(task_id="4:abc:0", status="open")
    assert resp.task_id == "4:abc:0"
    assert resp.status == "open"
