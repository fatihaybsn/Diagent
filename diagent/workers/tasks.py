"""Celery task definitions for Diagent."""

import logging
import os
from sqlalchemy import create_engine
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
