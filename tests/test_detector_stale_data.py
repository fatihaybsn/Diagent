"""Tests for the stale_data anomaly detector."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.asyncio
async def test_stale_data_should_trigger(
    client: AsyncClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """source_age_hours=96 with threshold=72 → alert must be created."""
    monkeypatch.setenv("STALE_DATA_HOURS", "72.0")

    # Create a run
    resp = await client.post(
        "/runs", json={"agent_name": "test-agent", "input": "stale test"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Add a retrieval with stale source
    resp = await client.post(
        f"/runs/{run_id}/retrievals",
        json={
            "query": "refund policy",
            "retrieved_chunks": [
                {"text": "Old policy from 2022", "score": 0.75, "source": "old.md"},
            ],
            "top_k": 5,
            "source_age_hours": 96.0,
        },
    )
    assert resp.status_code == 201

    # Run detector
    from diagent.core.anomaly_detector import detect_stale_data

    triggered = detect_stale_data(run_id, sync_engine)

    assert triggered is True

    # Verify alert exists
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type, severity FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 1
    assert alerts[0][0] == "stale_data"
    assert alerts[0][1] == "warning"


@pytest.mark.asyncio
async def test_stale_data_should_not_trigger(
    client: AsyncClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """source_age_hours=24 with threshold=72 → no alert."""
    monkeypatch.setenv("STALE_DATA_HOURS", "72.0")

    # Create a run
    resp = await client.post(
        "/runs", json={"agent_name": "test-agent", "input": "fresh test"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Add a retrieval with fresh source
    resp = await client.post(
        f"/runs/{run_id}/retrievals",
        json={
            "query": "refund policy",
            "retrieved_chunks": [
                {"text": "Current policy 2026", "score": 0.95, "source": "current.md"},
            ],
            "top_k": 5,
            "source_age_hours": 24.0,
        },
    )
    assert resp.status_code == 201

    # Run detector
    from diagent.core.anomaly_detector import detect_stale_data

    triggered = detect_stale_data(run_id, sync_engine)

    assert triggered is False

    # Verify no alert
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 0
