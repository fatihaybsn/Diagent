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


def detect_cost_spike(run_id: str, engine: Engine) -> bool:
    multiplier = _threshold("COST_SPIKE_MULTIPLIER", settings.cost_spike_multiplier)

    with engine.connect() as conn:
        run_row = conn.execute(
            text("SELECT cost_usd, agent_id FROM runs WHERE id = :rid"),
            {"rid": run_id},
        ).fetchone()

    if run_row is None or run_row[0] is None:
        return False

    cost_usd = float(run_row[0])
    agent_id = str(run_row[1])

    with engine.connect() as conn:
        avg_row = conn.execute(
            text(
                "SELECT AVG(cost_usd) FROM runs "
                "WHERE agent_id = :aid AND id != :rid "
                "AND cost_usd IS NOT NULL AND status = 'finished'"
            ),
            {"aid": agent_id, "rid": run_id},
        ).fetchone()

    if avg_row is None or avg_row[0] is None:
        return False

    baseline = float(avg_row[0])
    if baseline <= 0:
        return False

    if cost_usd > baseline * multiplier:
        _insert_alert(
            engine,
            run_id,
            alert_type="cost_spike",
            severity="warning",
            message=(
                f"Cost ${cost_usd:.4f} exceeds baseline "
                f"${baseline:.4f} × {multiplier} = ${baseline * multiplier:.4f}"
            ),
        )
        return True

    return False


def detect_stale_data(run_id: str, engine: Engine) -> bool:
    threshold_hours = _threshold("STALE_DATA_HOURS", settings.stale_data_hours)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT source_age_hours FROM retrievals "
                "WHERE run_id = :rid AND source_age_hours IS NOT NULL"
            ),
            {"rid": run_id},
        ).fetchall()

    if not rows:
        return False

    max_age = max(float(row[0]) for row in rows)

    if max_age > threshold_hours:
        _insert_alert(
            engine,
            run_id,
            alert_type="stale_data",
            severity="warning",
            message=(
                f"Source age {max_age:.1f}h exceeds threshold {threshold_hours:.1f}h"
            ),
        )
        return True

    return False


def run_all_detectors(run_id: str, engine: Engine) -> dict[str, bool]:
    results = {
        "tool_loop": detect_tool_loop(run_id, engine),
        "tool_failure": detect_tool_failure(run_id, engine),
        "cost_spike": detect_cost_spike(run_id, engine),
        "stale_data": detect_stale_data(run_id, engine),
    }
    return results
