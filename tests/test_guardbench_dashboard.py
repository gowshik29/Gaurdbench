from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_guardbench_dashboard_loads_saved_risk_aware_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("LANGSMITH_TRACING", "false")

    app = AppTest.from_file(str(PROJECT_ROOT / "dashboard.py")).run(timeout=20)

    assert not app.exception
    assert app.title[0].value == "GuardBench"
    assert any(
        selectbox.label == "Agent mode"
        for selectbox in app.selectbox
    )
