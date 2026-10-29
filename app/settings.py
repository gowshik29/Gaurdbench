import json
import os
from functools import lru_cache
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@lru_cache(maxsize=4)
def _read_config(path):
    config_path = Path(path)
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Unable to read GuardBench config: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in GuardBench config: {config_path}") from exc
    if not isinstance(config, dict):
        raise ValueError("GuardBench config must be a JSON object")
    return config


def get_settings():
    config_path = os.getenv("GUARDBENCH_CONFIG", str(_PROJECT_ROOT / "config.json"))
    config = _read_config(config_path)
    settings = {
        "ollama_base_url": os.getenv(
            "OLLAMA_BASE_URL",
            config.get("ollama_base_url", "http://localhost:11434"),
        ),
        "ollama_model": os.getenv(
            "OLLAMA_MODEL",
            config.get("ollama_model", "qwen2.5:3b"),
        ),
        "audit_db": os.getenv("AUDIT_DB_PATH", config.get("audit_db", "logs/audit.db")),
        "langsmith_tracing": os.getenv("LANGSMITH_TRACING"),
        "langsmith_project": os.getenv(
            "LANGSMITH_PROJECT",
            config.get("langsmith_project", "guardbench-local"),
        ),
    }
    for key in ("ollama_base_url", "ollama_model", "audit_db", "langsmith_project"):
        if not isinstance(settings[key], str) or not settings[key].strip():
            raise ValueError(f"GuardBench setting {key!r} must be a non-empty string")
    return settings


def langsmith_tracing_enabled():
    configured = get_settings()["langsmith_tracing"]
    if configured is None:
        configured = _read_config(
            os.getenv("GUARDBENCH_CONFIG", str(_PROJECT_ROOT / "config.json"))
        ).get("langsmith_tracing", False)
    return str(configured).strip().lower() in {"1", "true", "yes", "on"}
