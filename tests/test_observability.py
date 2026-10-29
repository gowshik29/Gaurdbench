import pytest

from app.observability import _trace_destination


def test_agent_destination_is_used_when_configured(monkeypatch):
    monkeypatch.setenv("LANGSMITH_AGENT_ID", "guardbench")
    monkeypatch.setenv("LANGSMITH_AGENT_ENVIRONMENT", "local")

    destination = _trace_destination()

    assert "address" in destination
    assert "project_name" not in destination


@pytest.mark.parametrize(
    ("agent_id", "environment"),
    [("guardbench", None), (None, "local")],
)
def test_partial_agent_destination_fails_clearly(monkeypatch, agent_id, environment):
    if agent_id is None:
        monkeypatch.delenv("LANGSMITH_AGENT_ID", raising=False)
    else:
        monkeypatch.setenv("LANGSMITH_AGENT_ID", agent_id)
    if environment is None:
        monkeypatch.delenv("LANGSMITH_AGENT_ENVIRONMENT", raising=False)
    else:
        monkeypatch.setenv("LANGSMITH_AGENT_ENVIRONMENT", environment)

    with pytest.raises(RuntimeError, match="Set both LANGSMITH_AGENT_ID"):
        _trace_destination()


def test_project_destination_used_when_agent_is_unset(monkeypatch):
    monkeypatch.delenv("LANGSMITH_AGENT_ID", raising=False)
    monkeypatch.delenv("LANGSMITH_AGENT_ENVIRONMENT", raising=False)

    destination = _trace_destination()

    assert destination == {"project_name": "guardbench-local"}
