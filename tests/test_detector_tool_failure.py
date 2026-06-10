"""Tests for the tool_failure anomaly detector."""

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


@pytest.mark.asyncio
async def test_tool_failure_should_trigger(
    client: AsyncClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """3/3 tool calls failed (rate=1.0) with threshold=0.5 → alert."""
    monkeypatch.setenv("TOOL_FAILURE_RATE", "0.5")

    # Create a run
    resp = await client.post(
        "/runs", json={"agent_name": "test-agent", "input": "failure test"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # Add 3 failing tool calls
    error_tools = [
        ("database_query", "ConnectionRefusedError"),
        ("email_sender", "SMTPAuthenticationError"),
        ("payment_gateway", "TimeoutError"),
    ]
    for tool_name, error_msg in error_tools:
        resp = await client.post(
            f"/runs/{run_id}/tool_calls",
            json={
                "tool_name": tool_name,
                "args": {"action": "execute"},
                "status": "error",
                "error": error_msg,
                "duration_ms": 5000,
            },
        )
        assert resp.status_code == 201

    # Run detector
    from diagent.core.anomaly_detector import detect_tool_failure

    triggered = detect_tool_failure(run_id, sync_engine)

    assert triggered is True

    # Verify alert exists
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type, severity FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 1
    assert alerts[0][0] == "tool_failure"
    assert alerts[0][1] == "critical"


@pytest.mark.asyncio
async def test_tool_failure_should_not_trigger(
    client: AsyncClient, sync_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1/3 tool calls failed (rate=0.33) with threshold=0.5 → no alert."""
    monkeypatch.setenv("TOOL_FAILURE_RATE", "0.5")

    # Create a run
    resp = await client.post(
        "/runs", json={"agent_name": "test-agent", "input": "partial failure"}
    )
    assert resp.status_code == 201
    run_id = resp.json()["id"]

    # 1 error + 2 success
    resp = await client.post(
        f"/runs/{run_id}/tool_calls",
        json={
            "tool_name": "database_query",
            "args": {"action": "execute"},
            "status": "error",
            "error": "ConnectionRefusedError",
            "duration_ms": 5000,
        },
    )
    assert resp.status_code == 201

    for tool_name in ["email_sender", "payment_gateway"]:
        resp = await client.post(
            f"/runs/{run_id}/tool_calls",
            json={
                "tool_name": tool_name,
                "args": {"action": "execute"},
                "status": "success",
                "duration_ms": 200,
            },
        )
        assert resp.status_code == 201

    # Run detector
    from diagent.core.anomaly_detector import detect_tool_failure

    triggered = detect_tool_failure(run_id, sync_engine)

    assert triggered is False

    # Verify no alert
    with sync_engine.connect() as conn:
        alerts = conn.execute(
            text("SELECT type FROM alerts WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    assert len(alerts) == 0
