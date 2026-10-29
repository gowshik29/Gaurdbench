import pytest

from guardrails.action_policy import (
    ACTION_NAMES,
    DEFAULT_POLICY,
    ActionPolicy,
    ActionRule,
    RiskLevel,
)


def test_default_policy_versions_are_deterministic_and_cover_actions():
    assert set(DEFAULT_POLICY.rules) == ACTION_NAMES
    assert DEFAULT_POLICY.version == ActionPolicy().version
    assert DEFAULT_POLICY.rule_for("change_payment_method").risk_level is RiskLevel.CRITICAL
    assert ActionPolicy.from_mapping(DEFAULT_POLICY.to_mapping()).version == DEFAULT_POLICY.version


def test_policy_mapping_rejects_malformed_configuration():
    rules = DEFAULT_POLICY.to_mapping()
    rules["cancel_booking"]["extra"] = "not allowed"

    with pytest.raises(ValueError, match="Invalid policy rule"):
        ActionPolicy.from_mapping(rules)


def test_policy_rejects_missing_or_unknown_actions():
    with pytest.raises(ValueError, match="exactly match"):
        ActionPolicy({"get_booking": ActionRule(RiskLevel.LOW, False)})

    rules = dict(DEFAULT_POLICY.rules)
    rules["unknown"] = ActionRule(RiskLevel.LOW, False)
    with pytest.raises(ValueError, match="exactly match"):
        ActionPolicy(rules)


@pytest.mark.parametrize(
    "rule",
    [
        ("not-a-rule"),
        (ActionRule("high", True)),
        (ActionRule(RiskLevel.HIGH, "yes")),
    ],
)
def test_policy_rejects_malformed_rules(rule):
    rules = dict(DEFAULT_POLICY.rules)
    rules["cancel_booking"] = rule

    with pytest.raises(ValueError):
        ActionPolicy(rules)
