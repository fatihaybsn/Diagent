"""Celery task definitions for Diagent."""

import logging
import os
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


@celery_app.task(name="diagent.echo_task")
def echo_task(run_id: str) -> dict:
    """Dummy task to verify Celery connection and DB visibility."""
    engine = create_engine(_get_sync_database_url())
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT status FROM runs WHERE id = :rid"),
                {"rid": run_id},
            ).fetchone()
        status = row[0] if row else "not_found"
        logger.info(
            "echo task — run_id=%s  status=%s  (DB connection OK)",
            run_id,
            status,
        )
        return {"run_id": run_id, "status": status}
    finally:
        engine.dispose()
