"""Tests for the cost_spike anomaly detector."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.asyncio
async def test_cost_spike_should_trigger(
    client: AsyncClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cost_usd=0.50 vs baseline avg=0.005 with multiplier=5 → alert."""
    monkeypatch.setenv("COST_SPIKE_MULTIPLIER", "5.0")

    # Create baseline runs (same agent) to establish average cost
    for _ in range(3):
        resp = await client.post(
            "/runs", json={"agent_name": "cost-agent", "input": "baseline"}
        )
        assert resp.status_code == 201
        baseline_id = resp.json()["id"]
        resp = await client.post(
            f"/runs/{baseline_id}/finish",
            json={"output": "ok", "total_tokens": 500, "cost_usd": 0.005},
        )
        assert resp.status_code == 200

    # Create the expensive run
    resp = await client.post(
        "/runs", json={"agent_name": "cost-agent", "input": "spike test"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Finish with high cost
    resp = await client.post(
        f"/runs/{run_id}/finish",
        json={"output": "expensive", "total_tokens": 50000, "cost_usd": 0.50},
    )
    assert resp.status_code == 200

    # Run detector
    from diagent.core.anomaly_detector import detect_cost_spike

    triggered = detect_cost_spike(run_id, sync_engine)

    assert triggered is True

    # Verify alert exists
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type, severity FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 1
    assert alerts[0][0] == "cost_spike"
    assert alerts[0][1] == "warning"


@pytest.mark.asyncio
async def test_cost_spike_should_not_trigger(
    client: AsyncClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cost_usd=0.006 vs baseline avg=0.005 with multiplier=5 → no alert."""
    monkeypatch.setenv("COST_SPIKE_MULTIPLIER", "5.0")

    # Create baseline runs
    for _ in range(3):
        resp = await client.post(
            "/runs", json={"agent_name": "cost-agent-ok", "input": "baseline"}
        )
        assert resp.status_code == 201
        baseline_id = resp.json()["id"]
        resp = await client.post(
            f"/runs/{baseline_id}/finish",
            json={"output": "ok", "total_tokens": 500, "cost_usd": 0.005},
        )
        assert resp.status_code == 200

    # Create a normal-cost run
    resp = await client.post(
        "/runs", json={"agent_name": "cost-agent-ok", "input": "normal test"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    resp = await client.post(
        f"/runs/{run_id}/finish",
        json={"output": "normal", "total_tokens": 600, "cost_usd": 0.006},
    )
    assert resp.status_code == 200

    # Run detector
    from diagent.core.anomaly_detector import detect_cost_spike

    triggered = detect_cost_spike(run_id, sync_engine)

    assert triggered is False

    # Verify no alert
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 0
