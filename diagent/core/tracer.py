"""Diagent Tracer SDK.

Provides the ``@observe`` decorator and helper functions to record
runs, spans, tool calls, and retrievals via the Diagent REST API.

This module lives in ``core/`` and has **zero** database or ORM imports.
All communication goes through HTTP so that any Python process — not just
the API server — can emit telemetry.

Usage::

    from diagent.core.tracer import observe, log_tool_call, log_retrieval

    @observe(agent_name="my-bot")
    def handle(question: str) -> str:
        log_retrieval(query=question, chunks=[...], top_k=3)
        log_tool_call(tool_name="calc", args={"expr": "2+2"}, status="success")
        return "The answer is 4"
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)

# ── Context ────────────────────────────────────────────

_current_run_id: ContextVar[str | None] = ContextVar("_current_run_id", default=None)
_current_tracer: ContextVar["DiagentTracer | None"] = ContextVar("_current_tracer", default=None)
_run_metadata_store: ContextVar[dict | None] = ContextVar("_run_metadata_store", default=None)


def get_current_run_id() -> str | None:
    """Return the active run ID set by ``@observe``, or *None*."""
    return _current_run_id.get()


def set_run_metadata(
    *,
    total_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    """Accumulate token/cost metadata within an ``@observe``-decorated function.

    Each call **adds** to the current totals (does not replace).
    """
    store = _run_metadata_store.get()
    if store is None:
        raise RuntimeError(
            "No active run. Call within an @observe-decorated function."
        )
    if total_tokens is not None:
        store["total_tokens"] = store.get("total_tokens", 0) + total_tokens
    if cost_usd is not None:
        store["cost_usd"] = (store.get("cost_usd") or 0.0) + cost_usd


# ── Tracer client ──────────────────────────────────────


class DiagentTracer:
    """Thin HTTP client that speaks to the Diagent REST API."""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or os.getenv("DIAGENT_API_URL", "http://localhost:8000")).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # ── helpers ────────────────────────────────────────

    def _post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _utcnow_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── public API ─────────────────────────────────────

    def create_run(self, agent_name: str, input_text: str = "") -> str:
        """POST /runs → returns run_id as string."""
        data = self._post("/runs", json={"agent_name": agent_name, "input": input_text})
        run_id: str = data["id"]
        logger.debug("created run %s for agent=%s", run_id, agent_name)
        return run_id

    def log_span(
        self,
        run_id: str,
        *,
        span_type: str,
        name: str,
        started_at: str | None = None,
        ended_at: str | None = None,
        duration_ms: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        """POST /runs/{run_id}/spans → returns span_id."""
        now = self._utcnow_iso()
        body: dict[str, Any] = {
            "type": span_type,
            "name": name,
            "started_at": started_at or now,
        }
        if ended_at is not None:
            body["ended_at"] = ended_at
        if duration_ms is not None:
            body["duration_ms"] = duration_ms
        if payload is not None:
            body["payload"] = payload
        data = self._post(f"/runs/{run_id}/spans", json=body)
        return data["id"]

    def log_tool_call(
        self,
        run_id: str,
        *,
        tool_name: str,
        args: dict[str, Any] | None = None,
        status: str = "success",
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> str:
        """POST /runs/{run_id}/tool_calls → creates tool_call + companion span."""
        body: dict[str, Any] = {
            "tool_name": tool_name,
            "status": status,
        }
        if args is not None:
            body["args"] = args
        if error is not None:
            body["error"] = error
        if duration_ms is not None:
            body["duration_ms"] = duration_ms
        data = self._post(f"/runs/{run_id}/tool_calls", json=body)
        logger.debug("logged tool_call %s on run %s", data["id"], run_id)
        return data["id"]

    def log_retrieval(
        self,
        run_id: str,
        *,
        query: str,
        retrieved_chunks: list[dict[str, Any]] | None = None,
        top_k: int = 5,
        source_age_hours: float | None = None,
    ) -> str:
        """POST /runs/{run_id}/retrievals → creates retrieval + companion span."""
        body: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
        }
        if retrieved_chunks is not None:
            body["retrieved_chunks"] = retrieved_chunks
        if source_age_hours is not None:
            body["source_age_hours"] = source_age_hours
        data = self._post(f"/runs/{run_id}/retrievals", json=body)
        logger.debug("logged retrieval %s on run %s", data["id"], run_id)
        return data["id"]

    def finish_run(
        self,
        run_id: str,
        *,
        output: str | None = None,
        status: str | None = None,
        error: str | None = None,
        total_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> dict[str, Any]:
        """POST /runs/{run_id}/finish."""
        body: dict[str, Any] = {}
        if output is not None:
            body["output"] = output
        if status is not None:
            body["status"] = status
        if error is not None:
            body["error"] = error
        if total_tokens is not None:
            body["total_tokens"] = total_tokens
        if cost_usd is not None:
            body["cost_usd"] = cost_usd
        data = self._post(f"/runs/{run_id}/finish", json=body or None)
        logger.debug("finished run %s", run_id)
        return data

    def close(self) -> None:
        self._client.close()


# ── Module-level singleton ─────────────────────────────

_default_tracer: DiagentTracer | None = None


def _get_tracer() -> DiagentTracer:
    """Return the context-local tracer or a module-level default."""
    t = _current_tracer.get()
    if t is not None:
        return t
    global _default_tracer
    if _default_tracer is None:
        _default_tracer = DiagentTracer()
    return _default_tracer


# ── Convenience functions (use current context) ────────


def log_tool_call(
    *,
    tool_name: str,
    args: dict[str, Any] | None = None,
    status: str = "success",
    error: str | None = None,
    duration_ms: int | None = None,
    run_id: str | None = None,
) -> str:
    """Log a tool call on the current (or explicit) run."""
    rid = run_id or get_current_run_id()
    if rid is None:
        raise RuntimeError("No active run. Use @observe or pass run_id explicitly.")
    return _get_tracer().log_tool_call(
        rid, tool_name=tool_name, args=args, status=status, error=error, duration_ms=duration_ms,
    )


def log_retrieval(
    *,
    query: str,
    retrieved_chunks: list[dict[str, Any]] | None = None,
    top_k: int = 5,
    source_age_hours: float | None = None,
    run_id: str | None = None,
) -> str:
    """Log a retrieval on the current (or explicit) run."""
    rid = run_id or get_current_run_id()
    if rid is None:
        raise RuntimeError("No active run. Use @observe or pass run_id explicitly.")
    return _get_tracer().log_retrieval(
        rid, query=query, retrieved_chunks=retrieved_chunks, top_k=top_k, source_age_hours=source_age_hours,
    )


def log_span(
    *,
    span_type: str,
    name: str,
    started_at: str | None = None,
    ended_at: str | None = None,
    duration_ms: int | None = None,
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> str:
    """Log an arbitrary span on the current (or explicit) run."""
    rid = run_id or get_current_run_id()
    if rid is None:
        raise RuntimeError("No active run. Use @observe or pass run_id explicitly.")
    return _get_tracer().log_span(
        rid, span_type=span_type, name=name, started_at=started_at,
        ended_at=ended_at, duration_ms=duration_ms, payload=payload,
    )


# ── @observe decorator ────────────────────────────────


def observe(agent_name: str = "default", *, tracer: DiagentTracer | None = None):
    """Decorator that wraps a function with full Diagent run lifecycle.

    Handles both synchronous and asynchronous functions automatically.

    1. Creates a run (``POST /runs``)
    2. Sets ``_current_run_id`` context var so inner helpers work
    3. Calls/awaits the decorated function
    4. Finishes the run (``POST /runs/{id}/finish``)

    The decorated function receives an injected ``run_id`` kwarg if it
    accepts one, otherwise the context var is the only way to access it.
    """

    def decorator(fn: Callable) -> Callable:
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                t = tracer or _get_tracer()
                token_tracer = _current_tracer.set(t)

                # Serialize input
                input_text = ""
                if args:
                    input_text = str(args[0]) if len(args) == 1 else str(args)
                elif kwargs:
                    input_text = str(kwargs)

                run_id = t.create_run(agent_name, input_text)
                token_run = _current_run_id.set(run_id)

                meta_store: dict = {}
                token_meta = _run_metadata_store.set(meta_store)

                output = None
                error_text = None
                try:
                    result = await fn(*args, **kwargs)
                    output = str(result) if result is not None else None
                    return result
                except Exception as exc:
                    error_text = f"{type(exc).__name__}: {exc}"
                    raise
                finally:
                    # Collect accumulated metadata from context
                    t.finish_run(
                        run_id,
                        output=output if error_text is None else None,
                        status="failed" if error_text is not None else "finished",
                        error=error_text,
                        total_tokens=meta_store.get("total_tokens") or None,
                        cost_usd=meta_store.get("cost_usd") or None,
                    )
                    _run_metadata_store.reset(token_meta)
                    _current_run_id.reset(token_run)
                    _current_tracer.reset(token_tracer)

            return async_wrapper
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                t = tracer or _get_tracer()
                token_tracer = _current_tracer.set(t)

                # Serialize input
                input_text = ""
                if args:
                    input_text = str(args[0]) if len(args) == 1 else str(args)
                elif kwargs:
                    input_text = str(kwargs)

                run_id = t.create_run(agent_name, input_text)
                token_run = _current_run_id.set(run_id)

                meta_store: dict = {}
                token_meta = _run_metadata_store.set(meta_store)

                output = None
                error_text = None
                try:
                    result = fn(*args, **kwargs)
                    output = str(result) if result is not None else None
                    return result
                except Exception as exc:
                    error_text = f"{type(exc).__name__}: {exc}"
                    raise
                finally:
                    # Collect accumulated metadata from context
                    t.finish_run(
                        run_id,
                        output=output if error_text is None else None,
                        status="failed" if error_text is not None else "finished",
                        error=error_text,
                        total_tokens=meta_store.get("total_tokens") or None,
                        cost_usd=meta_store.get("cost_usd") or None,
                    )
                    _run_metadata_store.reset(token_meta)
                    _current_run_id.reset(token_run)
                    _current_tracer.reset(token_tracer)

            return sync_wrapper

    return decorator


aobserve = observe

