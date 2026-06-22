"""Tests for the read-only diagnostician agent."""

from __future__ import annotations

import pytest
from diagent.core.diagnostician import run_diagnostician_graph


class FakeDiagnosisLLM:

    def complete_json(self, prompt: str) -> str:
        return """
        {
          "root_cause": "weak_retrieval",
          "confidence": 0.82,
          "evidence": [
            "overall_score is below 0.6",
            "multiple alerts make the root cause ambiguous"
          ],
          "recommendation": "Review retrieval freshness and failed tool evidence before changing prompts."
        }
        """


def test_diagnostician_graph_logic() -> None:
    llm = FakeDiagnosisLLM()
    # Mock resources dictionary
    resources = {
        "run": {"id": "test-run", "input": "test"},
        "alerts": [{"type": "tool_loop"}],
        "evaluation": {"overall_score": 0.3},
        "retrievals": [],
    }
    result = run_diagnostician_graph("test-run", llm, resources=resources)
    assert result["root_cause"] == "weak_retrieval"
    assert result["confidence"] == 0.82
    assert "overall_score is below 0.6" in result["evidence"]
