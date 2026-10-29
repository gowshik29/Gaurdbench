# GuardBench final verification report

**Date:** 2026-10-26  
**Platform:** Windows 10, Python 3.12.1 (project `.venv`)  
**Git:** Not a git repository (no revision recorded)

## Phase zero audit summary

The repository implements a local-first GuardBench framework: airline demo agent,
`ActionPolicy` + `ConfirmationGate`, hash-chained SQLite audit, adversarial fixtures,
local judge validation, synthetic three-mode experiment runner, τ²-bench adapter (unit-tested),
Streamlit dashboard, optional LangSmith tracing, and Promptfoo configuration.

Unrelated **FinSight** modules (separate financial RAG stack), their tests, data,
dashboard, and docs were **removed** so the tree matches the GuardBench mission.

## Original test baseline (this session)

| Command | Exit | Result |
|---|---|---|
| `python -m pytest --collect-only -q` (system Python, before cleanup) | 2 | 186 collected, **2 collection errors** (`duckdb` missing for FinSight tests) |
| `python -m pytest -q` with FinSight ignores (system Python) | 1 | **182 passed, 4 failed** (3 FinSight evaluation + 1 LangSmith `agent_address` on older langsmith) |
| `.\.venv\Scripts\python.exe -m pytest --collect-only -q` (after FinSight removal) | 0 | **108 tests collected**, 0 errors |
| `.\.venv\Scripts\python.exe -m pytest -q` (after FinSight removal) | 0 | **108 passed**, 0 failed, 0 skipped, 1 warning |

Prior upgrade audit (documented in `docs/UPGRADE_PLAN.md`) recorded **161 passed**
when FinSight tests were still present in the venv environment.

## Environment checks

| Check | Result |
|---|---|
| Ollama API `http://127.0.0.1:11434/api/tags` | Reachable; model **`qwen2.5:3b`** listed |
| `python scripts/check_setup.py` | Exit 0; Python 3.12.1, Ollama CLI+API OK |
| τ²-bench import (`import tau2`) | **NOT RUN** — `ModuleNotFoundError` (install via `requirements-tau2.txt` when needed) |

## Commands executed (final verification)

| Command | Exit | Summary |
|---|---|---|
| `python -m compileall -q app guardrails evaluation judge adapters tests scripts dashboard.py` | 0 | OK |
| `python -m ruff check --select E9,F63,F7,F82 ...` | 0 | All checks passed |
| `python -m pytest -q` | 0 | 108 passed |
| `python -m guardrails.confirmation_gate --db logs\audit.db` | 0 | `{"valid": true, "events_checked": 121, ...}` |
| `python -m evaluation.run_experiments --benchmark synthetic --episodes 4 --seed 17` | 0 | Run `20261026T102640Z-28fb32ed`; baseline/gated/risk_aware episodes saved; report + reproducibility markdown under `data/reports/` |
| τ²-bench live evaluation | NOT RUN | Package not installed in `.venv` |
| Streamlit manual browser session | NOT RUN | AppTest coverage via `tests/test_guardbench_dashboard.py` only |
| GitHub Actions workflow on GitHub | NOT RUN | Workflow file updated locally |

## Synthetic smoke run (not a benchmark)

Run ID: **`20261026T102640Z-28fb32ed`** (4 episodes per mode, seed 17).  
Outputs:

- `data/20261026T102640Z-28fb32ed-metadata.json`
- `data/reports/20261026T102640Z-28fb32ed.md`
- `data/reports/20261026T102640Z-28fb32ed-reproducibility.md`

This is **deterministic synthetic fixture output**, not τ²-bench results.

## Files changed in this completion pass

- Removed: `finsight/`, `finsight_dashboard.py`, `requirements-finsight.txt`, `data/finsight/`, FinSight tests and docs.
- Updated: `app/observability.py` (LangSmith `agent_address` compatibility fallback).
- Updated: `.github/workflows/ci.yml` (GuardBench-only paths and `requirements.txt`).
- Updated: `docs/THREAT_MODEL.md`, `docs/UPGRADE_PLAN.md`, `docs/ACCEPTANCE_MATRIX.md`.

## Known limitations (honest)

1. **Not production-ready** — see `docs/THREAT_MODEL.md`.
2. **τ²-bench end-to-end** not executed; adapter tests pass only.
3. **No git metadata** for reproducibility fields that depend on revision.
4. **Audit hash chain** is same-database; no independent checkpoint.
5. **Human labels / calibration** helpers tested; no shipped labeled dataset.
6. **Dashboard** advanced analytics (heatmaps, calibration UI) partially implemented; not fully browser-verified.
7. **CI on GitHub** not observed from this environment.

## Acceptance matrix

See [`docs/ACCEPTANCE_MATRIX.md`](../docs/ACCEPTANCE_MATRIX.md).
