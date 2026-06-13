"""Rule-based anomaly detectors for agent runs.

Each detector receives a *run_id* and a sync SQLAlchemy **Engine**.
If an anomaly is detected, a row is inserted into the ``alerts`` table.

All thresholds are read from environment variables at call time so that
tests can override them via ``monkeypatch.setenv``.
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


# ── Helpers ────────────────────────────────────────────────────────


def _threshold(env_key: str, settings_value: float) -> float:
    """Read a numeric threshold from the environment, falling back to settings."""
    raw = os.environ.get(env_key)
    return float(raw) if raw is not None else float(settings_value)


def _threshold_int(env_key: str, settings_value: int) -> int:
    """Read an integer threshold from the environment, falling back to settings."""
    raw = os.environ.get(env_key)
    return int(raw) if raw is not None else int(settings_value)


def _insert_alert(
    engine: Engine,
    run_id: str,
    alert_type: str,
    severity: str,
    message: str,
) -> None:
    """Insert a row into the alerts table."""
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


# ── Detectors ──────────────────────────────────────────────────────


def detect_tool_loop(run_id: str, engine: Engine) -> bool:
    """Detect when the same tool is called N or more times in a single run.

    Threshold env: ``TOOL_LOOP_THRESHOLD`` (default 3).
    """
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
    """Detect when the error rate of tool calls exceeds a threshold.

    Threshold env: ``TOOL_FAILURE_RATE`` (default 0.5 = 50%).
    """
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
    """Detect when a run's cost exceeds the agent's average by a multiplier.

    Threshold env: ``COST_SPIKE_MULTIPLIER`` (default 5.0).
    """
    multiplier = _threshold("COST_SPIKE_MULTIPLIER", settings.cost_spike_multiplier)

    with engine.connect() as conn:
        # Get this run's cost and agent_id
        run_row = conn.execute(
            text("SELECT cost_usd, agent_id FROM runs WHERE id = :rid"),
            {"rid": run_id},
        ).fetchone()

    if run_row is None or run_row[0] is None:
        return False

    cost_usd = float(run_row[0])
    agent_id = str(run_row[1])

    with engine.connect() as conn:
        # Calculate baseline: average cost of OTHER finished runs for this agent
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


def detect_latency_spike(run_id: str, engine: Engine) -> bool:
    """Detect when a run's duration exceeds the latency threshold.

    Threshold env: ``LATENCY_SPIKE_MS`` (default 30000).
    """
    threshold_ms = _threshold_int("LATENCY_SPIKE_MS", settings.latency_spike_ms)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT duration_ms FROM runs WHERE id = :rid"),
            {"rid": run_id},
        ).fetchone()

    if row is None or row[0] is None:
        return False

    duration_ms = row[0]

    if duration_ms > threshold_ms:
        _insert_alert(
            engine,
            run_id,
            alert_type="latency_spike",
            severity="warning",
            message=(
                f"Duration {duration_ms}ms exceeds threshold {threshold_ms}ms"
            ),
        )
        return True

    return False


def detect_stale_data(run_id: str, engine: Engine) -> bool:
    """Detect when any retrieval's source age exceeds the staleness threshold.

    Threshold env: ``STALE_DATA_HOURS`` (default 72.0).
    """
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


def detect_empty_retrieval(run_id: str, engine: Engine) -> bool:
    """Detect when a retrieval returns empty or null chunks.

    No threshold env — triggers whenever retrieved_chunks is empty or null.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT retrieved_chunks FROM retrievals WHERE run_id = :rid"
            ),
            {"rid": run_id},
        ).fetchall()

    if not rows:
        return False

    for row in rows:
        chunks = row[0]
        if chunks is None or chunks == []:
            _insert_alert(
                engine,
                run_id,
                alert_type="empty_retrieval",
                severity="warning",
                message="Retrieval returned empty or null chunks",
            )
            return True

    return False


# ── Orchestrator ───────────────────────────────────────────────────


def run_all_detectors(run_id: str, engine: Engine) -> dict[str, bool]:
    """Run all anomaly detectors for a given run.

    Returns a dict mapping detector name → whether it triggered.
    """
    results = {
        "tool_loop": detect_tool_loop(run_id, engine),
        "tool_failure": detect_tool_failure(run_id, engine),
        "cost_spike": detect_cost_spike(run_id, engine),
        "latency_spike": detect_latency_spike(run_id, engine),
        "stale_data": detect_stale_data(run_id, engine),
        "empty_retrieval": detect_empty_retrieval(run_id, engine),
    }

    triggered = [k for k, v in results.items() if v]
    if triggered:
        logger.info(
            "Detectors triggered for run %s: %s", run_id, ", ".join(triggered)
        )
    else:
        logger.info("No anomalies detected for run %s", run_id)

    return results
