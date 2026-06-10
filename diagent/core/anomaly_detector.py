"""Rule-based anomaly detectors for agent runs.

Each detector receives a *run_id* and a sync SQLAlchemy **Engine**.
If an anomaly is detected, a row is inserted into the ``alerts`` table.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine

from diagent.config import settings

logger = logging.getLogger(__name__)


def _threshold(env_key: str, settings_value: float) -> float:
    raw = os.environ.get(env_key)
    return float(raw) if raw is not None else float(settings_value)


def _threshold_int(env_key: str, settings_value: int) -> int:
    raw = os.environ.get(env_key)
    return int(raw) if raw is not None else int(settings_value)


def _insert_alert(
    engine: Engine,
    run_id: str,
    alert_type: str,
    severity: str,
    message: str,
) -> None:
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO alerts (id, run_id, type, severity, message, created_at) "
                "VALUES (:id, :run_id, :type, :severity, :message, :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "run_id": run_id,
                "type": alert_type,
                "severity": severity,
                "message": message,
                "created_at": datetime.now(timezone.utc),
            },
        )
        conn.commit()
    logger.info("Alert created: type=%s run_id=%s", alert_type, run_id)


def detect_tool_loop(run_id: str, engine: Engine) -> bool:
    threshold = _threshold_int("TOOL_LOOP_THRESHOLD", settings.tool_loop_threshold)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tool_name FROM tool_calls WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    if not rows:
        return False

    counts = Counter(row[0] for row in rows)
    most_common_name, most_common_count = counts.most_common(1)[0]

    if most_common_count >= threshold:
        _insert_alert(
            engine,
            run_id,
            alert_type="tool_loop",
            severity="warning",
            message=(
                f"Tool '{most_common_name}' called {most_common_count} times "
                f"(threshold: {threshold})"
            ),
        )
        return True

    return False


def detect_tool_failure(run_id: str, engine: Engine) -> bool:
    threshold = _threshold("TOOL_FAILURE_RATE", settings.tool_failure_rate)

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT status FROM tool_calls WHERE run_id = :rid"),
            {"rid": run_id},
        ).fetchall()

    if not rows:
        return False

    total = len(rows)
    errors = sum(1 for row in rows if row[0] == "error")
    rate = errors / total

    if rate >= threshold:
        _insert_alert(
            engine,
            run_id,
            alert_type="tool_failure",
            severity="critical",
            message=(
                f"Tool failure rate {rate:.0%} ({errors}/{total}) "
                f"exceeds threshold {threshold:.0%}"
            ),
        )
        return True

    return False


def run_all_detectors(run_id: str, engine: Engine) -> dict[str, bool]:
    results = {
        "tool_loop": detect_tool_loop(run_id, engine),
        "tool_failure": detect_tool_failure(run_id, engine),
    }
    return results
