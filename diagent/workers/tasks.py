"""Celery task definitions for Diagent."""

import logging
import os
import uuid
from decimal import Decimal
from typing import Any
from sqlalchemy import create_engine, text
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
    """Run all rule-based anomaly detectors for a finished run."""
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
    return float(os.getenv("JUDGE_RATE_LIMIT_SECONDS", "1"))


def _build_judge():
    from diagent.core.rag_quality import OllamaJudge, OpenAIJudge

    backend = os.getenv("DIAGENT_JUDGE_BACKEND", "openai").strip().lower()
    rate_limit_seconds = _judge_rate_limit_seconds()

    if backend == "openai":
        return OpenAIJudge(rate_limit_seconds=rate_limit_seconds)
    if backend == "ollama":
        return OllamaJudge(rate_limit_seconds=rate_limit_seconds)

    raise ValueError(f"Unsupported judge backend: {backend}")


def _score_decimal(value: float) -> Decimal:
    clamped = min(1.0, max(0.0, float(value)))
    return Decimal(str(round(clamped, 3)))


def _normalise_chunks(retrieved_chunks: Any) -> list[dict[str, Any]]:
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


def _load_rag_payload(run_id: str, engine) -> dict[str, Any] | None:
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
        "query": "
".join(dict.fromkeys(queries)) or run_row["input"],
        "answer": run_row["output"] or "",
        "context": context,
    }


@celery_app.task(name="diagent.run_rag_evaluation")
def run_rag_evaluation(run_id: str) -> dict:
    engine = create_engine(_get_sync_database_url())
    try:
        payload = _load_rag_payload(run_id, engine)
        if payload is None:
            return {"run_id": run_id, "status": "not_found"}

        if not payload["has_retrievals"]:
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

        logger.info("RAG evaluation done — run_id=%s scores=%s", run_id, scores)
        return {
            "run_id": run_id,
            "status": "evaluated",
            "scores": scores,
        }
    finally:
        engine.dispose()
