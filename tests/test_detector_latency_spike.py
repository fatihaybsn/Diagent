"""Tests for the latency_spike anomaly detector."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.asyncio
async def test_latency_spike_should_trigger(
    client: AsyncClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """duration_ms=5000 with threshold=3000 → alert must be created."""
    monkeypatch.setenv("LATENCY_SPIKE_MS", "3000")

    # Create a run
    resp = await client.post(
        "/runs", json={"agent_name": "test-agent", "input": "latency test"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Finish run with 5000ms duration
    resp = await client.post(
        f"/runs/{run_id}/finish",
        json={"output": "done", "cost_usd": 0.0, "total_tokens": 10},
    )
    assert resp.status_code == 200

    # Manually update duration_ms in DB to 5000ms to override elapsed time calculation
    with sync_engine.connect() as conn:
        conn.execute(
            text("UPDATE runs SET duration_ms = 5000 WHERE id = :rid"),
            {"rid": run_id},
        )
        conn.commit()

    # Run detector
    from diagent.core.anomaly_detector import detect_latency_spike

    triggered = detect_latency_spike(run_id, sync_engine)

    assert triggered is True

    # Verify alert exists
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type, severity FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 1
    assert alerts[0][0] == "latency_spike"
    assert alerts[0][1] == "warning"


@pytest.mark.asyncio
async def test_latency_spike_should_not_trigger(
    client: AsyncClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """duration_ms=1000 with threshold=3000 → no alert."""
    monkeypatch.setenv("LATENCY_SPIKE_MS", "3000")

    # Create a run
    resp = await client.post(
        "/runs", json={"agent_name": "test-agent", "input": "latency test 2"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Finish run
    resp = await client.post(
        f"/runs/{run_id}/finish",
        json={"output": "done", "cost_usd": 0.0, "total_tokens": 10},
    )
    assert resp.status_code == 200

    # Manually update duration_ms in DB to 1000ms
    with sync_engine.connect() as conn:
        conn.execute(
            text("UPDATE runs SET duration_ms = 1000 WHERE id = :rid"),
            {"rid": run_id},
        )
        conn.commit()

    # Run detector
    from diagent.core.anomaly_detector import detect_latency_spike

    triggered = detect_latency_spike(run_id, sync_engine)

    assert triggered is False

    # Verify no alert
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 0
