"""Unit tests for the enrichment gap reporting endpoints.

No live Neo4j required. Tests cover:
  - EnrichmentReportRequest validation (including length limits)
  - enrichment_report_endpoint: node write params, None-record guard
  - require_role: 403 for missing role, passes for matching role
  - enrichment_tasks_endpoint: status filter (open/resolved/all), limit, datetime coercion
  - EnrichmentTaskItem / EnrichmentTasksResponse model contracts
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from finance_analytics.api.routes import enrichment_report_endpoint
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


def test_report_request_rejects_description_over_max_length():
    with pytest.raises(ValidationError):
        EnrichmentReportRequest(description="x" * 2001)


def test_report_request_accepts_description_at_max_length():
    req = EnrichmentReportRequest(description="x" * 2000)
    assert len(req.description) == 2000


def test_report_request_rejects_affected_question_over_max_length():
    with pytest.raises(ValidationError):
        EnrichmentReportRequest(
            description="valid",
            affected_question="q" * 501,
        )


def test_report_request_whitespace_only_description_passes_pydantic():
    # Pydantic min_length=1 counts raw length, not stripped length.
    # "   " has length 3, so it passes. This is deliberate — knowledge engineers
    # may occasionally submit edge-case descriptions; we store them verbatim.
    req = EnrichmentReportRequest(description="   ")
    assert req.description == "   "


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

_SENTINEL = object()


def _make_session_mock(single_result=_SENTINEL):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result_mock = AsyncMock()
    result_mock.single = AsyncMock(
        return_value={"task_id": "4:abc:0"} if single_result is _SENTINEL else single_result
    )
    session.run = AsyncMock(return_value=result_mock)
    return session


@pytest.mark.asyncio
async def test_enrichment_report_writes_correct_params():
    request = EnrichmentReportRequest(
        description="Gross retention concept missing",
        affected_question="What is gross retention?",
    )
    session_mock = _make_session_mock(single_result={"element_id": "4:abc:0"})
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_report_endpoint(
            request=request, current_user=("user-42", ["analyst"])
        )

    assert len(response.task_id) == 64  # sha256 hex digest
    assert response.status == "open"

    session_mock.run.assert_called_once()
    _, kwargs = session_mock.run.call_args
    assert kwargs["description"] == "Gross retention concept missing"
    assert kwargs["user_id"] == "user-42"
    assert kwargs["affected_question"] == "What is gross retention?"
    assert len(kwargs["task_id"]) == 64  # deterministic idempotency key


@pytest.mark.asyncio
async def test_enrichment_report_null_affected_question():
    request = EnrichmentReportRequest(description="Some gap")
    session_mock = _make_session_mock(single_result={"element_id": "4:xyz:0"})
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_report_endpoint(
            request=request, current_user=("user-1", [])
        )

    _, kwargs = session_mock.run.call_args
    assert kwargs["affected_question"] is None
    assert len(response.task_id) == 64  # sha256 deterministic ID


@pytest.mark.asyncio
async def test_enrichment_report_idempotency_key_stable():
    """Same user+description within the 15-min TTL window produces the same task_id."""
    request = EnrichmentReportRequest(description="Same gap description")
    ids = []
    for _ in range(2):
        session_mock = _make_session_mock(single_result={"element_id": "4:x:0"})
        neo4j_mock = MagicMock()
        neo4j_mock.driver.session.return_value = session_mock
        with patch("finance_analytics.api.routes.conn") as mock_conn:
            mock_conn.get_neo4j.return_value = neo4j_mock
            resp = await enrichment_report_endpoint(
                request=request, current_user=("user-1", [])
            )
        ids.append(resp.task_id)

    assert ids[0] == ids[1], "task_id must be stable within the TTL window"


@pytest.mark.asyncio
async def test_enrichment_report_raises_500_when_record_is_none():
    """CREATE returning no record (driver failure) must raise HTTP 500, not TypeError."""
    request = EnrichmentReportRequest(description="Some gap")
    session_mock = _make_session_mock(single_result=None)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        with pytest.raises(HTTPException) as exc_info:
            await enrichment_report_endpoint(
                request=request, current_user=("user-1", [])
            )

    assert exc_info.value.status_code == 500


# ── require_role ─────────────────────────────────────────────────────────────

def test_require_role_raises_403_for_missing_role():
    from finance_analytics.api.auth import require_role

    fn = require_role("knowledge_engineer")
    with pytest.raises(HTTPException) as exc_info:
        fn(current_user=("user-1", ["analyst"]))

    assert exc_info.value.status_code == 403
    assert "knowledge_engineer" in exc_info.value.detail


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


def _task_record(dt, *, source="manual", status_val="open"):
    return {
        "task_id": "4:abc:0",
        "question_text": "missing gross retention",
        "confidence_score": None,
        "source": source,
        "status": status_val,
        "submitted_by": "user-42",
        "created_at": _make_fake_neo4j_dt(dt),
    }


@pytest.mark.asyncio
async def test_enrichment_tasks_returns_items():
    from finance_analytics.api.routes import enrichment_tasks_endpoint

    dt = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)
    session_mock = _make_tasks_session_mock([_task_record(dt)], total=1)
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
        [_task_record(dt, source="reflection", status_val="resolved")],
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
    assert kwargs["limit"] == 50
    assert response.total == 1


@pytest.mark.asyncio
async def test_enrichment_tasks_status_all():
    from finance_analytics.api.routes import enrichment_tasks_endpoint

    dt = datetime(2026, 6, 6, tzinfo=timezone.utc)
    session_mock = _make_tasks_session_mock(
        [_task_record(dt), _task_record(dt, status_val="resolved")],
        total=2,
    )
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_tasks_endpoint(
            current_user=("user-1", ["knowledge_engineer"]),
            status="all",
            limit=50,
        )

    _, kwargs = session_mock.run.call_args_list[0]
    assert kwargs["status"] == "all"
    assert response.total == 2
    assert len(response.items) == 2


@pytest.mark.asyncio
async def test_enrichment_tasks_source_fallback_for_reflection_nodes():
    """Reflection-written EnrichmentTask nodes have no source property → should use 'unknown'."""
    from finance_analytics.api.routes import enrichment_tasks_endpoint

    dt = datetime(2026, 6, 6, tzinfo=timezone.utc)
    record = _task_record(dt)
    record["source"] = None  # reflection.py does not set source
    session_mock = _make_tasks_session_mock([record], total=1)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_tasks_endpoint(
            current_user=("user-1", ["knowledge_engineer"]),
            status="open",
            limit=50,
        )

    assert response.items[0].source == "unknown"


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
    resp = EnrichmentReportResponse(task_id="4:abc:0")
    assert resp.task_id == "4:abc:0"
    assert resp.status == "open"


def test_enrichment_report_response_status_is_always_open():
    resp = EnrichmentReportResponse(task_id="4:x:0")
    assert resp.status == "open"


# ── _coerce_neo4j_dt: passthrough branches ───────────────────────────────────

def test_coerce_neo4j_dt_passthrough_for_plain_datetime():
    from finance_analytics.api.routes import _coerce_neo4j_dt
    dt = datetime(2026, 6, 6, tzinfo=timezone.utc)
    assert _coerce_neo4j_dt(dt) is dt


def test_coerce_neo4j_dt_passthrough_for_none():
    from finance_analytics.api.routes import _coerce_neo4j_dt
    assert _coerce_neo4j_dt(None) is None


# ── enrichment_report_endpoint: TTL window flip and driver failure ────────────

@pytest.mark.asyncio
async def test_enrichment_report_different_windows_produce_different_ids():
    """task_id must change when the 15-min TTL window rolls over."""
    request = EnrichmentReportRequest(description="Same description")
    ids = []
    for window_offset in [1_000_000.0, 1_000_900.0]:  # straddle a 900-s boundary
        session_mock = _make_session_mock(single_result={"element_id": "4:x:0"})
        neo4j_mock = MagicMock()
        neo4j_mock.driver.session.return_value = session_mock
        with patch("finance_analytics.api.routes.conn") as mock_conn, \
             patch("finance_analytics.api.routes.time") as mock_time:
            mock_conn.get_neo4j.return_value = neo4j_mock
            mock_time.time.return_value = float(window_offset)
            resp = await enrichment_report_endpoint(
                request=request, current_user=("user-1", [])
            )
        ids.append(resp.task_id)
    assert ids[0] != ids[1]


@pytest.mark.asyncio
async def test_enrichment_report_propagates_driver_exception():
    """session.run() raising propagates out (FastAPI converts unhandled exc to HTTP 500)."""
    request = EnrichmentReportRequest(description="Some gap")
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.run = AsyncMock(side_effect=RuntimeError("Neo4j unavailable"))
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        with pytest.raises(RuntimeError, match="Neo4j unavailable"):
            await enrichment_report_endpoint(
                request=request, current_user=("user-1", [])
            )


# ── enrichment_tasks_endpoint: None coercions, count_record=None, driver fail ─

@pytest.mark.asyncio
async def test_enrichment_tasks_null_status_coerced_to_open():
    from finance_analytics.api.routes import enrichment_tasks_endpoint
    dt = datetime(2026, 6, 6, tzinfo=timezone.utc)
    record = _task_record(dt)
    record["status"] = None
    session_mock = _make_tasks_session_mock([record], total=1)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_tasks_endpoint(
            current_user=("user-1", ["knowledge_engineer"]),
            status="open",
            limit=50,
        )

    assert response.items[0].status == "open"


@pytest.mark.asyncio
async def test_enrichment_tasks_null_question_text_coerced_to_empty():
    from finance_analytics.api.routes import enrichment_tasks_endpoint
    dt = datetime(2026, 6, 6, tzinfo=timezone.utc)
    record = _task_record(dt)
    record["question_text"] = None
    session_mock = _make_tasks_session_mock([record], total=1)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_tasks_endpoint(
            current_user=("user-1", ["knowledge_engineer"]),
            status="open",
            limit=50,
        )

    assert response.items[0].question_text == ""


@pytest.mark.asyncio
async def test_enrichment_tasks_null_count_record_gives_total_zero():
    from finance_analytics.api.routes import enrichment_tasks_endpoint
    dt = datetime(2026, 6, 6, tzinfo=timezone.utc)
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    list_result = AsyncMock()
    list_result.data = AsyncMock(return_value=[_task_record(dt)])
    count_result = AsyncMock()
    count_result.single = AsyncMock(return_value=None)
    session.run = AsyncMock(side_effect=[list_result, count_result])
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_tasks_endpoint(
            current_user=("user-1", ["knowledge_engineer"]),
            status="open",
            limit=50,
        )

    assert response.total == 0


@pytest.mark.asyncio
async def test_enrichment_tasks_confidence_score_non_none():
    from finance_analytics.api.routes import enrichment_tasks_endpoint
    dt = datetime(2026, 6, 6, tzinfo=timezone.utc)
    record = _task_record(dt)
    record["confidence_score"] = 0.45
    session_mock = _make_tasks_session_mock([record], total=1)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        response = await enrichment_tasks_endpoint(
            current_user=("user-1", ["knowledge_engineer"]),
            status="open",
            limit=50,
        )

    assert response.items[0].confidence_score == pytest.approx(0.45)


@pytest.mark.asyncio
async def test_enrichment_tasks_propagates_driver_exception():
    from finance_analytics.api.routes import enrichment_tasks_endpoint
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.run = AsyncMock(side_effect=RuntimeError("Neo4j unavailable"))
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        with pytest.raises(RuntimeError, match="Neo4j unavailable"):
            await enrichment_tasks_endpoint(
                current_user=("user-1", ["knowledge_engineer"]),
                status="open",
                limit=50,
            )


# ── require_role: end-to-end wiring via FastAPI Depends ─────────────────────

def test_enrichment_tasks_endpoint_depends_on_require_role():
    """Verify the endpoint wires Depends(require_role('knowledge_engineer')), not bare get_current_user."""
    import inspect
    from fastapi import params
    from finance_analytics.api.routes import enrichment_tasks_endpoint

    sig = inspect.signature(enrichment_tasks_endpoint)
    current_user_param = sig.parameters.get("current_user")
    assert current_user_param is not None
    default = current_user_param.default
    assert isinstance(default, params.Depends)
    # The dependency is the _check closure from require_role("knowledge_engineer").
    # Calling it with a non-KE role must raise HTTP 403 with the correct role name.
    with pytest.raises(HTTPException) as exc_info:
        default.dependency(current_user=("user-1", ["analyst"]))
    assert exc_info.value.status_code == 403
    assert "knowledge_engineer" in exc_info.value.detail


# ── GET /enrichment/tasks/{task_id} ──────────────────────────────────────────

def _make_single_task_session_mock(record):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    result = AsyncMock()
    result.single = AsyncMock(return_value=record)
    session.run = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_get_enrichment_task_returns_task_for_valid_id():
    from datetime import datetime, timezone
    from finance_analytics.api.routes import get_enrichment_task_endpoint

    dt = datetime(2026, 6, 20, tzinfo=timezone.utc)
    sha256_id = "a" * 64  # sha256 hex — t.id property returned by the Cypher query
    record = {
        "task_id": sha256_id,
        "question_text": "What is the revenue trend?",
        "confidence_score": 0.45,
        "source": "query",
        "status": "open",
        "submitted_by": "dev-analyst",
        "created_at": _make_fake_neo4j_dt(dt),
    }
    session_mock = _make_single_task_session_mock(record)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        item = await get_enrichment_task_endpoint(
            task_id=sha256_id,
            current_user=("user-1", ["knowledge_engineer"]),
        )

    assert item.task_id == sha256_id
    assert item.question_text == "What is the revenue trend?"
    assert item.status == "open"


@pytest.mark.asyncio
async def test_get_enrichment_task_returns_404_for_unknown_id():
    from finance_analytics.api.routes import get_enrichment_task_endpoint

    session_mock = _make_single_task_session_mock(None)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        with pytest.raises(HTTPException) as exc_info:
            await get_enrichment_task_endpoint(
                task_id="does-not-exist",
                current_user=("user-1", ["knowledge_engineer"]),
            )

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_get_enrichment_task_raises_403_for_wrong_role():
    from finance_analytics.api.routes import get_enrichment_task_endpoint

    from fastapi import params

    sig = get_enrichment_task_endpoint.__wrapped__ if hasattr(get_enrichment_task_endpoint, "__wrapped__") else get_enrichment_task_endpoint
    import inspect
    parameters = inspect.signature(sig).parameters
    current_user_param = parameters.get("current_user")
    assert current_user_param is not None
    default = current_user_param.default
    assert isinstance(default, params.Depends)
    with pytest.raises(HTTPException) as exc_info:
        default.dependency(current_user=("user-1", ["analyst"]))
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_get_enrichment_task_propagates_driver_exception():
    """session.run() raising must propagate out (FastAPI converts to HTTP 500)."""
    from finance_analytics.api.routes import get_enrichment_task_endpoint

    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.run = AsyncMock(side_effect=RuntimeError("Neo4j unavailable"))
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        with pytest.raises(RuntimeError, match="Neo4j unavailable"):
            await get_enrichment_task_endpoint(
                task_id="any-id",
                current_user=("user-1", ["knowledge_engineer"]),
            )


@pytest.mark.asyncio
async def test_get_enrichment_task_null_created_at_coerced():
    """created_at=None must pass through _coerce_neo4j_dt as None, not raise."""
    from finance_analytics.api.routes import get_enrichment_task_endpoint

    sha256_id = "b" * 64
    record = {
        "task_id": sha256_id,
        "question_text": "Null date task",
        "confidence_score": None,
        "source": "manual",
        "status": "open",
        "submitted_by": None,
        "created_at": None,
    }
    session_mock = _make_single_task_session_mock(record)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        item = await get_enrichment_task_endpoint(
            task_id=sha256_id,
            current_user=("user-1", ["knowledge_engineer"]),
        )

    assert item.created_at is None
    assert item.submitted_by is None


# ── PATCH /enrichment/tasks/{task_id} ────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_enrichment_task_resolves_open_task():
    from finance_analytics.api.routes import patch_enrichment_task_endpoint, _PatchTaskRequest

    sha256_id = "c" * 64
    record = {
        "task_id": sha256_id,
        "question_text": "Revenue gap?",
        "confidence_score": 0.4,
        "source": "query",
        "status": "resolved",
        "submitted_by": "dev-analyst",
        "created_at": None,
    }
    session_mock = _make_single_task_session_mock(record)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        item = await patch_enrichment_task_endpoint(
            request=_PatchTaskRequest(status="resolved"),
            task_id=sha256_id,
            current_user=("user-1", ["knowledge_engineer"]),
        )

    assert item.task_id == sha256_id
    assert item.status == "resolved"
    session_mock.run.assert_awaited_once()
    call_kwargs = session_mock.run.call_args[1]
    assert call_kwargs.get("new_status") == "resolved"


@pytest.mark.asyncio
async def test_patch_enrichment_task_rejects_invalid_status():
    from finance_analytics.api.routes import patch_enrichment_task_endpoint, _PatchTaskRequest

    with pytest.raises(HTTPException) as exc_info:
        await patch_enrichment_task_endpoint(
            request=_PatchTaskRequest(status="deleted"),
            task_id="any-id",
            current_user=("user-1", ["knowledge_engineer"]),
        )

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_patch_enrichment_task_returns_404_for_unknown_id():
    from finance_analytics.api.routes import patch_enrichment_task_endpoint, _PatchTaskRequest

    session_mock = _make_single_task_session_mock(None)
    neo4j_mock = MagicMock()
    neo4j_mock.driver.session.return_value = session_mock

    with patch("finance_analytics.api.routes.conn") as mock_conn:
        mock_conn.get_neo4j.return_value = neo4j_mock
        with pytest.raises(HTTPException) as exc_info:
            await patch_enrichment_task_endpoint(
                request=_PatchTaskRequest(status="resolved"),
                task_id="does-not-exist",
                current_user=("user-1", ["knowledge_engineer"]),
            )

    assert exc_info.value.status_code == 404

