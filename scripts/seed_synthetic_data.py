"""Seed synthetic edge-case data for detector testing.

Creates 4 pathological runs directly via the Diagent REST API:
  1. Tool loop — same tool called 8 times
  2. Cost spike — cost_usd = 10x normal
  3. Stale data — source_age_hours = 96 (threshold = 72)
  4. Tool failure — all tool_calls status="error"

Usage::

    # From project root (API must be running)
    python -m scripts.seed_synthetic_data

    # Inside Docker
    docker compose exec api python -m scripts.seed_synthetic_data
"""

from __future__ import annotations

import logging
import os

import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = os.getenv("DIAGENT_API_URL", "http://localhost:8000")


def _post(client: httpx.Client, path: str, json: dict | None = None) -> dict:
    resp = client.post(path, json=json)
    resp.raise_for_status()
    return resp.json()


def seed_tool_loop(client: httpx.Client) -> None:
    """Edge case 1: Same tool called 8 times (tool_loop threshold=3)."""
    logger.info("Creating: tool_loop edge case (8 calls)")
    run = _post(client, "/runs", json={"agent_name": "synthetic-bot", "input": "tool loop test"})
    run_id = run["id"]

    for i in range(8):
        _post(client, f"/runs/{run_id}/tool_calls", json={
            "tool_name": "web_search",
            "args": {"query": f"search attempt {i + 1}"},
            "status": "success",
            "duration_ms": 120,
        })

    _post(client, f"/runs/{run_id}/finish", json={"output": "completed after 8 tool calls"})
    logger.info("  → run_id=%s (8x web_search)", run_id)


def seed_cost_spike(client: httpx.Client) -> None:
    """Edge case 2: cost_usd = 10x normal (~$0.50 vs ~$0.05)."""
    logger.info("Creating: cost_spike edge case (10x cost)")

    # First create a "normal" baseline run
    baseline = _post(client, "/runs", json={"agent_name": "synthetic-bot", "input": "baseline cost run"})
    _post(client, f"/runs/{baseline['id']}/finish", json={
        "output": "normal answer",
        "total_tokens": 500,
        "cost_usd": 0.005,
    })
    logger.info("  → baseline run_id=%s (cost=$0.005)", baseline["id"])

    # Now create the spike
    run = _post(client, "/runs", json={"agent_name": "synthetic-bot", "input": "cost spike test"})
    run_id = run["id"]

    _post(client, f"/runs/{run_id}/tool_calls", json={
        "tool_name": "expensive_api",
        "args": {"model": "gpt-4-turbo", "max_tokens": 8000},
        "status": "success",
        "duration_ms": 5000,
    })

    _post(client, f"/runs/{run_id}/finish", json={
        "output": "very expensive answer with lots of tokens",
        "total_tokens": 50000,
        "cost_usd": 0.50,
    })
    logger.info("  → spike run_id=%s (cost=$0.50, 100x baseline)", run_id)


def seed_stale_data(client: httpx.Client) -> None:
    """Edge case 3: source_age_hours=96 (threshold=72)."""
    logger.info("Creating: stale_data edge case (96h old source)")
    run = _post(client, "/runs", json={"agent_name": "synthetic-bot", "input": "stale data test"})
    run_id = run["id"]

    _post(client, f"/runs/{run_id}/retrievals", json={
        "query": "company refund policy 2024",
        "retrieved_chunks": [
            {"text": "Refund policy from 2022...", "score": 0.75, "source": "old_policy.md"},
            {"text": "Updated terms may apply...", "score": 0.60, "source": "archive.md"},
        ],
        "top_k": 5,
        "source_age_hours": 96.0,
    })

    _post(client, f"/runs/{run_id}/finish", json={
        "output": "Based on our 2022 policy, refunds are processed in 30 days.",
    })
    logger.info("  → run_id=%s (source_age=96h, threshold=72h)", run_id)


def seed_tool_failure(client: httpx.Client) -> None:
    """Edge case 4: All tool_calls have status='error'."""
    logger.info("Creating: tool_failure edge case (all errors)")
    run = _post(client, "/runs", json={"agent_name": "synthetic-bot", "input": "tool failure test"})
    run_id = run["id"]

    error_tools = [
        ("database_query", "ConnectionRefusedError: DB unreachable"),
        ("email_sender", "SMTPAuthenticationError: Invalid credentials"),
        ("payment_gateway", "TimeoutError: Gateway did not respond in 10s"),
    ]

    for tool_name, error_msg in error_tools:
        _post(client, f"/runs/{run_id}/tool_calls", json={
            "tool_name": tool_name,
            "args": {"action": "execute"},
            "status": "error",
            "error": error_msg,
            "duration_ms": 5000,
        })

    _post(client, f"/runs/{run_id}/finish", json={
        "output": "Üzgünüm, şu anda sistemlerimizde bir sorun yaşanıyor.",
    })
    logger.info("  → run_id=%s (3/3 tool calls failed)", run_id)


def main() -> None:
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # Verify API is reachable
        try:
            resp = client.get("/healthz")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("API unreachable at %s: %s", BASE_URL, exc)
            logger.error("Make sure the API is running (docker compose up)")
            return

        logger.info("API connected at %s\n", BASE_URL)

        seed_tool_loop(client)
        seed_cost_spike(client)
        seed_stale_data(client)
        seed_tool_failure(client)

        logger.info("\n✅ Synthetic seed tamamlandı — 5 run oluşturuldu (1 baseline + 4 edge case).")


if __name__ == "__main__":
    main()
