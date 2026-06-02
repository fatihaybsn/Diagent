"""Tests for the observe and aobserve decorators."""

import pytest
from diagent.core.tracer import observe, aobserve, get_current_run_id, set_run_metadata


class FakeTracer:
    def __init__(self):
        self.runs = []
        self.finished = {}

    def create_run(self, agent_name: str, input_text: str = "") -> str:
        run_id = f"run-id-{agent_name}"
        self.runs.append({
            "id": run_id,
            "agent_name": agent_name,
            "input": input_text,
        })
        return run_id

    def finish_run(
        self,
        run_id: str,
        output: str | None = None,
        total_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> dict:
        self.finished[run_id] = {
            "output": output,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
        }
        return {"status": "ok"}


def test_sync_observe_decorator() -> None:
    """Sync functions decorated with @observe should trace successfully."""
    tracer = FakeTracer()

    @observe(agent_name="sync-test-agent", tracer=tracer)
    def my_sync_function(question: str) -> str:
        assert get_current_run_id() == "run-id-sync-test-agent"
        set_run_metadata(total_tokens=100, cost_usd=0.002)
        return f"Processed: {question}"

    result = my_sync_function("What is the refund policy?")

    assert result == "Processed: What is the refund policy?"
    assert len(tracer.runs) == 1
    assert tracer.runs[0]["input"] == "What is the refund policy?"
    assert "run-id-sync-test-agent" in tracer.finished
    assert tracer.finished["run-id-sync-test-agent"]["output"] == "Processed: What is the refund policy?"
    assert tracer.finished["run-id-sync-test-agent"]["total_tokens"] == 100
    assert tracer.finished["run-id-sync-test-agent"]["cost_usd"] == 0.002


@pytest.mark.asyncio
async def test_async_observe_decorator() -> None:
    """Async functions decorated with @observe (or @aobserve) should trace and await successfully."""
    tracer = FakeTracer()

    @observe(agent_name="async-test-agent", tracer=tracer)
    async def my_async_function(question: str) -> str:
        assert get_current_run_id() == "run-id-async-test-agent"
        set_run_metadata(total_tokens=250, cost_usd=0.005)
        return f"Async processed: {question}"

    result = await my_async_function("Is shipping free?")

    assert result == "Async processed: Is shipping free?"
    assert len(tracer.runs) == 1
    assert tracer.runs[0]["input"] == "Is shipping free?"
    assert "run-id-async-test-agent" in tracer.finished
    assert tracer.finished["run-id-async-test-agent"]["output"] == "Async processed: Is shipping free?"
    assert tracer.finished["run-id-async-test-agent"]["total_tokens"] == 250
    assert tracer.finished["run-id-async-test-agent"]["cost_usd"] == 0.005
