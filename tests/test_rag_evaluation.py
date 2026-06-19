"""Tests for RAG evaluation task and endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


class FakeJudge:
    """Deterministic judge used instead of an external LLM."""

    def evaluate(self, query: str, answer: str, context: list[dict]) -> dict[str, float]:
        assert "süresi" in query
        assert "14 gün" in answer
        assert context
        return {
            "faithfulness": 0.9,
            "answer_relevancy": 0.8,
            "context_precision": 0.7,
            "overall_score": 0.8,
        }


async def _create_rag_run(client: AsyncClient) -> str:
    response = await client.post(
        "/runs",
        json={"agent_name": "test-agent", "input": "İade süresi nedir?"},
    )
    assert response.status_code == 201
    run_id = response.json()["id"]

    response = await client.post(
        f"/runs/{run_id}/retrievals",
        json={
            "query": "İade süresi nedir?",
            "retrieved_chunks": [
                {
                    "text": "İade işlemleri 14 gün içinde yapılabilir.",
                    "score": 0.95,
                    "source": "faq.md",
                }
            ],
            "top_k": 3,
            "source_age_hours": 4.0,
        },
    )
    assert response.status_code == 201

    response = await client.post(
        f"/runs/{run_id}/finish",
        json={
            "output": "İade işleminizi 14 gün içinde yapabilirsiniz.",
            "total_tokens": 120,
            "cost_usd": 0.001,
        },
    )
    assert response.status_code == 200
    return run_id


@pytest.mark.asyncio
async def test_trigger_rag_evaluation_then_get_run_shows_scores(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /evaluations/run/{id} → GET /runs/{id} includes scores."""
    from types import SimpleNamespace

    import diagent.workers.tasks as tasks_module

    run_id = await _create_rag_run(client)
    monkeypatch.setattr(tasks_module, "_build_judge", lambda: FakeJudge())

    def run_now(queued_run_id: str) -> SimpleNamespace:
        tasks_module.run_rag_evaluation(queued_run_id)
        return SimpleNamespace(id="test-task-id")

    monkeypatch.setattr(tasks_module.run_rag_evaluation, "delay", run_now)

    response = await client.post(f"/evaluations/run/{run_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == run_id
    assert data["status"] == "queued"
    assert data["task_id"] == "test-task-id"

    response = await client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    evaluation = response.json()["evaluation"]
    assert evaluation is not None
    assert evaluation["faithfulness"] == 0.9
    assert evaluation["answer_relevancy"] == 0.8
    assert evaluation["context_precision"] == 0.7
    assert evaluation["overall_score"] == 0.8


@pytest.mark.asyncio
async def test_rag_evaluation_writes_scores_for_retrieval_run(
    client: AsyncClient,
    sync_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run with retrievals gets 0.0-1.0 evaluation scores."""
    import diagent.workers.tasks as tasks_module

    run_id = await _create_rag_run(client)
    monkeypatch.setattr(tasks_module, "_build_judge", lambda: FakeJudge())

    result = tasks_module.run_rag_evaluation(run_id)

    assert result["status"] == "evaluated"
    with sync_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT faithfulness, answer_relevancy, context_precision, "
                "overall_score FROM evaluations WHERE run_id = :rid"
            ),
            {"rid": run_id},
        ).fetchone()

    assert row is not None
    scores = [float(value) for value in row]
    assert scores == [0.9, 0.8, 0.7, 0.8]
    assert all(0.0 <= score <= 1.0 for score in scores)


def test_openai_judge_backend_evaluates_mocked_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI/API judge path posts chat completions and parses scores."""
    from diagent.core import rag_quality

    calls = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "choices": [
                    {"message": {"content": '{"score": 0.6, "reason": "ok"}'}}
                ]
            }

    def fake_post(url: str, **kwargs) -> FakeResponse:
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(rag_quality.httpx, "post", fake_post)
    judge = rag_quality.OpenAIJudge(
        api_key="test-key",
        base_url="https://api.test/v1",
        model="judge-model",
        rate_limit_seconds=0,
    )

    scores = judge.evaluate("query", "answer", [{"text": "answer"}])

    assert scores == {
        "faithfulness": 0.6,
        "answer_relevancy": 0.6,
        "context_precision": 0.6,
        "overall_score": 0.6,
    }
    assert len(calls) == 3
    assert all(call[0] == "https://api.test/v1/chat/completions" for call in calls)
    assert all(call[1]["headers"]["Authorization"] == "Bearer test-key" for call in calls)


def test_ollama_judge_backend_evaluates_mocked_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ollama judge path posts /api/chat and parses scores."""
    from diagent.core import rag_quality

    calls = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"message": {"content": '{"score": 0.4, "reason": "ok"}'}}

    def fake_post(url: str, **kwargs) -> FakeResponse:
        calls.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(rag_quality.httpx, "post", fake_post)
    judge = rag_quality.OllamaJudge(
        base_url="http://ollama.test",
        model="llama-test",
        rate_limit_seconds=0,
    )

    scores = judge.evaluate("query", "answer", [{"text": "answer"}])

    assert scores == {
        "faithfulness": 0.4,
        "answer_relevancy": 0.4,
        "context_precision": 0.4,
        "overall_score": 0.4,
    }
    assert len(calls) == 3
    assert all(call[0] == "http://ollama.test/api/chat" for call in calls)
    assert all(call[1]["json"]["format"] == "json" for call in calls)
