# GuardBench

GuardBench is a reproducible, local-first framework for evaluating tool-using LLM agents
under explicit authorization policies. It includes a synthetic airline demo, a fail-closed
tool boundary, security tests, a baseline-versus-gated evaluation pipeline, Promptfoo
red-team prompts, LangSmith tracing, τ²-bench airline evaluation, and a Streamlit
dashboard.

For the complete from-setup-to-evaluation walkthrough, see
[PROJECT_GUIDE.md](./PROJECT_GUIDE.md).

> **Safety and scope:** The built-in airline system is simulated. The default experiment
> runner uses τ²-bench; synthetic fixture runs do not use an LLM or a real airline
> service. Only actual runs of the pinned τ²-bench adapter count as τ²-bench results.
> The benchmark's original policy text and tool names are preserved by the adapter.

## Included features

- State-changing actions, including baggage-claim submissions, are checked at the final
  dispatch boundary. Confirmation is bound to an exact action and canonical JSON
  arguments, logged, and consumed atomically once.
- Unknown actions, malformed arguments, changed arguments, replayed approvals, and
  unapproved external tool calls fail closed.
- Thirty adversarial prompts plus deterministic tests for confirmation spoofing, argument
  tampering, replay, and competing dispatches.
- τ²-bench airline baseline/gated runs using the benchmark's original simulator and
  evaluator, with task rewards, gate metrics, and saved run results.
- Reproducible synthetic baseline/gated runs with a seed, metadata, JSON/CSV/Markdown
  exports, policy-aware success, unauthorized executions, false blocks, latency, and
  confirmation counts.
- Optional Promptfoo checks use a local Ollama model; the Python gate tests remain the
  security oracle because a prompt-only evaluation cannot prove final-boundary enforcement.
- The benchmark's agent, simulated user, semantic communication judge, and natural-language
  assertion judge are configured to use the same local Ollama model.
- LangSmith spans cover agent/LLM calls, tool dispatch, gate decisions, and benchmark
  runs. Trace inputs/outputs redact prompt text, arguments, booking/payment identifiers,
  and error strings.

## Windows setup (local models only)

Prerequisites: Python 3.12, Node.js/npm (Promptfoo only), and Ollama. No paid model API
is used by these commands.

```powershell
cd C:\path\to\guardrailed_action_agent
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
ollama pull qwen2.5:3b
python scripts\check_setup.py
python -m pytest -q
```

If PowerShell blocks virtual-environment activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

If installation of τ²-bench's LiteLLM dependency fails with a Windows path-length error,
create the virtual environment in a shorter location and install there:

```powershell
py -3.12 -m venv "$env:LOCALAPPDATA\venvs\guardbench"
& "$env:LOCALAPPDATA\venvs\guardbench\Scripts\Activate.ps1"
python -m pip install -r requirements.txt
```

The model defaults to `qwen2.5:3b`. Set `OLLAMA_MODEL` and `OLLAMA_BASE_URL` to use
another model hosted by your local Ollama server. `GUARDBENCH_CONFIG` can point to a
different JSON settings file; `AUDIT_DB_PATH` overrides the SQLite audit path.

## Run the project

### Interactive synthetic demo

```powershell
python -m app.demo
```

Mutating actions display the exact arguments and require the human operator to type
`yes`. This demo never connects to airline services.
The demo can search flights by origin and destination or modify an existing synthetic
booking; booking a new flight and searching by date or passenger count are not supported.
For rebooking, use a known synthetic booking ID (`DEMO-100` or `DEMO-200`) and a flight
ID. The demo checks the booking ID before asking for confirmation.

### Security suite and default evaluation

```powershell
python -m pytest -q
python -m guardrails.confirmation_gate --db logs\audit.db
python -m evaluation.run_experiments --split base --limit 2 --seed 17
```

The default evaluation uses τ²-bench's airline tasks and original evaluator. Both an
ungated baseline and a gated run are executed; the dashboard displays results saved under
`data\tau2_runs`. Ensure Ollama is running and the configured model is available. Without
an approval file, assistant state-changing tool calls in gated runs are blocked.

To run the deterministic synthetic fixtures instead:

```powershell
python -m evaluation.run_experiments --benchmark synthetic --episodes 32 --seed 17
python -m evaluation.report --input data\episodes --output data\reports\latest.json
```

Each experiment writes run metadata and per-episode JSON under `data\episodes`, plus
JSON, CSV, and Markdown summaries under `data\reports`. Metadata records the seed,
Python/platform, configured model, repository revision when available, and whether
tracing was enabled. Synthetic fixture runs report `model_used: null` and zero API cost
because they do not call an LLM. The success metric is policy-aware: an unauthorized
sensitive action is expected to be blocked; an authorized one is expected to execute.

### Generate and run the Promptfoo suite

```powershell
python -m evaluation.generate_adversarial
npm install
npm run eval:promptfoo
```

Promptfoo sends the thirty adversarial messages to the configured local Ollama model
and checks output shape. It evaluates prompt robustness only; `python -m pytest -q`
tests the actual authorization boundary. No remote Promptfoo provider is configured.

### LangSmith observability

Tracing is enabled in `config.json`. If your LangSmith workspace shows agents and
environments (for example, the **Local** agent view), set the agent ID and environment
along with the API key in the same PowerShell session used to start the app:

```powershell
$env:LANGSMITH_API_KEY = "<your-new-key>"
$env:LANGSMITH_AGENT_ID = "<agent-id-from-langsmith>"
$env:LANGSMITH_AGENT_ENVIRONMENT = "local"
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

Use the exact agent ID shown in LangSmith's agent overview or URL; it may differ from
the displayed agent name. The app routes traces either to this agent/environment or, if
both agent variables are unset, to the project configured as `langsmith_project`.
It never sets both destinations on the same trace.

In PowerShell, use `$env:NAME = "value"` syntax; the `export NAME=value` example used in
some LangSmith setup guides is for Unix shells. `LANGSMITH_TRACING=true` can also be set
in the environment to override the config setting. LangSmith is an observability service;
enabling it sends trace metadata to the configured LangSmith endpoint. Prompts, tool
arguments, and common booking/payment identifiers are redacted, but review data-handling
requirements before using non-synthetic data. Set `LANGSMITH_ENDPOINT` for a self-hosted
deployment. Ollama inference remains local; no `OPENAI_API_KEY` is required.

### τ²-bench evaluation

The adapter is pinned to τ²-bench commit
[`05736c2`](https://github.com/sierra-research/tau2-bench/commit/05736c27219b769d0be507574dd3135010916644).
It preserves the benchmark's airline policy and tool names and routes all mutating
assistant calls through the gate at `Environment.make_tool_call`; read-only calls are
also audit-routed, and mutating simulated-user calls are blocked. It runs both an
ungated research baseline and a gated run through τ²-bench's original simulation evaluator.

The pinned τ²-bench dependency is included in the standard installation. To run the
benchmark directly:

```powershell
pip install -r requirements.txt
git clone --filter=blob:none --no-checkout https://github.com/sierra-research/tau2-bench.git C:\venvs\tau2-bench-data
Set-Location C:\venvs\tau2-bench-data
git sparse-checkout init --cone
git sparse-checkout set data/tau2/domains/airline data/tau2/multilingual/en
git checkout --detach 05736c27219b769d0be507574dd3135010916644
Set-Location C:\path\to\guardrailed_action_agent
$env:TAU2_DATA_DIR = "C:\venvs\tau2-bench-data\data"
ollama pull qwen2.5:3b
python -m evaluation.run_experiments --split base --limit 2 --seed 17 --model qwen2.5:3b
```

The dataset checkout is pinned to the same τ²-bench commit as the Python dependency.
It includes the airline fixtures and the English language pack used by default.
`TAU2_DATA_DIR` must point to its `data` folder, and must be set in the shell before
starting the benchmark.

The direct adapter command `python -m adapters.tau2_adapter` remains available for
advanced options. `requirements-tau2.txt` is retained as a compatibility alias for the
standard requirements file.

The agent, simulated customer, and τ² semantic/NL evaluators are explicitly directed to
Ollama through LiteLLM; the adapter does not use the paid provider defaults. No explicit
approval file means every mutating assistant tool call is blocked. To authorize an exact
tool invocation in a controlled experiment, create a local JSON file such as:

```json
{
  "approvals": [
    {
      "tool_name": "cancel_reservation",
      "arguments": {"reservation_id": "ZFA04Y"},
      "confirmation": "yes"
    }
  ]
}
```

Then pass `--approval-file data\approvals.json`. Entries are exact, local, one-use
approvals; simulated customer text, model output, urgency, and claimed prior approval
never grant authorization. Benchmark outputs include the task IDs, model, seed,
τ²-bench commit/version, original evaluator reward, gate audit events, and summary
metrics under `data\tau2_runs`. Run more than one task and seed before drawing
comparative conclusions.

### Streamlit app and local judge

```powershell
streamlit run dashboard.py
python -m evaluation.make_label_template
python -m evaluation.score_judge
```

The Streamlit app includes an interactive synthetic airline agent and the evaluation
dashboard. In the interactive tab, chat with the local Ollama-backed agent; state-changing
actions display their exact arguments and wait for approval or denial before dispatch.
The evaluation tab reads saved episodes and shows outcome/security metrics and latency.
`score_judge` uses the configured local Ollama model; human-label agreement is meaningful
only after `data\human_labels.csv` has been completed.

### Risk policy, ablations, and human evaluation

`guardrails.action_policy.ActionPolicy` defines explicit LOW/MEDIUM/HIGH/CRITICAL
risk levels and per-action approval requirements. Policy mappings can be created
through `ActionPolicy.from_mapping(...)`; each mapping receives a deterministic
content-derived policy version. Approval proposals are bound to exact canonical
arguments, actor/session labels, policy version, and expiry. The CLI creates a
per-process session ID and the Streamlit app creates a per-browser-session ID.
The default approval lifetime is five minutes; the UI shows expiry and policy
context before approval.

Run the reproducible synthetic ablation:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_experiments --benchmark synthetic --episodes 32 --seed 17 --output data\ablations
```

The `baseline`, `gated`, and `risk_aware` policies all pass through the trusted
dispatch boundary; the baseline intentionally disables approvals only as a
research treatment. The risk-aware treatment requires approval for HIGH and
CRITICAL actions; it is not a recommended policy. Every run records its
hypothesis and metrics before running, writes deterministic authorization
ground truth separately from optional human labels and judge predictions, and
generates a reproducibility report under `data\ablations\reports`.

To create distinct evaluation and calibration labels:

```powershell
.\.venv\Scripts\python.exe -m evaluation.make_label_template --input data\episodes --output data\human_labels.csv --split evaluation
.\.venv\Scripts\python.exe -m evaluation.make_label_template --input data\calibration_episodes --output data\calibration_labels.csv --split calibration
.\.venv\Scripts\python.exe -m evaluation.score_judge --input data\episodes --labels data\human_labels.csv --calibration-input data\calibration_episodes --calibration-labels data\calibration_labels.csv
```

Review [METRICS.md](./docs/METRICS.md), [EXPERIMENT_PROTOCOL.md](./docs/EXPERIMENT_PROTOCOL.md),
and [THREAT_MODEL.md](./docs/THREAT_MODEL.md) before interpreting results. The
synthetic fixed fixture set is not a substitute for independent benchmark tasks or
human-reviewed model quality.

### CI and validation

The free GitHub Actions workflow installs the project's local Python requirements,
compiles Python sources, runs Ruff's critical-error checks, and runs deterministic
tests. It does not install tau2-bench data, contact Ollama, or use a paid inference
service. Run the same local test suite with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

See [ACCEPTANCE_MATRIX.md](./docs/ACCEPTANCE_MATRIX.md) for the implemented,
tested, experimentally validated, and not-production-ready distinctions.

## Cost and limitations

- Ollama model inference is local. LangSmith is optional and requires an account or a
  self-hosted endpoint; no paid model is used.
- Promptfoo is open source and configured to use only Ollama.
- The built-in deterministic suite is a pipeline/security smoke test, not model
  performance evidence.
- τ²-bench requires downloading its published benchmark package/data. Its original
  evaluator may use local semantic judging configured by the adapter. Verify Ollama is
  reachable and the model is pulled before starting.
- No real-world airline service or external customer data is connected.
- The SQLite hash chain has no separately stored checkpoint; an attacker able to
  rewrite the whole database can recompute it. Sensitive argument/result values
  remain in audit storage, so use synthetic data.
- Local actor IDs are labels, not authenticated identities. The app is not a
  production multi-user authorization service.
- The synthetic ablation is small, deterministic, and correlated by fixture
  repetition; it does not certify model quality or establish zero risk.
