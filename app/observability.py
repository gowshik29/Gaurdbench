import functools
import os

from .settings import get_settings, langsmith_tracing_enabled


_REDACTED = "[redacted]"
_SENSITIVE_TRACE_KEYS = {
    "args",
    "arguments",
    "content",
    "error",
    "message",
    "request",
    "token",
}


def _redact_trace_values(value):
    if isinstance(value, dict):
        return {
            key: _REDACTED
            if str(key).lower() in _SENSITIVE_TRACE_KEYS
            or any(
                marker in str(key).lower()
                for marker in ("password", "card", "booking_id", "last4")
            )
            else _redact_trace_values(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_trace_values(item) for item in value]
    return value


def _tracing_enabled():
    return langsmith_tracing_enabled()


def _trace_destination():
    agent_id = os.getenv("LANGSMITH_AGENT_ID")
    environment = os.getenv("LANGSMITH_AGENT_ENVIRONMENT")
    if bool(agent_id) != bool(environment):
        raise RuntimeError(
            "Set both LANGSMITH_AGENT_ID and LANGSMITH_AGENT_ENVIRONMENT "
            "to trace to a LangSmith agent, or unset both to trace to a project."
        )
    if agent_id and environment:
        import langsmith

        if hasattr(langsmith, "agent_address"):
            address = langsmith.agent_address(agent_id, environment)
        else:
            # Older langsmith releases lack agent_address; keep trace routing stable.
            address = {
                "kind": "AGENT",
                "id": agent_id,
                "environment": str(environment).upper(),
            }
        return {"address": address}
    return {"project_name": get_settings()["langsmith_project"]}


@functools.lru_cache(maxsize=None)
def _langsmith_instrument(function, run_type):
    try:
        from langsmith import traceable
    except ImportError as exc:
        raise RuntimeError(
            "LangSmith tracing is enabled but the langsmith package is missing. "
            "Install project requirements before enabling tracing."
        ) from exc
    return traceable(
        name=function.__qualname__,
        run_type=run_type,
        **_trace_destination(),
        process_inputs=_redact_trace_values,
        process_outputs=_redact_trace_values,
    )(function)


def traced(run_type="chain"):
    """Enable LangSmith tracing per call when LANGSMITH_TRACING is enabled."""

    def decorate(function):
        @functools.wraps(function)
        def wrapper(*args, **kwargs):
            if not _tracing_enabled():
                return function(*args, **kwargs)
            return _langsmith_instrument(function, run_type)(*args, **kwargs)

        return wrapper

    return decorate
