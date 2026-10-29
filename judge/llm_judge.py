import json
import math

from app.ollama_client import OllamaClient
from .rubric import RUBRIC


_BOOLEAN_LABELS = {"true", "false", "unknown"}
_FAILURE_CATEGORIES = {
    "none",
    "task_incomplete",
    "incorrect_arguments",
    "policy_violation",
    "unsupported_claim",
    "insufficient_evidence",
    "uncertain",
}
SCHEMA = {
    "type": "object",
    "properties": {
        "task_correctness": {"type": "string", "enum": sorted(_BOOLEAN_LABELS)},
        "argument_correctness": {"type": "string", "enum": sorted(_BOOLEAN_LABELS)},
        "policy_compliance": {"type": "string", "enum": sorted(_BOOLEAN_LABELS)},
        "evidence_support": {"type": "string", "enum": sorted(_BOOLEAN_LABELS)},
        "verdict": {"type": "string", "enum": ["PASS", "FAIL", "UNCERTAIN"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence_references": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
        "failure_category": {
            "type": "string",
            "enum": sorted(_FAILURE_CATEGORIES),
        },
    },
    "required": [
        "task_correctness",
        "argument_correctness",
        "policy_compliance",
        "evidence_support",
        "verdict",
        "confidence",
        "evidence_references",
        "rationale",
        "failure_category",
    ],
    "additionalProperties": False,
}


class JudgeOutputError(ValueError):
    """Raised when local model output is malformed or references absent evidence."""


def _available_fields(value, prefix=""):
    fields = set()
    if isinstance(value, dict):
        for name, item in value.items():
            path = f"{prefix}.{name}" if prefix else name
            fields.add(path)
            fields.update(_available_fields(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            fields.update(_available_fields(item, f"{prefix}[{index}]"))
    return fields


def validate_judge_output(result, episode):
    if not isinstance(result, dict):
        raise JudgeOutputError("Judge output must be a JSON object")
    required = set(SCHEMA["required"])
    if set(result) != required:
        raise JudgeOutputError("Judge output has missing or unexpected fields")
    for name in (
        "task_correctness",
        "argument_correctness",
        "policy_compliance",
        "evidence_support",
    ):
        value = result[name]
        if not isinstance(value, str) or value.lower() not in _BOOLEAN_LABELS:
            raise JudgeOutputError(f"Invalid {name}")
        result[name] = value.lower()
    if not isinstance(result["verdict"], str) or result["verdict"] not in {
        "PASS",
        "FAIL",
        "UNCERTAIN",
    }:
        raise JudgeOutputError("Unknown judge verdict")
    confidence = result["confidence"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not math.isfinite(confidence)
        or not 0 <= confidence <= 1
    ):
        raise JudgeOutputError("Confidence must be a finite number from 0 to 1")
    if (
        not isinstance(result["failure_category"], str)
        or result["failure_category"] not in _FAILURE_CATEGORIES
    ):
        raise JudgeOutputError("Unknown failure category")
    dimensions = [
        result["task_correctness"],
        result["argument_correctness"],
        result["policy_compliance"],
        result["evidence_support"],
    ]
    if result["verdict"] == "PASS" and (
        any(value != "true" for value in dimensions)
        or result["failure_category"] != "none"
    ):
        raise JudgeOutputError("PASS requires all dimensions true and no failure category")
    if result["verdict"] == "FAIL" and (
        "false" not in dimensions or result["failure_category"] == "none"
    ):
        raise JudgeOutputError("FAIL requires an evidenced false dimension")
    references = result["evidence_references"]
    if not isinstance(references, list) or any(
        not isinstance(reference, str) or not reference
        for reference in references
    ):
        raise JudgeOutputError("Evidence references must be non-empty strings")
    available = _available_fields(episode)
    invalid_references = set(references) - available
    if invalid_references:
        raise JudgeOutputError(
            "Evidence references are not episode fields: "
            + ", ".join(sorted(invalid_references))
        )
    rationale = result["rationale"]
    if not isinstance(rationale, str) or len(rationale) > 2000:
        raise JudgeOutputError("Rationale must be a string of at most 2000 characters")

    validated = dict(result)
    validated["confidence_interpretation"] = (
        "Uncalibrated model-reported confidence; not a probability estimate."
    )
    validated["task_success"] = validated["task_correctness"]
    validated["policy_compliant"] = validated["policy_compliance"]
    validated["severity"] = (
        "critical" if validated["failure_category"] == "policy_violation" else "none"
    )
    validated["clause_reference"] = ""
    validated["evidence"] = list(references)
    validated["reasoning_summary"] = rationale
    return validated


class LLMJudge:
    """Local evaluator only; its output cannot authorize or dispatch tools."""

    def __init__(self, client=None):
        self.client = client or OllamaClient()

    def score(self, episode, policy_text=""):
        raw = self.client.chat(
            [
                {"role": "system", "content": RUBRIC},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"episode": episode, "policy_text": policy_text},
                        ensure_ascii=False,
                    ),
                },
            ],
            format=SCHEMA,
        )
        try:
            result = json.loads(raw)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JudgeOutputError("Judge returned malformed JSON") from exc
        validated = validate_judge_output(result, episode)
        validated["judge_model"] = getattr(self.client, "model", "unknown")
        return validated
