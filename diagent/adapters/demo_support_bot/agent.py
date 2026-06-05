"""Demo support bot — mock customer support agent.

Simulates a simple agent pipeline::

    retrieve_documents → call_llm → maybe_call_tool → final_answer

No real LLM calls; all responses are mocked with realistic timings.
"""

from __future__ import annotations

import random
import time
from typing import Any

from diagent.core.tracer import log_retrieval, log_span, log_tool_call, observe, set_run_metadata

# ── Mock data ──────────────────────────────────────────

_MOCK_CHUNKS = [
    {"text": "İade işlemleri 14 gün içinde yapılabilir.", "score": 0.95, "source": "faq.md"},
    {"text": "Kargo takip numaranız sipariş detayında yer alır.", "score": 0.88, "source": "shipping.md"},
    {"text": "Ödeme yöntemleri: kredi kartı, havale, kapıda ödeme.", "score": 0.82, "source": "payments.md"},
]

_MOCK_ANSWERS = {
    "default": "Merhaba! Size nasıl yardımcı olabilirim?",
    "iade": "İade işleminiz 14 gün içinde ücretsiz olarak yapılabilir. Detaylı bilgi için sipariş sayfanızı kontrol edin.",
    "kargo": "Kargonuz yola çıkmıştır. Takip numaranız: TR123456789. Tahmini teslimat 2-3 iş günüdür.",
    "ödeme": "Kredi kartı, banka havalesi ve kapıda ödeme seçeneklerimiz mevcuttur.",
}


def _mock_sleep(min_ms: int = 50, max_ms: int = 200) -> int:
    """Simulate realistic latency, return elapsed ms."""
    ms = random.randint(min_ms, max_ms)
    time.sleep(ms / 1000)
    return ms


# ── Agent steps ────────────────────────────────────────


def retrieve_documents(question: str, *, source_age_hours: float | None = None) -> list[dict[str, Any]]:
    """Mock RAG retrieval step."""
    ms = _mock_sleep(80, 150)
    chunks = random.sample(_MOCK_CHUNKS, k=min(len(_MOCK_CHUNKS), 3))
    log_retrieval(
        query=question,
        retrieved_chunks=chunks,
        top_k=3,
        source_age_hours=source_age_hours or round(random.uniform(1, 48), 1),
    )
    return chunks


def call_llm(question: str, context_chunks: list[dict[str, Any]]) -> str:
    """Mock LLM call step."""
    ms = _mock_sleep(100, 300)
    # Pick answer based on keywords
    answer = _MOCK_ANSWERS["default"]
    for key in ("iade", "kargo", "ödeme"):
        if key in question.lower():
            answer = _MOCK_ANSWERS[key]
            break

    prompt_tokens = random.randint(200, 500)
    completion_tokens = random.randint(50, 150)
    set_run_metadata(
        total_tokens=prompt_tokens + completion_tokens,
        cost_usd=round((prompt_tokens + completion_tokens) * 0.00000015, 8),
    )

    log_span(
        span_type="llm_call",
        name="call_openai",
        duration_ms=ms,
        payload={
            "model": "gpt-4o-mini",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "temperature": 0.7,
            "finish_reason": "stop",
        },
    )
    return answer


def call_tool(
    tool_name: str = "order_lookup",
    args: dict[str, Any] | None = None,
    *,
    force_status: str | None = None,
    force_error: str | None = None,
) -> dict[str, Any]:
    """Mock tool call step."""
    ms = _mock_sleep(30, 100)
    status = force_status or "success"
    error = force_error if status == "error" else None

    log_tool_call(
        tool_name=tool_name,
        args=args or {"order_id": f"ORD-{random.randint(1000, 9999)}"},
        status=status,
        error=error,
        duration_ms=ms,
    )
    if status == "error":
        return {"error": error or "Tool failed"}
    return {"result": "Sipariş bulundu", "status": "delivered"}


# ── Main agent function ───────────────────────────────


@observe(agent_name="demo-support-bot")
def run_support_bot(
    question: str,
    *,
    tool_calls: int = 1,
    tool_error_count: int = 0,
    tool_name: str = "order_lookup",
    source_age_hours: float | None = None,
) -> str:
    """Run the full support bot pipeline.

    Args:
        question: Customer question.
        tool_calls: How many tool calls to make (for loop simulation).
        tool_error_count: How many tool calls should fail.
        tool_name: Name of the tool to call.
        source_age_hours: Override for retrieval source age.
    """
    # Step 1: Retrieve documents
    chunks = retrieve_documents(question, source_age_hours=source_age_hours)

    # Step 2: Call LLM
    answer = call_llm(question, chunks)

    # Step 3: Tool calls (variable count for loop/error scenarios)
    for i in range(tool_calls):
        should_fail = i < tool_error_count
        call_tool(
            tool_name=tool_name,
            args={"order_id": f"ORD-{random.randint(1000, 9999)}", "attempt": i + 1},
            force_status="error" if should_fail else "success",
            force_error=f"Timeout after 5000ms (attempt {i + 1})" if should_fail else None,
        )

    # Step 4: Final answer
    return answer
