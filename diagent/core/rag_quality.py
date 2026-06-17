"""LLM-as-a-judge scoring for RAG quality.

The evaluator follows the RAGAS-style split of:

* faithfulness: answer claims grounded in the retrieved context
* answer_relevancy: answer directly addresses the user query
* context_precision: retrieved chunks are relevant and ranked early
"""

from __future__ import annotations

import json
import os
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

ScoreDict = dict[str, float]

_JSON_SCORE_RE = re.compile(r'"?score"?\s*[:=]\s*(0(?:\.\d+)?|1(?:\.0+)?)')


class JudgeLLM(ABC):
    """Abstract interface for RAG judge LLM backends."""

    def __init__(self, *, rate_limit_seconds: float = 1.0) -> None:
        self.rate_limit_seconds = max(0.0, rate_limit_seconds)
        self._last_call_at = 0.0

    def evaluate(
        self,
        query: str,
        answer: str,
        context: Sequence[Mapping[str, Any]] | str,
    ) -> ScoreDict:
        """Evaluate a RAG answer and return normalized 0.0-1.0 scores."""
        context_text = _format_context(context)
        scores = {
            metric: self._score_metric(metric, query, answer, context_text)
            for metric in (
                "faithfulness",
                "answer_relevancy",
                "context_precision",
            )
        }
        scores["overall_score"] = round(sum(scores.values()) / 3, 3)
        return scores

    @abstractmethod
    def _complete_json(self, prompt: str) -> str:
        """Return a JSON string from the backend."""

    def _score_metric(
        self,
        metric: str,
        query: str,
        answer: str,
        context_text: str,
    ) -> float:
        prompt = _build_metric_prompt(metric, query, answer, context_text)
        self._wait_for_rate_limit()
        raw = self._complete_json(prompt)
        self._last_call_at = time.monotonic()
        return _extract_score(raw)

    def _wait_for_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_call_at
        remaining = self.rate_limit_seconds - elapsed
        if self._last_call_at and remaining > 0:
            time.sleep(remaining)


class OpenAIJudge(JudgeLLM):
    """OpenAI-backed judge using the Chat Completions API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        rate_limit_seconds: float = 1.0,
    ) -> None:
        super().__init__(rate_limit_seconds=rate_limit_seconds)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_JUDGE_MODEL", "gpt-4o-mini")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout = timeout

    def _complete_json(self, prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required when DIAGENT_JUDGE_BACKEND=openai")

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a strict RAGAS-style evaluator. "
                            "Return only valid JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    def complete_json(self, prompt: str) -> str:
        """DiagnosisLLM Protocol interface — public wrapper."""
        return self._complete_json(prompt)


class OllamaJudge(JudgeLLM):
    """Ollama-backed judge using the local /api/chat endpoint."""

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 120.0,
        rate_limit_seconds: float = 1.0,
    ) -> None:
        super().__init__(rate_limit_seconds=rate_limit_seconds)
        self.model = model or os.getenv("OLLAMA_JUDGE_MODEL", "llama3.1")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout

    def _complete_json(self, prompt: str) -> str:
        response = httpx.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a strict RAGAS-style evaluator. "
                            "Return only valid JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]

    def complete_json(self, prompt: str) -> str:
        """DiagnosisLLM Protocol interface — public wrapper."""
        return self._complete_json(prompt)


def _build_metric_prompt(
    metric: str,
    query: str,
    answer: str,
    context_text: str,
) -> str:
    metric_instructions = {
        "faithfulness": (
            "Evaluate faithfulness using the RAGAS method: break the answer "
            "into factual claims, verify each claim against the retrieved "
            "context, and score the fraction of answer claims supported by "
            "the context. Penalize unsupported or contradicted claims."
        ),
        "answer_relevancy": (
            "Evaluate answer relevancy using the RAGAS method: judge whether "
            "the answer directly and completely addresses the user query. "
            "Penalize evasive, incomplete, generic, or off-topic content."
        ),
        "context_precision": (
            "Evaluate context precision using the RAGAS method: inspect the "
            "retrieved chunks in order and judge whether relevant chunks for "
            "answering the query appear before irrelevant chunks. Score high "
            "when the retrieved context is relevant and well ranked."
        ),
    }
    if metric not in metric_instructions:
        raise ValueError(f"Unknown RAG quality metric: {metric}")

    return f"""
{metric_instructions[metric]}

Return only JSON with this schema:
{{"score": <number from 0.0 to 1.0>, "reason": "<short reason>"}}

User query:
{query}

Answer:
{answer}

Retrieved context:
{context_text}
""".strip()


def _format_context(context: Sequence[Mapping[str, Any]] | str) -> str:
    if isinstance(context, str):
        return context

    lines: list[str] = []
    for index, chunk in enumerate(context, start=1):
        text = chunk.get("text") or chunk.get("content") or json.dumps(chunk, ensure_ascii=False)
        source = chunk.get("source")
        score = chunk.get("score")

        metadata = []
        if source is not None:
            metadata.append(f"source={source}")
        if score is not None:
            metadata.append(f"retrieval_score={score}")

        suffix = f" ({', '.join(metadata)})" if metadata else ""
        lines.append(f"[{index}] {text}{suffix}")

    return "\n".join(lines)


def _extract_score(raw: str) -> float:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "score" in parsed:
            return _clamp_score(parsed["score"])
    except json.JSONDecodeError:
        pass

    match = _JSON_SCORE_RE.search(raw)
    if match:
        return _clamp_score(match.group(1))

    raise ValueError(f"Judge response did not include a valid score: {raw!r}")


def _clamp_score(value: Any) -> float:
    score = float(value)
    return round(min(1.0, max(0.0, score)), 3)
