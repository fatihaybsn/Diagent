"""Diagent Tracer SDK.

Provides the ``@observe`` decorator and helper functions to record
runs and spans via the Diagent REST API.
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
    store = _run_metadata_store.get()
    if store is None:
        raise RuntimeError(
            "No active run. Call within an @observe-decorated function."
        )
    if total_tokens is not None:
        store["total_tokens"] = store.get("total_tokens", 0) + total_tokens
    if cost_usd is not None:
        store["cost_usd"] = (store.get("cost_usd") or 0.0) + cost_usd


class DiagentTracer:
    """Thin HTTP client that speaks to the Diagent REST API."""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or os.getenv("DIAGENT_API_URL", "http://localhost:8000")).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def _post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._client.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _utcnow_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_run(self, agent_name: str, input_text: str = "") -> str:
        data = self._post("/runs", json={"agent_name": agent_name, "input": input_text})
        run_id: str = data["id"]
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

    def finish_run(
        self,
        run_id: str,
        *,
        output: str | None = None,
        total_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if output is not None:
            body["output"] = output
        if total_tokens is not None:
            body["total_tokens"] = total_tokens
        if cost_usd is not None:
            body["cost_usd"] = cost_usd
        return self._post(f"/runs/{run_id}/finish", json=body or None)

    def close(self) -> None:
        self._client.close()


_default_tracer: DiagentTracer | None = None


def _get_tracer() -> DiagentTracer:
    t = _current_tracer.get()
    if t is not None:
        return t
    global _default_tracer
    if _default_tracer is None:
        _default_tracer = DiagentTracer()
    return _default_tracer


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
    rid = run_id or get_current_run_id()
    if rid is None:
        raise RuntimeError("No active run. Use @observe or pass run_id explicitly.")
    return _get_tracer().log_span(
        rid, span_type=span_type, name=name, started_at=started_at,
        ended_at=ended_at, duration_ms=duration_ms, payload=payload,
    )


def observe(agent_name: str = "default", *, tracer: DiagentTracer | None = None):
    def decorator(fn: Callable) -> Callable:
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                t = tracer or _get_tracer()
                token_tracer = _current_tracer.set(t)

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
                try:
                    result = await fn(*args, **kwargs)
                    output = str(result) if result is not None else None
                    return result
                except Exception:
                    output = "[ERROR]"
                    raise
                finally:
                    t.finish_run(
                        run_id,
                        output=output,
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
                try:
                    result = fn(*args, **kwargs)
                    output = str(result) if result is not None else None
                    return result
                except Exception:
                    output = "[ERROR]"
                    raise
                finally:
                    t.finish_run(
                        run_id,
                        output=output,
                        total_tokens=meta_store.get("total_tokens") or None,
                        cost_usd=meta_store.get("cost_usd") or None,
                    )
                    _run_metadata_store.reset(token_meta)
                    _current_run_id.reset(token_run)
                    _current_tracer.reset(token_tracer)

            return sync_wrapper

    return decorator


aobserve = observe
