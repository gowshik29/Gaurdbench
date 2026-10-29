# GuardBench Upgrade Plan

## Audit baseline

- Audited the existing policy, confirmation gate, action-agent boundary, audit
  storage, adversarial fixtures, judge, synthetic experiment runner, τ²-bench
  adapter, Streamlit dashboard, configuration, dependency manifests, and tests.
- Baseline command (pre-upgrade audit): `.\.venv\Scripts\python.exe -m pytest -q`
- Baseline result at audit time: **161 passed in 10.90 seconds** (Python 3.12.1),
  including unrelated FinSight modules that were later removed from this repository.
- Post-cleanup GuardBench-only suite: **108 tests collected**, command
  `.\.venv\Scripts\python.exe -m pytest -q`, **108 passed** (2026-10-26).
- The workspace has no `.git` directory, so the current Git revision cannot be
  recorded or used to compare a later implementation against a repository
  commit.
- No application files were changed as part of this initial audit.
- A focused security review of the reviewed source and tests found no
  actionable, high-confidence vulnerability. The capability gaps below are
  upgrade requirements, not claims of confirmed exploits.

## Current capabilities and gaps

### Authorization and dispatch

`guardrails/action_policy.py` allow-lists eight airline actions and classifies
six as sensitive. `guardrails/confirmation_gate.py` validates action arguments,
limits serialized arguments to 16 KiB, computes canonical JSON fingerprints,
and requires exact, one-use approval for sensitive and external mutating calls.
The gate persists proposals and audit events in SQLite. Existing tests cover
unknown actions, argument changes, replay, malformed/oversized inputs, and
concurrent attempts to consume one approval.

The policy is currently a fixed sensitive-action set, not a configurable,
versioned risk policy. Approvals have no expiry, actor/session binding, or
policy-version binding. An explicit `yes` is stored against a proposal, but
identity and approval provenance are not validated. SQLite serializes the
approval state transition and records the dispatch event before invoking the
tool; the tool call occurs after that transaction commits. Consequently,
approval consumption is one-time and transactionally serialized, but the
database transaction cannot make an arbitrary external tool side effect atomic
with the audit write.

### Audit

Audit rows have an autoincrementing sequence, timestamp, event type, action,
arguments, fingerprint, proposal ID, and JSON details. This supports event
inspection, but there are no unique event UUIDs, event schema/version,
actor/session fields, policy version, hash chain, chain verifier, or retention
configuration. Arguments and some result/error details are stored in
cleartext. A future hash chain can detect accidental or partial tampering, but
cannot prevent an attacker with database write access from rewriting the
entire chain; separately stored checkpoints would be needed to anchor history.

### Adversarial evaluation

The existing deterministic adversarial suite checks prompt-pressure examples
against the real gate and tests mutation/replay and concurrent approval
consumption. Cases are currently tuples of pressure label and message; they do
not carry stable IDs, threat/property descriptions, observed outcomes, or
attack-category reporting. Prompt attacks are not proof of enforcement; gate
tests remain the relevant authorization evidence.

### Judge and human labels

`judge/llm_judge.py` requests structured JSON and parses the response, but does
not independently validate the parsed fields or reject additional/invalid
values. The current verdict includes task success, policy compliance, severity,
clause reference, evidence, and a short reasoning summary, but not argument
correctness, evidence support as an explicit dimension, a PASS/FAIL/UNCERTAIN
verdict, confidence, or a machine-readable failure category.

The label-template and scoring scripts support explicit true/false labels and
report accuracy and Cohen's kappa. They do not calculate precision, recall,
F1, a confusion matrix, uncertainty/class imbalance, or calibration metrics;
they do not distinguish held-out calibration data. Existing agreement excludes
missing and unknown labels, which should be preserved.

### Experiment runner and reports

The synthetic runner saves deterministic episodes for an ungated baseline and
the existing confirmation-gated mode, with seed/run metadata, latency,
policy-aware task success, unauthorized-execution and false-block fields, and
JSON/CSV/Markdown summaries. It explicitly labels these deterministic fixtures
as synthetic rather than τ²-bench. It does not run a risk-aware mode, aggregate
repeated seeds, calculate false-allow rates or confidence intervals, or capture
all requested software/policy metadata.

The τ²-bench adapter is separately pinned to commit
`05736c27219b769d0be507574dd3135010916644`, uses the benchmark's original
evaluator, and records baseline/gated task results and audit events. Actual
τ²-bench execution additionally requires the pinned package, benchmark data,
language pack, and a reachable local Ollama model. This audit ran the Python
test suite, not a τ²-bench experiment, so actual benchmark behavior and results
remain unverified. Synthetic and τ²-bench reports must remain separate.

### Dashboard and project documentation

`dashboard.py` displays saved τ²-bench and synthetic results with separate
sections, empty states, basic outcome metrics, episode outcomes, and a latency
chart. It does not yet compare three agent modes or display attack-category
heatmaps, false-allow analysis, judge-human agreement, calibration, or
proposal/gate/audit drill-down.

`docs/THREAT_MODEL.md`, `docs/METRICS.md`, and `docs/EXPERIMENT_PROTOCOL.md`
now document GuardBench only. Unrelated FinSight modules were removed from
this repository so the GuardBench framework stays focused and reproducible.

## Proposed implementation sequence

Each phase should be implemented and reviewed independently, with focused
regression tests followed by the full suite when practical.

1. **Versioned risk policy and approval context**
   - Extend the existing action policy and gate rather than creating a second
     authorization path.
   - Define LOW, MEDIUM, HIGH, and CRITICAL risk levels, a validated,
     configurable action mapping, and deterministic policy versioning.
   - Add strict request handling and bind approvals to the canonical proposal
     fingerprint, actor/session identity, policy version, and expiry.
   - Preserve legacy call signatures where safe; fail closed when the new
     required identity/context cannot be established.
   - Test invalid policies, unknown actions, malformed input, expiry, replay,
     argument mutation, identity mismatch, policy changes, and concurrent
     dispatch.

2. **Tamper-evident, minimized audit records**
   - Add event IDs, schema version, structured decision outcome/reason,
     actor/session, proposal fingerprint, policy version, and canonical event
     serialization.
   - Migrate the existing SQLite schema additively and keep `audit_events()`
     compatible for existing consumers.
   - Add chain verification and tests for altered, reordered, deleted, and
     malformed records.
   - Minimize/redact sensitive values and define retention. Document SQLite
     transaction boundaries and the limits of a hash chain; evaluate separately
     stored checkpoints without implying they prevent full database rewrites.

3. **Structured adversarial cases and outcomes**
   - Evolve existing fixtures without removing the deterministic gate tests.
   - Give cases stable IDs, category, threat, expected security property, and
     observed outcome; add indirect/tool-output injection, cross-session reuse,
     approval substitution, and judge-manipulation coverage.
   - Keep deterministic gate assertions separate from model-dependent prompt
     attack/refusal measurements. Report unauthorized execution independently
     from model refusal.

4. **Validated judge and human-label analysis**
   - Extend the existing judge schema and validate every returned field and
     allowed value after JSON parsing.
   - Add argument correctness, evidence support, PASS/FAIL/UNCERTAIN,
     confidence, evidence references, and failure category. The judge remains
     an evaluator only and must never authorize tools.
   - Extend label scoring with precision, recall, F1, confusion matrix,
     class balance, uncertainty, and agreement; exclude missing labels.
   - Add separate calibration data and reliability/ECE reporting only when
     sample size permits. Describe judge confidence as uncalibrated until
     validated against a sufficiently sized held-out label set.

5. **Comparable reproducible experiments**
   - Extend the synthetic runner with baseline, existing confirmation-gated,
     and risk-aware policy-gated modes while keeping the existing synthetic
     fixtures distinct from τ²-bench.
   - Record run ID, revision if available, benchmark/dataset, model and
     inference settings, policy version, seed, task IDs, timestamps, software
     versions, metrics, and failure categories.
   - Add repeated-seed aggregation, false-allow/false-block metrics when ground
     truth exists, confirmation rates, latency summaries, attack breakdowns,
     judge-human agreement, and appropriately qualified confidence intervals.
   - Preserve existing output fields where practical and test old consumers.

6. **Research dashboard and documentation**
   - Extend `dashboard.py` to select and compare saved runs; show actual saved
     values only, distinguish synthetic/local-model/actual τ²-bench evidence,
     and provide explicit empty/invalid-result states.
   - Add requested risk/attack, false-allow/false-block, latency, judge
     agreement, calibration, episode, proposal, gate, and audit views.
   - Add GuardBench-specific `docs/THREAT_MODEL.md`, `docs/METRICS.md`, and
     `docs/EXPERIMENT_PROTOCOL.md`; update `README.md` with actual setup,
     migration, interpretation, and known limitations.

## Compatibility risks and controls

- **SQLite migration:** Existing audit databases must remain readable. Use
  additive, transactional schema migration and test against a database created
  with the current schema; do not discard existing audit history.
- **Public interfaces:** `ConfirmationGate.propose`, `approve`, `execute`,
  `execute_external`, and `audit_events` are used by the app, tests, and τ²
  adapter. Preserve signatures or provide explicit backward-compatible
  defaults; identity/expiry requirements must not silently weaken fail-closed
  behavior.
- **Approval UX:** Identity and expiry affect CLI, Streamlit, and τ² approval
  fixtures. Update all entry points and display/record enough context for
  explicit, informed confirmation.
- **Dispatch semantics:** A SQLite transaction cannot roll back an external
  side effect. Keep one-time consumption before dispatch, record outcomes
  accurately, and document the failure window if a process stops after
  consumption but before or during tool execution.
- **Existing report consumers:** Add new metadata and metrics without
  renaming/removing existing fields unless a migration is documented and
  tested.
- **Benchmark validity:** Never mix synthetic fixture episodes with τ²-bench
  task results. The original τ² evaluator, pinned dependency/data, model, and
  seed must be recorded for real benchmark claims.
- **Judge calibration:** Do not claim calibrated probabilities or meaningful
  confidence intervals from a tiny or non-held-out sample. Keep calibration
  labels separate from evaluation labels.
- **Local-first constraint:** Retain Ollama as the inference path, avoid paid
  APIs/cloud requirements, and keep LangSmith optional. Existing tracing can
  transmit data externally when enabled; its handling should remain explicit.
- **Scope:** GuardBench-only repository; unrelated FinSight code was removed.

## Validation gates

For each implementation phase:

1. Add focused regression tests for the changed behavior and migration paths.
2. Run the focused tests, then `.\.venv\Scripts\python.exe -m pytest -q`.
3. Run static/type checks only if already configured or required by the change.
4. Exercise the synthetic runner and inspect generated metadata/report schemas.
5. Test the dashboard against empty data and representative saved result files.
6. Run τ²-bench only when its pinned package, dataset, and local Ollama model
   are available; otherwise report it as unverified, not passed.

The audited baseline was 161 passing tests before implementation. The status
after implementation and final local verification is tracked in
[ACCEPTANCE_MATRIX.md](./ACCEPTANCE_MATRIX.md); do not treat plan completion as
production readiness.

## Implementation update

The first implementation increment now includes:

- Risk levels and a validated content-versioned action policy, plus approval
  expiry and actor/session/policy binding.
- An additive SQLite migration, unique event IDs, structured outcomes, a
  same-database SHA-256 hash chain, and a verifier.
- Public simulator dispatch rejection and explicit routing of τ²-bench
  read-only/mutating calls through the gate; simulated user mutations are
  blocked unless separately approved as assistant actions.
- Validated local judge output, separate human task-quality labels, binary
  agreement statistics, and held-out calibration inputs with a minimum sample
  threshold.
- Synthetic baseline, confirmation-gated, and risk-threshold ablations;
  deterministic adversarial gate checks; per-run metadata and a generated
  reproducibility report.
- CI workflow, metrics/protocol/acceptance documentation, and dashboard
  episode/audit and saved attack-check views.

Not completed by this increment: configurable audit retention and value
minimization, an out-of-database audit checkpoint, multi-seed aggregation,
full attack-category evaluation of model behavior, broad cross-run dashboard
comparison, a real held-out human-label calibration run, actual τ²-bench
execution, authenticated multi-user identities, and production deployment
hardening. These are explicit limitations rather than inferred successes.
