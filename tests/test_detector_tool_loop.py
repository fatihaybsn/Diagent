"""Tests for the tool_loop anomaly detector."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.asyncio
async def test_tool_loop_should_trigger(
    client: AsyncClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """5 identical tool calls with threshold=3 → alert must be created."""
    monkeypatch.setenv("TOOL_LOOP_THRESHOLD", "3")

    # Create a run
    resp = await client.post(
        "/runs", json={"agent_name": "test-agent", "input": "loop test"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Add 5 identical tool calls
    for i in range(5):
        resp = await client.post(
            f"/runs/{run_id}/tool_calls",
            json={
                "tool_name": "web_search",
                "args": {"query": f"attempt {i}"},
                "status": "success",
                "duration_ms": 100,
            },
        )
        assert resp.status_code == 201

    # Run detector
    from diagent.core.anomaly_detector import detect_tool_loop

    triggered = detect_tool_loop(run_id, sync_engine)

    assert triggered is True

    # Verify alert exists in DB
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type, severity FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 1
    assert alerts[0][0] == "tool_loop"
    assert alerts[0][1] == "warning"


@pytest.mark.asyncio
async def test_tool_loop_should_not_trigger(
    client: AsyncClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2 different tool calls with threshold=3 → no alert."""
    monkeypatch.setenv("TOOL_LOOP_THRESHOLD", "3")

    # Create a run
    resp = await client.post(
        "/runs", json={"agent_name": "test-agent", "input": "no loop test"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Add 2 different tool calls
    for tool in ["web_search", "calculator"]:
        resp = await client.post(
            f"/runs/{run_id}/tool_calls",
            json={
                "tool_name": tool,
                "args": {"q": "test"},
                "status": "success",
                "duration_ms": 100,
            },
        )
        assert resp.status_code == 201

    # Run detector
    from diagent.core.anomaly_detector import detect_tool_loop

    triggered = detect_tool_loop(run_id, sync_engine)

    assert triggered is False

    # Verify no alert in DB
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 0
