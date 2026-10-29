import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


ACTION_NAMES = frozenset(
    {
        "get_booking",
        "search_flights",
        "rebook_flight",
        "cancel_booking",
        "issue_refund",
        "grant_compensation",
        "change_payment_method",
        "baggage_claim",
    }
)


@dataclass(frozen=True)
class ActionRule:
    risk_level: RiskLevel
    approval_required: bool


DEFAULT_RULES = {
    "get_booking": ActionRule(RiskLevel.LOW, False),
    "search_flights": ActionRule(RiskLevel.LOW, False),
    "rebook_flight": ActionRule(RiskLevel.MEDIUM, True),
    "baggage_claim": ActionRule(RiskLevel.MEDIUM, True),
    "cancel_booking": ActionRule(RiskLevel.HIGH, True),
    "issue_refund": ActionRule(RiskLevel.HIGH, True),
    "grant_compensation": ActionRule(RiskLevel.HIGH, True),
    "change_payment_method": ActionRule(RiskLevel.CRITICAL, True),
}


class ActionPolicy:
    """Validated immutable policy with a content-derived version identifier."""

    def __init__(self, rules: Mapping[str, ActionRule] | None = None):
        normalized = dict(DEFAULT_RULES if rules is None else rules)
        unknown = set(normalized) - ACTION_NAMES
        missing = ACTION_NAMES - set(normalized)
        if unknown or missing:
            raise ValueError(
                f"Policy actions must exactly match the allow-list; "
                f"unknown={sorted(unknown)}, missing={sorted(missing)}"
            )
        for action, rule in normalized.items():
            if not isinstance(rule, ActionRule):
                raise ValueError(f"Invalid policy rule for {action}")
            if not isinstance(rule.risk_level, RiskLevel):
                raise ValueError(f"Invalid risk level for {action}")
            if not isinstance(rule.approval_required, bool):
                raise ValueError(f"Invalid approval requirement for {action}")
        self._rules = normalized
        canonical = json.dumps(
            {
                name: {
                    "risk_level": rule.risk_level.value,
                    "approval_required": rule.approval_required,
                }
                for name, rule in sorted(normalized.items())
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.version = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @classmethod
    def from_mapping(cls, mapping):
        if not isinstance(mapping, dict):
            raise ValueError("Policy mapping must be an object")
        rules = {}
        for action, raw_rule in mapping.items():
            if not isinstance(raw_rule, dict) or set(raw_rule) != {
                "risk_level",
                "approval_required",
            }:
                raise ValueError(f"Invalid policy rule for {action}")
            try:
                risk_level = RiskLevel(raw_rule["risk_level"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid risk level for {action}") from exc
            rules[action] = ActionRule(
                risk_level,
                raw_rule["approval_required"],
            )
        return cls(rules)

    @property
    def rules(self) -> Mapping[str, ActionRule]:
        return dict(self._rules)

    def to_mapping(self):
        return {
            name: {
                "risk_level": rule.risk_level.value,
                "approval_required": rule.approval_required,
            }
            for name, rule in sorted(self._rules.items())
        }

    def rule_for(self, action: str) -> ActionRule:
        try:
            return self._rules[action]
        except KeyError as exc:
            raise ValueError(f"Action not allow-listed: {action}") from exc

    def requires_approval(self, action: str) -> bool:
        return self.rule_for(action).approval_required


DEFAULT_POLICY = ActionPolicy()
SENSITIVE_ACTIONS = frozenset(
    action for action in ACTION_NAMES if DEFAULT_POLICY.requires_approval(action)
)


def is_sensitive(action):
    """Compatibility helper for callers using the default policy."""
    return action in SENSITIVE_ACTIONS
