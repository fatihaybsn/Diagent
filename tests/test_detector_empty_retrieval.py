"""Tests for the empty_retrieval anomaly detector."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.asyncio
async def test_empty_retrieval_should_trigger(
    client: AsyncClient, sync_engine: Engine
) -> None:
    """empty retrieved_chunks ([]) → alert must be created."""
    # Create a run
    resp = await client.post(
        "/runs", json={"agent_name": "test-agent", "input": "empty retrieval test"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Record retrieval with empty chunks
    resp = await client.post(
        f"/runs/{run_id}/retrievals",
        json={
            "query": "something secret",
            "retrieved_chunks": [],
            "top_k": 3,
            "source_age_hours": 12.0,
        },
    )
    assert resp.status_code == 201

    # Run detector
    from diagent.core.anomaly_detector import detect_empty_retrieval

    triggered = detect_empty_retrieval(run_id, sync_engine)

    assert triggered is True

    # Verify alert exists
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type, severity FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 1
    assert alerts[0][0] == "empty_retrieval"
    assert alerts[0][1] == "warning"


@pytest.mark.asyncio
async def test_empty_retrieval_should_not_trigger(
    client: AsyncClient, sync_engine: Engine
) -> None:
    """retrieved_chunks has content → no alert."""
    # Create a run
    resp = await client.post(
        "/runs", json={"agent_name": "test-agent", "input": "good retrieval test"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Record retrieval with non-empty chunks
    resp = await client.post(
        f"/runs/{run_id}/retrievals",
        json={
            "query": "company info",
            "retrieved_chunks": [{"text": "Found some information", "source": "docs.md"}],
            "top_k": 3,
            "source_age_hours": 12.0,
        },
    )
    assert resp.status_code == 201

    # Run detector
    from diagent.core.anomaly_detector import detect_empty_retrieval

    triggered = detect_empty_retrieval(run_id, sync_engine)

    assert triggered is False

    # Verify no alert
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 0
