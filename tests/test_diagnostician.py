"""Tests for the read-only diagnostician agent and API."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


class FakeDiagnosisLLM:
    """Deterministic diagnosis LLM used instead of an external backend."""

    def complete_json(self, prompt: str) -> str:
        assert "overall_score" in prompt
        assert "stale_data" in prompt
        assert "tool_failure" in prompt
        return """
        {
          "root_cause": "weak_retrieval",
          "confidence": 0.82,
          "evidence": [
            "overall_score is below 0.6",
            "multiple alerts make the root cause ambiguous"
          ],
          "recommendation": "Review retrieval freshness and failed tool evidence before changing prompts."
        }
        """


class LowScoreJudge:
    """RAG judge that forces the diagnosis trigger path."""

    def evaluate(self, query: str, answer: str, context: list[dict]) -> dict[str, float]:
        assert query
        assert answer
        assert context
        return {
            "faithfulness": 0.2,
            "answer_relevancy": 0.4,
            "context_precision": 0.3,
            "overall_score": 0.3,
        }


async def _create_low_quality_seed_run(client: AsyncClient) -> str:
    response = await client.post(
        "/runs",
        json={"agent_name": "diagnosis-seed", "input": "Refund policy nedir?"},
    )
    assert response.status_code == 201
    run_id = response.json()["id"]

    response = await client.post(
        f"/runs/{run_id}/retrievals",
        json={
            "query": "Refund policy nedir?",
            "retrieved_chunks": [
                {
                    "text": "Old refund policy says 30 days.",
                    "score": 0.41,
                    "source": "old_policy.md",
                }
            ],
            "top_k": 3,
            "source_age_hours": 96.0,
        },
    )
    assert response.status_code == 201

    response = await client.post(
        f"/runs/{run_id}/tool_calls",
        json={
            "tool_name": "policy_lookup",
            "args": {"query": "refund"},
            "status": "error",
            "error": "TimeoutError",
            "duration_ms": 1500,
        },
    )
    assert response.status_code == 201

    response = await client.post(
        f"/runs/{run_id}/finish",
        json={
            "output": "Refunds are processed in 30 days.",
            "total_tokens": 250,
            "cost_usd": 0.002,
        },
    )
    assert response.status_code == 200
    return run_id


def _insert_alerts(sync_engine: Engine, run_id: str) -> None:
    with sync_engine.begin() as conn:
        for alert_type in ("stale_data", "tool_failure"):
            conn.execute(
                text(
                    "INSERT INTO alerts "
                    "(id, run_id, type, severity, message, created_at) "
                    "VALUES (:id, :run_id, :type, 'warning', :message, now())"
                ),
                {
                    "id": str(uuid4()),
                    "run_id": run_id,
                    "type": alert_type,
                    "message": f"{alert_type} synthetic alert",
                },
            )


def _insert_low_score(sync_engine: Engine, run_id: str) -> None:
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO evaluations "
                "(id, run_id, faithfulness, answer_relevancy, "
                "context_precision, overall_score, created_at) "
                "VALUES (:id, :run_id, 0.2, 0.4, 0.3, 0.3, now())"
            ),
            {"id": str(uuid4()), "run_id": run_id},
        )


@pytest.mark.asyncio
async def test_run_diagnosis_writes_row_for_low_score_multi_alert_seed(
    client: AsyncClient,
    sync_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Low RAG score + multiple alerts produces a diagnosis row."""
    import diagent.workers.tasks as tasks_module

    run_id = await _create_low_quality_seed_run(client)
    _insert_alerts(sync_engine, run_id)
    _insert_low_score(sync_engine, run_id)
    monkeypatch.setattr(
        tasks_module, "_build_judge", lambda: FakeDiagnosisLLM()
    )

    result = tasks_module.run_diagnosis(run_id)

    assert result["status"] == "diagnosed"
    assert result["diagnosis"]["root_cause"] == "weak_retrieval"
    with sync_engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT root_cause, confidence, evidence, recommendation "
                    "FROM diagnoses WHERE run_id = :rid"
                ),
                {"rid": run_id},
            )
            .mappings()
            .fetchone()
        )

    assert row is not None
    assert row["root_cause"] == "weak_retrieval"
    assert float(row["confidence"]) == 0.82
    assert row["evidence"] == [
        "overall_score is below 0.6",
        "multiple alerts make the root cause ambiguous",
    ]

    response = await client.get(f"/diagnoses/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["root_cause"] == "weak_retrieval"
    assert data["evidence"] == row["evidence"]


@pytest.mark.asyncio
async def test_rag_evaluation_enqueues_diagnosis_after_low_score_multi_alerts(
    client: AsyncClient,
    sync_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RAG evaluation queues diagnosis when the trigger condition is met."""
    import diagent.workers.tasks as tasks_module

    run_id = await _create_low_quality_seed_run(client)
    _insert_alerts(sync_engine, run_id)
    monkeypatch.setattr(tasks_module, "_build_judge", lambda: LowScoreJudge())

    queued_run_ids: list[str] = []

    def queue_diagnosis(queued_run_id: str) -> SimpleNamespace:
        queued_run_ids.append(queued_run_id)
        return SimpleNamespace(id="diagnosis-task-id")

    monkeypatch.setattr(tasks_module.run_diagnosis, "delay", queue_diagnosis)

    result = tasks_module.run_rag_evaluation(run_id)

    assert result["status"] == "evaluated"
    assert result["diagnosis_trigger"]["eligible"] is True
    assert result["diagnosis_task_id"] == "diagnosis-task-id"
    assert queued_run_ids == [run_id]


# ---------------------------------------------------------------------------
# Edge-case tests for _diagnosis_trigger_state
# ---------------------------------------------------------------------------


class FakeDiagnosisLLMNoAlerts:
    """Deterministic LLM for the 0-alert scenario."""

    def complete_json(self, prompt: str) -> str:
        assert "overall_score" in prompt
        return """
        {
          "root_cause": "answer_not_grounded",
          "confidence": 0.70,
          "evidence": [
            "overall_score is below 0.6",
            "no rule-based alerts — cause is unknown"
          ],
          "recommendation": "Investigate retrieval pipeline manually."
        }
        """


def _insert_single_alert(sync_engine: Engine, run_id: str) -> None:
    """Insert exactly one alert for a run."""
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts "
                "(id, run_id, type, severity, message, created_at) "
                "VALUES (:id, :run_id, 'tool_failure', 'warning', "
                "'single tool_failure alert', now())"
            ),
            {"id": str(uuid4()), "run_id": run_id},
        )


@pytest.mark.asyncio
async def test_diagnosis_triggers_with_low_score_and_zero_alerts(
    client: AsyncClient,
    sync_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Low RAG score + 0 alerts → diagnosis should run (unknown cause)."""
    import diagent.workers.tasks as tasks_module

    run_id = await _create_low_quality_seed_run(client)
    # No alerts inserted — 0 alerts
    _insert_low_score(sync_engine, run_id)
    monkeypatch.setattr(
        tasks_module, "_build_judge", lambda: FakeDiagnosisLLMNoAlerts()
    )

    result = tasks_module.run_diagnosis(run_id)

    assert result["status"] == "diagnosed"
    assert result["trigger"]["eligible"] is True
    assert result["trigger"]["reason"] == "low_score_no_alerts_unknown_cause"
    assert result["trigger"]["alert_count"] == 0

    with sync_engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT root_cause FROM diagnoses WHERE run_id = :rid"
                ),
                {"rid": run_id},
            )
            .mappings()
            .fetchone()
        )
    assert row is not None
    assert row["root_cause"] == "answer_not_grounded"


@pytest.mark.asyncio
async def test_diagnosis_skipped_with_low_score_and_single_alert(
    client: AsyncClient,
    sync_engine: Engine,
) -> None:
    """Low RAG score + 1 alert → diagnosis should NOT run (clear cause)."""
    import diagent.workers.tasks as tasks_module

    run_id = await _create_low_quality_seed_run(client)
    _insert_single_alert(sync_engine, run_id)
    _insert_low_score(sync_engine, run_id)

    result = tasks_module.run_diagnosis(run_id)

    assert result["status"] == "skipped"
    assert result["trigger"]["eligible"] is False
    assert result["trigger"]["reason"] == "single_alert_clear_cause"
    assert result["trigger"]["alert_count"] == 1


@pytest.mark.asyncio
async def test_diagnosis_triggers_with_low_score_and_multiple_alerts(
    client: AsyncClient,
    sync_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Low RAG score + 2+ alerts → diagnosis should run (ambiguous cause)."""
    import diagent.workers.tasks as tasks_module

    run_id = await _create_low_quality_seed_run(client)
    _insert_alerts(sync_engine, run_id)  # 2 alerts: stale_data + tool_failure
    _insert_low_score(sync_engine, run_id)
    monkeypatch.setattr(
        tasks_module, "_build_judge", lambda: FakeDiagnosisLLM()
    )

    result = tasks_module.run_diagnosis(run_id)

    assert result["status"] == "diagnosed"
    assert result["trigger"]["eligible"] is True
    assert result["trigger"]["reason"] == "low_score_with_multiple_alerts"
    assert result["trigger"]["alert_count"] == 2


@pytest.mark.asyncio
async def test_diagnosis_skipped_with_high_score_regardless_of_alerts(
    client: AsyncClient,
    sync_engine: Engine,
) -> None:
    """High RAG score → diagnosis never triggers, regardless of alert count."""
    import diagent.workers.tasks as tasks_module

    run_id = await _create_low_quality_seed_run(client)
    _insert_alerts(sync_engine, run_id)  # 2 alerts

    # Insert a high evaluation score (above default threshold 0.6)
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO evaluations "
                "(id, run_id, faithfulness, answer_relevancy, "
                "context_precision, overall_score, created_at) "
                "VALUES (:id, :run_id, 0.9, 0.8, 0.85, 0.85, now())"
            ),
            {"id": str(uuid4()), "run_id": run_id},
        )

    result = tasks_module.run_diagnosis(run_id)

    assert result["status"] == "skipped"
    assert result["trigger"]["eligible"] is False
    assert result["trigger"]["reason"] == "score_not_low"
