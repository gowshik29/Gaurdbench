from adapters.tau2_adapter import (
    GatedTau2Environment,
    _collect_tool_actions,
    _require_tau2_data,
)
from guardrails.confirmation_gate import ConfirmationGate
from evaluation import run_experiments


def test_tau2_missing_data_error_explains_required_location(tmp_path):
    missing_task_file = tmp_path / "tau2" / "domains" / "airline" / "tasks.json"

    try:
        _require_tau2_data([missing_task_file])
    except RuntimeError as error:
        assert "Set TAU2_DATA_DIR" in str(error)
        assert "language pack" in str(error)
        assert str(missing_task_file) in str(error)
    else:
        raise AssertionError("Missing τ²-bench data should fail with setup instructions")


def test_tau2_airline_user_tools_are_optional():
    from adapters.tau2_adapter import _user_tools_for_task

    class EnvironmentWithoutUserTools:
        user_tools = None

        def get_user_tools(self, include=None):
            raise AssertionError("Unavailable user tools should not be requested")

    class TaskWithoutUserTools:
        user_tools = None

    assert _user_tools_for_task(
        EnvironmentWithoutUserTools(),
        TaskWithoutUserTools(),
    ) is None


def test_tau2_tool_action_collection_skips_tool_messages():
    class Call:
        name = "cancel_reservation"
        arguments = {"reservation_id": "ZFA04Y"}
        requestor = "assistant"

    class AssistantMessage:
        tool_calls = [Call()]

    class ToolMessage:
        content = "Cancelled"

    class Environment:
        def _is_mutating_tool(self, tool_name):
            return tool_name == "cancel_reservation"

    actions = _collect_tool_actions(
        [AssistantMessage(), ToolMessage()],
        Environment(),
    )

    assert actions == [
        {
            "tool_name": "cancel_reservation",
            "arguments": {"reservation_id": "ZFA04Y"},
            "requestor": "assistant",
            "mutates_state": True,
        }
    ]


class FakeTau2Environment:
    def __init__(self):
        self.calls = []

    def _is_mutating_tool(self, tool_name):
        return tool_name in {"cancel_reservation", "update_reservation_flights"}

    def make_tool_call(self, tool_name, requestor="assistant", **kwargs):
        self.calls.append((tool_name, requestor, kwargs))
        return {"tool": tool_name, "arguments": kwargs}


def test_tau2_mutation_is_blocked_without_external_confirmation(tmp_path):
    environment = FakeTau2Environment()
    gated = GatedTau2Environment(
        environment,
        ConfirmationGate(tmp_path / "audit.db"),
    )

    result = gated.make_tool_call(
        "cancel_reservation",
        requestor="assistant",
        reservation_id="ZFA04Y",
    )

    assert result["status"] == "blocked"
    assert environment.calls == []


def test_tau2_mutation_preserves_tool_result_after_exact_approval(tmp_path):
    environment = FakeTau2Environment()
    gate = ConfirmationGate(tmp_path / "audit.db")
    approval = {"tool_name": "cancel_reservation", "arguments": {"reservation_id": "ZFA04Y"}}
    used = False

    def approve(proposal):
        nonlocal used
        if used:
            return False
        used = proposal["action"] == approval["tool_name"] and proposal["arguments"] == approval["arguments"]
        return used

    gated = GatedTau2Environment(environment, gate, approve)
    result = gated.make_tool_call(
        "cancel_reservation",
        requestor="assistant",
        reservation_id="ZFA04Y",
    )

    assert result == {
        "tool": "cancel_reservation",
        "arguments": {"reservation_id": "ZFA04Y"},
    }
    assert len(environment.calls) == 1


def test_tau2_readonly_and_user_calls_keep_original_routing(tmp_path):
    environment = FakeTau2Environment()
    gate = ConfirmationGate(tmp_path / "audit.db")
    gated = GatedTau2Environment(
        environment,
        gate,
    )

    read_result = gated.make_tool_call(
        "get_reservation_details",
        requestor="assistant",
        reservation_id="ZFA04Y",
    )
    user_result = gated.make_tool_call(
        "get_reservation_details",
        requestor="user",
        reservation_id="ZFA04Y",
    )

    assert read_result["tool"] == "get_reservation_details"
    assert user_result["tool"] == "get_reservation_details"
    assert [call[1] for call in environment.calls] == ["assistant", "user"]
    events = gate.audit_events()
    assert [event["event_type"] for event in events].count(
        "external_readonly_tool_dispatched"
    ) == 2
    assert {event["actor_id"] for event in events} == {
        "tau2-agent:assistant",
        "tau2-agent:user",
    }


def test_tau2_user_mutating_tool_is_not_authorized_by_approval_fixture(tmp_path):
    environment = FakeTau2Environment()
    gate = ConfirmationGate(tmp_path / "audit.db")
    approval = lambda proposal: True
    gated = GatedTau2Environment(environment, gate, approval)

    result = gated.make_tool_call(
        "cancel_reservation",
        requestor="user",
        reservation_id="ZFA04Y",
    )

    assert result["status"] == "blocked"
    assert environment.calls == []
    assert any(
        event["event_type"] == "external_mutating_tool_blocked"
        for event in gate.audit_events()
    )


def test_evaluation_entrypoint_defaults_to_tau2(monkeypatch, tmp_path):
    from adapters import tau2_adapter

    calls = []
    monkeypatch.setattr(tau2_adapter, "run_tau2", lambda args: calls.append(args))
    monkeypatch.setattr(
        "sys.argv",
        ["evaluation.run_experiments", "--output", str(tmp_path)],
    )

    run_experiments.main()

    assert len(calls) == 1
    assert calls[0].split == "base"
    assert calls[0].limit == 2
    assert calls[0].output == tmp_path


def test_evaluation_entrypoint_keeps_synthetic_mode_explicit(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        run_experiments,
        "run_experiment",
        lambda episodes, output, seed: calls.append((episodes, output, seed)),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "evaluation.run_experiments",
            "--benchmark",
            "synthetic",
            "--episodes",
            "3",
            "--seed",
            "23",
            "--output",
            str(tmp_path),
        ],
    )

    run_experiments.main()

    assert calls == [(3, tmp_path, 23)]
