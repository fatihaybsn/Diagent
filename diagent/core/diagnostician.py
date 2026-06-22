"""Read-only LangGraph diagnostician for ambiguous low-quality RAG runs."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, TypedDict

from sqlalchemy import text
from sqlalchemy.engine import Engine

try:  # pragma: no cover - exercised when langgraph is installed in Docker
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover - local dev/test fallback
    END = "__end__"
    StateGraph = None


ROOT_CAUSES = {
    "stale_document",
    "weak_retrieval",
    "tool_failure",
    "tool_loop",
    "cost_spike",
    "answer_not_grounded",
    "unknown",
}


class DiagnosisLLM(Protocol):
    """Minimal JSON completion interface used by the reason node."""

    def complete_json(self, prompt: str) -> str:
        """Return a JSON object as text."""


class DiagnosticianState(TypedDict, total=False):
    """LangGraph state for the two-node diagnosis graph."""

    run_id: str
    evidence_bundle: dict[str, Any]
    diagnosis: dict[str, Any]


def get_run_details(run_id: str, engine: Engine) -> dict[str, Any] | None:
    """Read run metadata and output for diagnosis evidence."""
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT r.id, r.input, r.output, r.status, r.duration_ms, "
                    "r.total_tokens, r.cost_usd, r.created_at, "
                    "a.name AS agent_name, a.version AS agent_version "
                    "FROM runs r JOIN agents a ON a.id = r.agent_id "
                    "WHERE r.id = :rid"
                ),
                {"rid": run_id},
            )
            .mappings()
            .fetchone()
        )

    return _json_ready(dict(row)) if row is not None else None


def get_alerts(run_id: str, engine: Engine) -> list[dict[str, Any]]:
    """Read alerts for a run."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT id, type, severity, message, created_at "
                    "FROM alerts WHERE run_id = :rid ORDER BY created_at DESC"
                ),
                {"rid": run_id},
            )
            .mappings()
            .fetchall()
        )

    return [_json_ready(dict(row)) for row in rows]


def get_evaluation_scores(run_id: str, engine: Engine) -> dict[str, Any] | None:
    """Read the latest RAG evaluation scores for a run."""
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    "SELECT faithfulness, answer_relevancy, context_precision, "
                    "overall_score, created_at "
                    "FROM evaluations WHERE run_id = :rid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"rid": run_id},
            )
            .mappings()
            .fetchone()
        )

    return _json_ready(dict(row)) if row is not None else None


def get_retrieval_info(run_id: str, engine: Engine) -> list[dict[str, Any]]:
    """Read retrieval summaries without mutating run state."""
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT query, retrieved_chunks, top_k, source_age_hours "
                    "FROM retrievals WHERE run_id = :rid ORDER BY id"
                ),
                {"rid": run_id},
            )
            .mappings()
            .fetchall()
        )

    return [_summarize_retrieval(dict(row)) for row in rows]


def build_diagnostician_graph(engine: Engine, llm: DiagnosisLLM):
    """Build the required gather_evidence -> reason graph."""

    def gather_evidence(state: DiagnosticianState) -> DiagnosticianState:
        run_id = state["run_id"]
        return {
            "evidence_bundle": {
                "run": get_run_details(run_id, engine),
                "alerts": get_alerts(run_id, engine),
                "evaluation": get_evaluation_scores(run_id, engine),
                "retrievals": get_retrieval_info(run_id, engine),
            }
        }

    def reason(state: DiagnosticianState) -> DiagnosticianState:
        evidence_bundle = state["evidence_bundle"]
        prompt = _build_reason_prompt(evidence_bundle)
        raw = llm.complete_json(prompt)
        return {"diagnosis": _parse_diagnosis_json(raw)}

    if StateGraph is None:
        return _LinearDiagnosticianGraph(gather_evidence, reason)

    graph = StateGraph(DiagnosticianState)
    graph.add_node("gather_evidence", gather_evidence)
    graph.add_node("reason", reason)
    graph.set_entry_point("gather_evidence")
    graph.add_edge("gather_evidence", "reason")
    graph.add_edge("reason", END)
    return graph.compile()


def diagnose_run(run_id: str, engine: Engine, llm: DiagnosisLLM) -> dict[str, Any]:
    """Run the two-node diagnostician graph and return validated JSON."""
    graph = build_diagnostician_graph(engine, llm)
    final_state = graph.invoke({"run_id": run_id})
    return final_state["diagnosis"]


class _LinearDiagnosticianGraph:
    """Small fallback so tests can run before Docker installs langgraph."""

    def __init__(
        self,
        gather_evidence: Callable[[DiagnosticianState], DiagnosticianState],
        reason: Callable[[DiagnosticianState], DiagnosticianState],
    ) -> None:
        self._gather_evidence = gather_evidence
        self._reason = reason

    def invoke(self, state: DiagnosticianState) -> DiagnosticianState:
        next_state = dict(state)
        next_state.update(self._gather_evidence(next_state))
        next_state.update(self._reason(next_state))
        return next_state


def _build_reason_prompt(evidence_bundle: dict[str, Any]) -> str:
    evidence_json = json.dumps(evidence_bundle, ensure_ascii=False, indent=2)
    root_values = "|".join(sorted(ROOT_CAUSES))
    return f"""
You are Diagent's read-only diagnostician.
Use only the supplied evidence. Do not suggest writing to the database,
calling external services, reindexing, or automatic fixes.

Choose the most likely root cause from:
{root_values}

Return only valid JSON in this exact shape:
{{
  "root_cause": "weak_retrieval",
  "confidence": 0.0,
  "evidence": ["short evidence string"],
  "recommendation": "short recommendation"
}}

Evidence:
{evidence_json}
""".strip()


def _parse_diagnosis_json(raw: str) -> dict[str, Any]:
    parsed = json.loads(_extract_json_object(raw))
    if not isinstance(parsed, dict):
        raise ValueError("Diagnosis LLM response must be a JSON object")

    root_cause = str(parsed.get("root_cause", "unknown"))
    if root_cause not in ROOT_CAUSES:
        root_cause = "unknown"

    evidence = parsed.get("evidence", [])
    if isinstance(evidence, str):
        evidence = [evidence]
    if not isinstance(evidence, list):
        evidence = []

    recommendation = parsed.get("recommendation") or ""

    return {
        "root_cause": root_cause,
        "confidence": _clamp_confidence(parsed.get("confidence", 0.0)),
        "evidence": [str(item) for item in evidence],
        "recommendation": str(recommendation),
    }


def _extract_json_object(raw: str) -> str:
    text_value = raw.strip()
    if text_value.startswith("```"):
        lines = [
            line for line in text_value.splitlines() if not line.strip().startswith("```")
        ]
        text_value = "\n".join(lines).strip()

    try:
        json.loads(text_value)
        return text_value
    except json.JSONDecodeError:
        start = text_value.find("{")
        end = text_value.rfind("}")
        if start != -1 and end != -1 and end > start:
            return text_value[start : end + 1]
        raise


def _clamp_confidence(value: Any) -> float:
    score = float(value)
    return round(min(1.0, max(0.0, score)), 3)


def _summarize_retrieval(row: dict[str, Any]) -> dict[str, Any]:
    chunks = row.get("retrieved_chunks") or []
    if not isinstance(chunks, list):
        chunks = [chunks]

    return {
        "query": row.get("query"),
        "top_k": row.get("top_k"),
        "source_age_hours": _json_ready(row.get("source_age_hours")),
        "chunk_count": len(chunks),
        "chunk_previews": [_summarize_chunk(chunk) for chunk in chunks[:3]],
    }


def _summarize_chunk(chunk: Any) -> dict[str, Any]:
    if not isinstance(chunk, dict):
        return {"text": str(chunk)[:300]}

    text_value = chunk.get("text") or chunk.get("content") or json.dumps(
        chunk, ensure_ascii=False
    )
    return {
        "text": str(text_value)[:300],
        "source": chunk.get("source"),
        "score": _json_ready(chunk.get("score")),
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value
