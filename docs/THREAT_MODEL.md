# GuardBench Threat Model

## Assets and trust boundaries

- **Assets:** simulated reservation state, one-use approvals, gate policy,
  SQLite proposal/audit history, experiment labels, and generated reports.
- **Untrusted inputs:** user prompts, LLM action proposals/responses, model
  judge output, retrieved or quoted content, external tool output, τ²-bench
  messages, and approval-file contents until exact action/argument matching.
- **Trusted components:** Python action allow-list and schema validation,
  `ActionPolicy`, `ConfirmationGate`, and explicit human input routed through
  the local CLI or Streamlit approval control.
- **Dispatch:** public `SimulatedAirlineTools.dispatch` refuses sensitive
  actions. `GatedAirlineTools` reaches its private simulator dispatch only from
  the callback passed to `ConfirmationGate.execute`. τ²-bench mutating
  assistant calls use `GatedTau2Environment` and `execute_external`. Read-only
  calls are also logged through the gate before invoking the original
  environment; simulated-user mutating calls are blocked without an
  assistant-scoped trusted approval.
- **Evaluation baseline:** synthetic “baseline” disables the approval rule as
  an explicit research treatment, but still traverses the trusted gate, schema
  validation, and audit path. It must not be used as a runtime configuration.

## Controls

| Threat | Control |
|---|---|
| Direct simulator mutation bypass | Public simulator dispatch rejects sensitive operations; regression tests exercise direct bypass and assert no state change. |
| Model-generated or retrieved claim of approval | No action/judge/retrieval/tool text is passed to `approve`; approval is bound to an explicit local UI/CLI call and exact proposal. Missing approval ID blocks. |
| Argument substitution, replay, cross-session reuse, or policy drift | Canonical action/argument fingerprint, one-use SQLite state transition, actor/session identity, content-derived policy version, and proposal expiry. |
| Unknown actions or malformed/oversized input | Allow-list, typed action-specific validation, finite JSON serialization, and size limit fail closed. |
| Audit row modification, reordering, or deletion | UUID-bearing canonical events with SHA-256 previous-hash chain and verifier; legacy database is migrated additively. |
| Judge manipulation or invalid output | Local judge output is parsed and independently validated; evidence paths must exist in the episode; verdicts are evaluator-only. |
| Confounded experiment labels | Deterministic authorization fields, human task-quality labels, and judge predictions are kept in distinct fields/files. |
| Benchmark mixing | Synthetic results are labeled synthetic; τ²-bench uses a separate runner, output directory, package/data provenance, and original evaluator. |

## Residual risk and non-production status

- The hash chain is stored in the same SQLite database. Anyone able to rewrite
  the entire file can recompute the chain; no separately stored checkpoint,
  signature, or immutable external anchor is implemented.
- SQLite approval consumption is committed before a tool callback runs. The
  database cannot atomically commit an arbitrary side effect; a crash after
  consumption may leave an action unexecuted or its outcome uncertain.
- The simulator's internal capability is a Python module-level object and is
  a guard against accidental direct call paths, not a defense against an
  attacker with arbitrary code execution in the process.
- The single-user application has no authenticated identity provider. Actor
  values are local labels and Streamlit/CLI sessions use generated session IDs;
  they are not cryptographic authentication.
- Approval requirements for the trusted baseline and risk-ablation modes are
  deliberately altered for research. These modes are not production policies.
- Full arguments and action results can be present in SQLite audit details.
  Use synthetic data only; field-level audit minimization, configurable
  retention, and at-rest encryption are not implemented.
- External tools may produce side effects that cannot be undone. Review and
  reconcile outcomes when dispatch reports failure or the process terminates.
- No remote deployment controls, multi-user access controls, independent
  checkpoint service, or formal security certification are implemented.

The deterministic test suite verifies selected boundary properties. It does
not prove the absence of vulnerabilities, establish model refusal quality, or
demonstrate production readiness.
