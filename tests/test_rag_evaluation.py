"""Tests for RAG evaluation judge backends."""

from __future__ import annotations

import pytest
from diagent.core import rag_quality


def test_openai_judge_backend_evaluates_mocked_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_ollama_judge_backend_evaluates_mocked_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
