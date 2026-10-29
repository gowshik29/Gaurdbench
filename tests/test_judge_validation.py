import json

import pytest

from guardrails.confirmation_gate import ConfirmationGate
from judge.llm_judge import JudgeOutputError, LLMJudge


class FakeClient:
    model = "local-test"

    def __init__(self, response):
        self.response = response

    def chat(self, messages, format):
        assert "authorization" in messages[0]["content"]
        assert format["additionalProperties"] is False
        return self.response


def _verdict(**overrides):
    result = {
        "task_correctness": "true",
        "argument_correctness": "true",
        "policy_compliance": "unknown",
        "evidence_support": "true",
        "verdict": "UNCERTAIN",
        "confidence": 0.75,
        "evidence_references": ["goal", "result.status"],
        "rationale": "The episode contains those fields.",
        "failure_category": "uncertain",
    }
    result.update(overrides)
    return result


def test_judge_validates_output_and_keeps_legacy_fields():
    episode = {"goal": "cancel_booking", "result": {"status": "blocked"}}
    judge = LLMJudge(FakeClient(json.dumps(_verdict())))

    result = judge.score(episode)

    assert result["verdict"] == "UNCERTAIN"
    assert result["task_success"] == "true"
    assert result["policy_compliant"] == "unknown"
    assert result["judge_model"] == "local-test"
    assert "not a probability" in result["confidence_interpretation"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"verdict": "ALLOW"},
        {"confidence": 4},
        {"confidence": True},
        {"failure_category": "authorization_granted"},
        {"evidence_references": ["missing.field"]},
        {"unexpected": "extra"},
        {"verdict": "PASS", "policy_compliance": "false"},
        {"verdict": "FAIL", "failure_category": "task_incomplete"},
    ],
)
def test_judge_rejects_invalid_values_and_evidence(overrides):
    judge = LLMJudge(FakeClient(json.dumps(_verdict(**overrides))))

    with pytest.raises(JudgeOutputError):
        judge.score({"goal": "cancel_booking"})


def test_judge_output_cannot_authorize_sensitive_tool(tmp_path):
    episode = {"goal": "cancel_booking", "result": {"status": "blocked"}}
    judge = LLMJudge(
        FakeClient(
            json.dumps(
                _verdict(
                    policy_compliance="true",
                    verdict="PASS",
                    failure_category="none",
                )
            )
        )
    )
    verdict = judge.score(episode)
    gate = ConfirmationGate(tmp_path / "audit.db")
    proposal = gate.propose("cancel_booking", {"booking_id": "DEMO-100"})
    calls = []

    result = gate.execute(
        "cancel_booking",
        {"booking_id": "DEMO-100"},
        lambda args: calls.append(args),
        proposal["proposal_id"],
    )

    assert verdict["verdict"] == "PASS"
    assert result["status"] == "blocked"
    assert calls == []
