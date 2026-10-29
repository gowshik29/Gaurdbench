# Upgrade acceptance matrix

Assurance labels are intentionally separate:

- **Implemented**: code or documentation exists.
- **Tested**: deterministic local regression test has passed.
- **Experimentally validated**: a recorded experiment has been executed and its
  result reviewed. Synthetic experiments are labeled as such.
- **Production-ready**: independent security, deployment, privacy, recovery,
  and operational requirements have been addressed. This project is **not
  production-ready**.

Status verified on **2026-10-26** on Windows with Python 3.12.1 (`.venv`).
CI workflow existence does not imply that GitHub Actions has run on GitHub.

| Requirement | Implementation location | Test/evidence | Status | Observed result | Remaining limitation |
|---|---|---|---|---|---|
| Existing regression behavior | Full GuardBench suite | `.\.venv\Scripts\python.exe -m pytest -q` | PASS (Tested) | **108 passed**, 0 failed, 0 skipped, 1 pandas deprecation warning in 10.05s | FinSight modules removed; suite is GuardBench-only (108 tests). |
| Strict action validation | `guardrails/action_policy.py`, `guardrails/confirmation_gate.py` | `tests/test_action_policy.py`, adversarial invalid-arg tests | PASS (Tested) | Unknown actions, malformed types, oversized input blocked | Policy file/UI loading not implemented. |
| Exact approval binding | `guardrails/confirmation_gate.py` | `tests/test_gate.py`, `tests/test_adversarial_gate.py` | PASS (Tested) | Fingerprint, actor/session, policy version enforced | Actor IDs are local labels only. |
| Approval expiry | `guardrails/confirmation_gate.py` | `tests/test_gate.py::test_expired_proposal_cannot_be_approved_or_executed` | PASS (Tested) | Expired proposals rejected | — |
| Replay protection | `guardrails/confirmation_gate.py` | Replay and competing-dispatch tests | PASS (Tested) | One-time consumption | External side effects not atomic with SQLite. |
| Concurrent dispatch protection | `guardrails/confirmation_gate.py` | `test_competing_replays_can_execute_only_once` | PASS (Tested) | Single winner under contention | — |
| Actor/session binding | `guardrails/confirmation_gate.py` | `test_approval_is_bound_to_actor_and_session` | PASS (Tested) | Cross-actor reuse blocked | No auth provider. |
| Direct-dispatch bypass prevention | `app/airline_tools.py`, `app/gated_tools.py` | Direct simulator dispatch tests | PASS (Tested) | Sensitive public dispatch rejected | In-process CPython, not a sandbox. |
| Audit-chain integrity | `guardrails/confirmation_gate.py` | Migration, tamper, reorder tests; CLI verifier | PASS (Tested) | `python -m guardrails.confirmation_gate --db logs\audit.db` → `valid: true`, 121 events | Same-DB chain; no external checkpoint. |
| Adversarial security cases | `evaluation/adversarial_cases.py`, gate tests | 30+ prompt-pressure cases + structured case records | PASS (Tested) | Text never authorizes; stable case IDs recorded | Model-dependent refusal not measured here. |
| Judge output validation | `judge/llm_judge.py`, `judge/rubric.py` | `tests/test_judge_validation.py` | PASS (Tested) | Schema validation with fake client | No live Ollama judge run in this verification. |
| Human-label agreement | `evaluation/label_metrics.py`, `evaluation/score_judge.py` | `tests/test_evaluation_metrics.py` | PASS (Tested) | Metrics helpers pass; missing labels excluded | No human-labeled dataset shipped. |
| Confidence calibration | `evaluation/label_metrics.py` | Calibration unit tests | PASS (Tested) | Inconclusive below minimum sample | No held-out calibration experiment run. |
| Reproducible experiment metadata | `evaluation/run_experiments.py`, `evaluation/reproducibility.py` | Smoke run `20261026T102640Z-28fb32ed` | PASS (Experimentally validated) | Metadata + reproducibility markdown written for synthetic run (4 episodes/mode, seed 17) | No Git revision (no `.git` directory). |
| Baseline / gated / risk-aware comparison | `evaluation/run_experiments.py` | Ablation tests + smoke run outputs | PASS (Tested + validated) | Three modes in smoke run; prior 32-episode ablation under `data/ablations/` | Synthetic fixtures only; not LLM behavior. |
| Synthetic versus τ²-bench separation | `evaluation/run_experiments.py`, `adapters/tau2_adapter.py` | Adapter unit tests; smoke run banner | PASS (Tested) | Smoke run labeled synthetic-only | **τ²-bench package not installed** in `.venv`; real benchmark run **NOT RUN**. |
| Dashboard data integrity | `dashboard.py` | `tests/test_guardbench_dashboard.py` | PASS (Tested) | AppTest loads saved risk-aware run | Attack heatmap, calibration plot, multi-run compare not browser-verified. |
| Documentation | `docs/*`, `README.md` | Manual review | PASS (Implemented) | Threat model, metrics, protocol, upgrade plan present | Claims match tested scope only. |
| Continuous integration | `.github/workflows/ci.yml` | Local: pytest, ruff E9/F63/F7/F82, compileall | PASS (Tested locally) | All local CI steps pass on GuardBench tree | GitHub Actions execution **NOT RUN** from this workspace. |
| Ollama model availability | `app/ollama_client.py`, `scripts/check_setup.py` | `check_setup.py`; API probe | PASS (Tested) | `qwen2.5:3b` available on loopback | Model-dependent adversarial suite not executed separately. |
| Production readiness | `docs/THREAT_MODEL.md` | Explicit non-claims | N/A | **Not production-ready** | See threat model residual risks. |

Detailed command log: [`reports/FINAL_VERIFICATION_REPORT.md`](../reports/FINAL_VERIFICATION_REPORT.md).
