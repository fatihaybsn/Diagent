"""Celery task definitions for Diagent."""

import logging
import os
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import bindparam
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from diagent.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_sync_database_url() -> str:
    """Convert the async DATABASE_URL to the installed sync psycopg2 driver."""
    url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://diagent:diagent@localhost:5432/diagent",
    )
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


@celery_app.task(name="diagent.run_anomaly_detection")
def run_anomaly_detection(run_id: str) -> dict:
    """Run all rule-based anomaly detectors for a finished run.

    Creates a sync SQLAlchemy engine, delegates to the core detector
    orchestrator, and returns a summary of which detectors triggered.
    """
    from diagent.core.anomaly_detector import run_all_detectors

    engine = create_engine(_get_sync_database_url())
    try:
        results = run_all_detectors(run_id, engine)
        triggered = [k for k, v in results.items() if v]

        if triggered:
            logger.info(
                "Anomaly detection done — run_id=%s  triggered=%s",
                run_id,
                triggered,
            )
        else:
            logger.info(
                "Anomaly detection done — run_id=%s  no anomalies", run_id
            )

        return {"run_id": run_id, "results": results}
    finally:
        engine.dispose()


def _judge_rate_limit_seconds() -> float:
    """Read the minimum wait between judge LLM calls."""
    return float(os.getenv("JUDGE_RATE_LIMIT_SECONDS", "1"))


def _build_judge():
    """Build the configured LLM backend (judge & diagnostician share this).

    The returned object satisfies both the JudgeLLM interface used by RAG
    evaluation and the DiagnosisLLM Protocol used by the diagnostician.
    Backend selection intentionally lives in the worker layer so core
    modules can remain independent from Celery, DB, and API wiring.
    """
    from diagent.core.rag_quality import OllamaJudge, OpenAIJudge

    backend = os.getenv("DIAGENT_JUDGE_BACKEND", "openai").strip().lower()
    rate_limit_seconds = _judge_rate_limit_seconds()

    if backend == "openai":
        return OpenAIJudge(rate_limit_seconds=rate_limit_seconds)
    if backend == "ollama":
        return OllamaJudge(rate_limit_seconds=rate_limit_seconds)

    raise ValueError(
        "Unsupported DIAGENT_JUDGE_BACKEND. Expected 'openai' or 'ollama', "
        f"got {backend!r}."
    )


def _diagnosis_score_threshold() -> float:
    """Read the RAG score threshold for triggering diagnosis."""
    return float(os.getenv("DIAGNOSIS_RAG_SCORE_THRESHOLD", "0.6"))


def _score_decimal(value: float) -> Decimal:
    """Convert a 0.0-1.0 float to the evaluations NUMERIC(4, 3) shape."""
    clamped = min(1.0, max(0.0, float(value)))
    return Decimal(str(round(clamped, 3)))


def _diagnosis_trigger_state(run_id: str, engine: Engine) -> dict[str, Any]:
    """Return whether this run should enter the diagnostician task."""
    threshold = _diagnosis_score_threshold()

    with engine.connect() as conn:
        run_exists = conn.execute(
            text("SELECT 1 FROM runs WHERE id = :rid"),
            {"rid": run_id},
        ).scalar_one_or_none()
        if run_exists is None:
            return {
                "eligible": False,
                "reason": "not_found",
                "threshold": threshold,
            }

        evaluation = (
            conn.execute(
                text(
                    "SELECT overall_score FROM evaluations "
                    "WHERE run_id = :rid ORDER BY created_at DESC LIMIT 1"
                ),
                {"rid": run_id},
            )
            .mappings()
            .fetchone()
        )

        alert_rows = (
            conn.execute(
                text("SELECT type FROM alerts WHERE run_id = :rid"),
                {"rid": run_id},
            )
            .mappings()
            .fetchall()
        )

    if evaluation is None or evaluation["overall_score"] is None:
        return {
            "eligible": False,
            "reason": "missing_evaluation",
            "threshold": threshold,
            "alert_count": len(alert_rows),
        }

    overall_score = float(evaluation["overall_score"])
    alert_types = [row["type"] for row in alert_rows]

    if overall_score >= threshold:
        return {
            "eligible": False,
            "reason": "score_not_low",
            "overall_score": overall_score,
            "threshold": threshold,
            "alert_count": len(alert_types),
        }

    if len(alert_types) == 1:
        return {
            "eligible": False,
            "reason": "single_alert_clear_cause",
            "overall_score": overall_score,
            "threshold": threshold,
            "alert_count": 1,
            "alert_types": alert_types,
        }

    if len(alert_types) == 0:
        return {
            "eligible": True,
            "reason": "low_score_no_alerts_unknown_cause",
            "overall_score": overall_score,
            "threshold": threshold,
            "alert_count": 0,
            "alert_types": alert_types,
        }

    return {
        "eligible": True,
        "reason": "low_score_with_multiple_alerts",
        "overall_score": overall_score,
        "threshold": threshold,
        "alert_count": len(alert_types),
        "alert_types": alert_types,
    }


def _normalise_chunks(retrieved_chunks: Any) -> list[dict[str, Any]]:
    """Return retrieved_chunks as a list of dicts for judge prompts."""
    if retrieved_chunks is None:
        return []
    if isinstance(retrieved_chunks, list):
        return [
            chunk if isinstance(chunk, dict) else {"text": str(chunk)}
            for chunk in retrieved_chunks
        ]
    if isinstance(retrieved_chunks, dict):
        return [retrieved_chunks]
    return [{"text": str(retrieved_chunks)}]


def _load_rag_payload(run_id: str, engine: Engine) -> dict[str, Any] | None:
    """Load query, answer, and context for a run with retrieval rows."""
    with engine.connect() as conn:
        run_row = conn.execute(
            text("SELECT input, output FROM runs WHERE id = :rid"),
            {"rid": run_id},
        ).mappings().fetchone()

        if run_row is None:
            return None

        retrieval_rows = conn.execute(
            text(
                "SELECT query, retrieved_chunks FROM retrievals "
                "WHERE run_id = :rid ORDER BY id"
            ),
            {"rid": run_id},
        ).mappings().fetchall()

    if not retrieval_rows:
        return {
            "run_exists": True,
            "has_retrievals": False,
        }

    queries = [row["query"] for row in retrieval_rows if row["query"]]
    context: list[dict[str, Any]] = []
    for row in retrieval_rows:
        context.extend(_normalise_chunks(row["retrieved_chunks"]))

    return {
        "run_exists": True,
        "has_retrievals": True,
        "query": "\n".join(dict.fromkeys(queries)) or run_row["input"],
        "answer": run_row["output"] or "",
        "context": context,
    }


@celery_app.task(name="diagent.run_rag_evaluation")
def run_rag_evaluation(run_id: str) -> dict:
    """Evaluate RAG quality for a run that has retrieval rows."""
    engine = create_engine(_get_sync_database_url())
    try:
        payload = _load_rag_payload(run_id, engine)
        if payload is None:
            logger.warning("RAG evaluation skipped — run_id=%s not found", run_id)
            return {"run_id": run_id, "status": "not_found"}

        if not payload["has_retrievals"]:
            logger.info(
                "RAG evaluation skipped — run_id=%s has no retrievals", run_id
            )
            return {"run_id": run_id, "status": "skipped_no_retrievals"}

        judge = _build_judge()
        scores = judge.evaluate(
            payload["query"],
            payload["answer"],
            payload["context"],
        )

        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO evaluations "
                    "(id, run_id, faithfulness, answer_relevancy, "
                    "context_precision, overall_score, created_at) "
                    "VALUES "
                    "(:id, :run_id, :faithfulness, "
                    ":answer_relevancy, :context_precision, "
                    ":overall_score, now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "faithfulness": _score_decimal(scores["faithfulness"]),
                    "answer_relevancy": _score_decimal(scores["answer_relevancy"]),
                    "context_precision": _score_decimal(scores["context_precision"]),
                    "overall_score": _score_decimal(scores["overall_score"]),
                },
            )

        diagnosis_trigger = _diagnosis_trigger_state(run_id, engine)
        diagnosis_task_id = None
        if diagnosis_trigger["eligible"]:
            diagnosis_task = run_diagnosis.delay(run_id)
            diagnosis_task_id = diagnosis_task.id

        logger.info("RAG evaluation done — run_id=%s scores=%s", run_id, scores)
        return {
            "run_id": run_id,
            "status": "evaluated",
            "scores": scores,
            "diagnosis_trigger": diagnosis_trigger,
            "diagnosis_task_id": diagnosis_task_id,
        }
    finally:
        engine.dispose()


@celery_app.task(name="diagent.run_diagnosis")
def run_diagnosis(run_id: str) -> dict:
    """Run the diagnostician and persist its JSON result when eligible."""
    from diagent.core.diagnostician import diagnose_run

    engine = create_engine(_get_sync_database_url())
    try:
        trigger = _diagnosis_trigger_state(run_id, engine)
        if not trigger["eligible"]:
            logger.info(
                "Diagnosis skipped — run_id=%s reason=%s",
                run_id,
                trigger["reason"],
            )
            return {"run_id": run_id, "status": "skipped", "trigger": trigger}

        diagnosis = diagnose_run(run_id, engine, _build_judge())

        statement = text(
            "INSERT INTO diagnoses "
            "(id, run_id, root_cause, confidence, evidence, "
            "recommendation, created_at) "
            "VALUES "
            "(:id, :run_id, :root_cause, :confidence, :evidence, "
            ":recommendation, now())"
        ).bindparams(bindparam("evidence", type_=JSONB))

        with engine.begin() as conn:
            conn.execute(
                statement,
                {
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "root_cause": diagnosis["root_cause"],
                    "confidence": _score_decimal(diagnosis["confidence"]),
                    "evidence": diagnosis["evidence"],
                    "recommendation": diagnosis["recommendation"],
                },
            )

        logger.info(
            "Diagnosis done — run_id=%s root_cause=%s confidence=%s",
            run_id,
            diagnosis["root_cause"],
            diagnosis["confidence"],
        )
        return {
            "run_id": run_id,
            "status": "diagnosed",
            "trigger": trigger,
            "diagnosis": diagnosis,
        }
    finally:
        engine.dispose()
