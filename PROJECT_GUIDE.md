# GuardBench: Complete Project Guide

This guide explains GuardBench from setup through evaluation. It is written for someone
opening the project for the first time and describes what the code currently does, how its
parts connect, how to run it on Windows, and what conclusions its results do and do not
support.

For the short project overview, use [README.md](./README.md). This document is the longer
walkthrough.

## 1. What GuardBench is

GuardBench is a local-first demonstration and evaluation framework for tool-using LLM
agents. Its central question is:

> Can an agent use tools to complete tasks while a trusted authorization boundary blocks
> state-changing calls that have not been explicitly approved?

The project combines:

- A local Ollama model that turns a user's message into a structured action proposal.
- A simulated airline tool environment.
- A final-dispatch confirmation gate, separate from the model.
- A Streamlit app containing an interactive demo and an evaluation dashboard.
- Deterministic security tests and a τ²-bench baseline-versus-gated evaluation runner,
  with synthetic fixtures available as a separate mode.
- Optional Promptfoo adversarial prompt checks.
- Optional LangSmith tracing.
- A pinned τ²-bench adapter for the published airline benchmark.

The built-in airline data is fake. No real airline, booking provider, or payment service is
connected. The model is configured to run locally through Ollama; LangSmith is an optional
external observability destination, not an inference provider.

## 2. The key design principle

The model is not the security authority. It can suggest an action, but the trusted Python
gate decides whether a state-changing tool call can reach the simulator.

For example, a model response such as “the customer already approved” does not count as
approval. To run a sensitive action, the app must:

1. Validate the action name and arguments.
2. Create a proposal for the exact action and arguments.
3. Show that exact proposal to the human operator.
4. Receive the explicit confirmation `yes`.
5. Pass the matching proposal ID to the gate for dispatch.
6. Let the gate consume the approval once before calling the tool.

Changing the action, changing any argument, omitting approval, or reusing an approval
blocks the call. These checks happen at the final dispatch boundary; model instructions
alone do not enforce them.

## 3. What you can do in the current demo

### Supported tool actions

The simulated environment supports:

| Action | Purpose | Confirmation |
|---|---|---|
| `get_booking` | Read a synthetic booking | No |
| `search_flights` | Show sample flight details for an origin and destination | No |
| `rebook_flight` | Change the flight on an existing synthetic booking | Yes |
| `cancel_booking` | Cancel an existing synthetic booking | Yes |
| `issue_refund` | Record a simulated refund | Yes |
| `grant_compensation` | Record simulated compensation | Yes |
| `change_payment_method` | Simulate a payment-method update using four digits | Yes |
| `baggage_claim` | Submit a simulated baggage claim | Yes |

The sample booking IDs are `DEMO-100` and `DEMO-200`. Sample search results include
`AB701` and `AB702`.

### Not supported

This is not an airline booking application. It cannot:

- Book a new flight.
- Check real availability or quote fares.
- Search by departure date or passenger count.
- Reach real airline or payment systems.

Flight search returns fixed sample details, not live availability or prices. A rebooking
changes only the in-memory synthetic booking after exact confirmation.

## 4. Request flow: from message to tool result

The interactive flow is:

```text
User message
    |
    v
Streamlit UI or CLI demo
    |
    v
ActionAgent
    |  Sends prompt to local Ollama and parses structured JSON
    |  Rejects unsupported actions/arguments and unknown demo booking IDs
    v
ConfirmationGate.propose()
    |  Validates allow-listed action and strict argument schema
    |  Stores a pending proposal and action/argument fingerprint
    v
Human reviews exact proposal
    |  Sensitive action: approve or deny
    |  Read-only action: no confirmation needed
    v
ConfirmationGate.execute()
    |  Re-checks action, arguments, proposal status, and single-use approval
    |  Writes audit event
    v
SimulatedAirlineTools.dispatch()
    |
    v
Result is shown in the UI
```

The agent receives the known synthetic booking IDs as context. It does not maintain
general conversation memory: a previous message is not, by itself, trusted authorization
or durable booking state.

## 5. Security gate details

The main policy is in [guardrails/action_policy.py](./guardrails/action_policy.py), and
the enforcement boundary is in
[guardrails/confirmation_gate.py](./guardrails/confirmation_gate.py).

The gate:

- Allow-lists known action names.
- Checks required and allowed argument fields for each action.
- Rejects malformed, non-finite, or oversized JSON arguments.
- Canonicalizes JSON so argument ordering cannot change the meaning of an approval.
- Fingerprints the action together with its exact arguments.
- Requires approval for every state-changing action.
- Stores proposal state in SQLite.
- Uses a transaction when consuming an approval, preventing two competing dispatches
  from using the same approval.
- Blocks missing, mismatched, denied, pending, expired-by-state, or already consumed
  approvals.
- Records proposals, confirmations, blocks, executions, and results in an audit log.

The demo stores that local audit data at the configured `audit_db` path, which defaults
to `logs/audit.db`. Audit records include action arguments and tool results. Do not treat
this local audit database as redacted storage or put real customer data in the demo.

### What the security tests prove

The deterministic tests exercise the Python boundary directly. They cover missing
confirmation, invalid arguments, unknown actions, argument tampering, replay, concurrent
dispatches, adversarial text, and the sensitive baggage-claim action.

These tests are the security oracle for this project. Prompt-only model checks cannot
prove that an external tool dispatcher enforces authorization.

## 6. Project layout

| Path | Responsibility |
|---|---|
| `app/action_agent.py` | Prompt, Ollama-backed action selection, response validation, unsupported-request handling |
| `app/ollama_client.py` | HTTP client for the local Ollama chat API |
| `app/airline_tools.py` | Fake airline records and simulated tool implementations |
| `app/gated_tools.py` | Routes simulated tool dispatch through the confirmation gate |
| `app/demo.py` | Interactive terminal demo |
| `app/settings.py` | Reads JSON settings and environment-variable overrides |
| `app/observability.py` | Optional LangSmith instrumentation, destination selection, trace redaction |
| `guardrails/action_policy.py` | Allow-listed action names and state-changing action classification |
| `guardrails/confirmation_gate.py` | Schema validation, proposals, approvals, atomic execution, SQLite audit log |
| `dashboard.py` | Streamlit interactive demo and evaluation dashboard |
| `evaluation/run_experiments.py` | Default τ²-bench baseline/gated runner and explicit synthetic fixture runner |
| `evaluation/report.py` | Aggregates saved episodes into metrics and JSON reports |
| `evaluation/episodes.py` | Saves and loads per-episode JSON files |
| `evaluation/adversarial_cases.py` | Thirty adversarial prompt examples |
| `evaluation/generate_adversarial.py` | Writes Promptfoo-compatible adversarial cases |
| `promptfooconfig.yaml` | Local Ollama Promptfoo configuration and output-shape assertions |
| `judge/` | Local-model evaluation rubric and LLM judge |
| `adapters/tau2_adapter.py` | τ²-bench airline environment adapter |
| `tests/` | Gate, agent, adapter, and tracing destination tests |
| `scripts/check_setup.py` | Checks Python, Git, Ollama service, and local model list |
| `config.json` | Default model, audit database, LangSmith tracing and project settings |
| `requirements.txt` | Standard application and pinned τ²-bench dependencies |
| `requirements-tau2.txt` | Compatibility alias for the standard requirements |
| `package.json` | Node/npm script for the optional Promptfoo evaluation |
| `data/` | Example inputs and generated experiment data |
| `logs/` | Local audit database output |

Generated episode/report data and local secrets are ignored by `.gitignore`. The project
does not automatically load `.env` files; it reads environment variables directly.

## 7. Windows setup

### Prerequisites

- Python 3.12.
- Ollama for Windows.
- The local model used by the default config (`qwen2.5:3b`).
- Node.js/npm only if you want to run Promptfoo.

### Install the standard project

Open PowerShell:

```powershell
cd "C:\Users\AIGow\Downloads\guardrailed_action_agent_full_project\guardrailed_action_agent"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
ollama pull qwen2.5:3b
python scripts\check_setup.py
```

If the virtual environment already exists, activate it rather than creating it again:

```powershell
.\.venv\Scripts\Activate.ps1
```

If installation of τ²-bench's LiteLLM dependency fails with a Windows path-length
error, create the virtual environment in a shorter location and install there:

```powershell
py -3.12 -m venv "$env:LOCALAPPDATA\venvs\guardbench"
& "$env:LOCALAPPDATA\venvs\guardbench\Scripts\Activate.ps1"
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, the project README shows a process-scoped execution
policy workaround. Alternatively, use the virtual-environment Python explicitly in
commands, for example:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The Ollama desktop app/service must be running. `scripts\check_setup.py` checks whether
the local API responds and prints model names; it does not install Ollama for you.

## 8. Run the Streamlit application

From the project directory, with Ollama running:

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

Open the local address Streamlit prints, normally `http://localhost:8501`.

The app has two tabs:

### Interactive airline demo

Use the chat box to try requests such as:

- `Show booking DEMO-100`
- `Search flights from Chennai to Delhi`
- `Rebook DEMO-100 to AB702`
- `Cancel booking DEMO-100`

For a state-changing action, inspect the displayed action and arguments. Approve only
when both are exactly what you intend. Denial does not dispatch the action.

The booking simulator is in memory. Its state is shared while the current app session
is running and resets when the process is restarted. The SQLite audit log persists
separately.

### Evaluation dashboard

The dashboard displays saved τ²-bench task results from `data/tau2_runs` and, in an
expanded section, synthetic per-episode results from `data/episodes`.

If there are no τ²-bench results yet, run the default evaluation command in the next
section.

## 9. Run the tests and evaluations

### Test the project

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The test suite is deterministic and does not require a paid model API. Adapter behavior
is tested with test doubles; a real benchmark run requires Ollama and the local model.

### Run the default τ²-bench evaluation

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_experiments --split base --limit 2 --seed 17
```

The runner executes both baseline and gated modes using τ²-bench's airline tasks and
original evaluator. Results are written under `data/tau2_runs` and can be viewed in the
Evaluation dashboard. Ollama and the configured local model must be available.

### Run reproducible synthetic fixtures

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_experiments `
  --benchmark synthetic `
  --episodes 32 `
  --seed 17
```

This mode creates deterministic simulated tasks, runs baseline and gated modes, and
saves episodes, audit databases, metadata, and reports.

The runner produces data under:

- `data/episodes/` — one JSON record per mode and episode.
- `data/reports/` — JSON, CSV, and Markdown summary reports.
- `data/` — run metadata and audit databases.

To build a report from saved episodes:

```powershell
.\.venv\Scripts\python.exe -m evaluation.report `
  --input data\episodes `
  --output data\reports\latest.json
```

Metrics include task success, policy compliance, unauthorized executions, false blocks,
mean/p50/p95 latency, and confirmation counts. Read the run metadata for the seed,
platform, model configuration, and benchmark designation.

**Interpretation warning:** synthetic fixtures do not involve an LLM performing tasks.
They are useful for validating the pipeline and comparing gate semantics in controlled
cases, but are not evidence of model quality or τ²-bench performance.

### Complete testing catalogue

Use the layers below from fastest to most realistic. They answer different questions;
passing one layer does not prove the others.

#### A. Check local prerequisites

```powershell
.\.venv\Scripts\python.exe scripts\check_setup.py
```

This checks the Python version, Git/Ollama CLI availability, whether the local Ollama
API responds, and which models Ollama reports. It does not run the agent or prove that
LangSmith credentials work.

#### B. Discover and run automated tests

List the tests pytest discovers:

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q
```

Run the complete test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Run a focused group while iterating:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_gate.py tests\test_adversarial_gate.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_action_agent.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_observability.py -q
.\.venv\Scripts\python.exe -m pytest tests\test_tau2_adapter.py -q
```

What those groups cover:

- `test_gate.py`: missing approval, exact one-time approval, claimed prior approval,
  argument changes, unknown actions, and audit ordering.
- `test_adversarial_gate.py`: 30 adversarial-pressure cases, approval replay/tampering,
  baggage-claim confirmation, invalid arguments, concurrent replay, and audit order.
- `test_action_agent.py`: expected output handling, unsupported booking/pricing requests,
  invalid model arguments, and known versus unknown synthetic booking IDs. Most tests
  use a fake model response so they are fast and deterministic.
- `test_observability.py`: routing to a LangSmith agent/environment versus a project,
  and rejecting a partially configured agent destination.
- `test_tau2_adapter.py`: adapter routing and gate behavior using test doubles; this is
  not the same as running the actual τ²-bench package and task set.

#### C. Run a deterministic synthetic evaluation check

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_experiments `
  --benchmark synthetic `
  --episodes 8 `
  --seed 17
```

This is the quickest full evaluation-pipeline smoke test. Confirm that it finishes,
prints baseline and gated episodes, and writes metadata, per-episode JSON, audit
databases, and JSON/CSV/Markdown reports. It makes no model inference calls. Use a
separate output directory if you want to keep this smoke run separate from earlier
results:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_experiments `
  --benchmark synthetic `
  --episodes 8 `
  --seed 17 `
  --output data\test-smoke
```

For a more stable synthetic comparison, use more episodes and repeat with different
seeds. Keep the seed and metadata with any result you share. Do not call these LLM
performance or τ²-bench results.

#### D. Test the local Ollama connection and model

Make sure Ollama is running and the configured model is installed:

```powershell
ollama list
ollama pull qwen2.5:3b
.\.venv\Scripts\python.exe scripts\check_setup.py
```

Then run the terminal agent:

```powershell
.\.venv\Scripts\python.exe -m app.demo
```

Try both safe and blocked/unsupported requests:

1. `Search flights from Chennai to Delhi` — expect sample flights, with no fares or live
   availability.
2. `Price of flight` — expect a clear unsupported-pricing response.
3. `Book a flight` — expect a new-booking-not-supported response.
4. `Show booking DEMO-100` — expect a read-only synthetic record.
5. `Rebook DEMO-100 to AB702` — inspect the exact proposal; deny it, then repeat and
   approve only if the displayed booking and flight IDs are correct.
6. Try an unknown booking ID — it should be rejected before approval.
7. Type `quit` to exit.

This exercises the real local model and terminal flow, but is manual and may vary with
model output. Always inspect proposed arguments; never approve a proposal just because
the model says it is correct.

#### E. Test the complete Streamlit experience

Start the application:

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

In the **Interactive airline demo** tab, repeat the local-model cases above. Verify that
state-changing actions show an exact proposal with separate **Approve** and **Deny**
controls. Try denial first and confirm no simulated change is reported. Then use an
appropriate synthetic booking to test an approved action.

In **Evaluation dashboard**, verify that a saved run can be selected and its episodes,
metrics, latency, and failure categories appear. If no episodes are listed, first run
the deterministic experiment command in section 9.

The interactive UI uses a simulated airline and does not test real airline integrations.

#### F. Test prompt robustness with Promptfoo

```powershell
.\.venv\Scripts\python.exe -m evaluation.generate_adversarial
npm install
npm run eval:promptfoo
```

This runs the adversarial messages against local Ollama and checks response JSON shape.
Review the Promptfoo output for failed cases. This tests model/prompt behavior only;
Promptfoo does not call the final authorization gate and is not proof that a real tool
dispatch is protected.

#### G. Test LangSmith trace delivery

Start Streamlit from a shell where tracing, a valid API key, and exactly one destination
are configured. See section 11 for secure PowerShell setup. Then:

1. Check the Streamlit sidebar: tracing enabled, key configured, and the intended
   project or agent/environment shown.
2. Send a fresh message in the interactive tab to create a trace.
3. Open the same destination shown in the sidebar in LangSmith and refresh.
4. Inspect parent/child runs for the agent, model call, gate, and tool dispatch.
5. Test one read-only request and one state-changing request; approval events should
   only appear for the latter.

This validates observability delivery, not correctness of the authorization policy.
Never share API keys or use real customer data for this test.

#### H. Test the local-model judge and human-label agreement

First generate a deterministic episode set. Then create and complete human labels:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_experiments --benchmark synthetic --episodes 8 --seed 17
.\.venv\Scripts\python.exe -m evaluation.make_label_template
```

Fill `data/human_labels.csv` with explicit `true`/`false` labels where appropriate, then:

```powershell
.\.venv\Scripts\python.exe -m evaluation.score_judge
```

This invokes the configured local Ollama model for each saved episode and writes judge
verdict and agreement files under `reports/`. It can take time and consumes local model
resources. The judge is not ground truth; compare its labels to human review.

#### I. Run the default τ²-bench integration

After installing the standard requirements and verifying local Ollama, run a small task
sample:

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
.\.venv\Scripts\python.exe -m evaluation.run_experiments `
  --split base `
  --limit 2 `
  --seed 17 `
  --model qwen2.5:3b
```

Without an approval fixture, gated mutations should be blocked. To test exact approval
matching, create a local fixture based on `data/approvals.example.json` and pass it with
`--approval-file data\approvals.json`. Use synthetic benchmark data and review the task
arguments before adding an approval. Compare baseline and gated task rewards, blocks,
unauthorized executions, confirmations, and latency in the output under
`data/tau2_runs`.

The τ²-bench package does not bundle its dataset. The checkout above downloads the
airline fixtures and default English language pack at the same pinned commit;
`TAU2_DATA_DIR` must point to the checkout's `data` folder before starting Python.

The default evaluation command produces τ²-bench results only when the actual benchmark
tasks and original evaluator complete successfully. Start with a small sample before
increasing the task limit. The direct adapter command remains available for advanced
options.

#### J. Suggested testing sequence

For a full confidence pass, run:

```powershell
.\.venv\Scripts\python.exe scripts\check_setup.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m evaluation.run_experiments --benchmark synthetic --episodes 8 --seed 17
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

Then manually verify the demo, run Promptfoo if desired, verify LangSmith delivery if
configured, and run the default τ²-bench evaluation when Ollama is available. Keep
synthetic, prompt-robustness, judge, and benchmark outputs clearly separated when
reporting results.

## 10. Promptfoo adversarial checks

Promptfoo is an optional open-source prompt robustness tool. It uses the local Ollama
provider in `promptfooconfig.yaml`.

Generate the adversarial input file and run Promptfoo:

```powershell
.\.venv\Scripts\python.exe -m evaluation.generate_adversarial
npm install
npm run eval:promptfoo
```

The current Promptfoo assertions check that model responses have the expected JSON
shape. They send adversarial text to the model; they do not call or prove the Python
confirmation gate. Use the Python tests to validate authorization enforcement.

## 11. LangSmith tracing

The default `config.json` enables tracing. The app sends traces only when a valid
LangSmith API key is available in the environment of the Python process running
Streamlit.

This app supports two trace destinations:

- **Agent/environment**: set both `LANGSMITH_AGENT_ID` and
  `LANGSMITH_AGENT_ENVIRONMENT`. Use the exact agent ID from LangSmith, not just its
  display name.
- **Project**: leave both agent variables unset. The project defaults to
  `guardbench-local`, configurable by `LANGSMITH_PROJECT`.

A trace goes to one destination or the other, not both. The Streamlit sidebar reports
whether tracing is enabled, whether a key is configured, and which destination the
process will use. It never displays the key.

### Start Streamlit with agent/environment tracing in PowerShell

Start in the project directory. Enter a newly generated key when prompted; do not paste
keys into source files, screenshots, or chat.

```powershell
$secureKey = Read-Host "LangSmith API key" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $env:LANGSMITH_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
}

$env:LANGSMITH_TRACING = "true"
$env:LANGSMITH_ENDPOINT = "https://api.smith.langchain.com"
$env:LANGSMITH_AGENT_ID = "<exact-agent-id>"
$env:LANGSMITH_AGENT_ENVIRONMENT = "local"

.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

For project tracing instead, remove or unset both agent variables and set:

```powershell
$env:LANGSMITH_PROJECT = "guardbench-local"
```

Set environment variables in the same PowerShell session before launching Streamlit.
Changing a shell variable does not update an already-running Streamlit process; stop and
restart the server after changing configuration. Send a message in the interactive demo
to generate traces.

### What gets sent

The tracing wrapper instruments agent, LLM, tool, gate, and benchmark functions. It
applies key-based redaction to trace input/output dictionaries. LangSmith is a separate
service, so trace data is sent to its configured endpoint when tracing is enabled.

Redaction is not a substitute for data minimization. The local SQLite audit database
stores action arguments and results, and not every possible nested value is guaranteed
to be redacted by the trace processor. Use synthetic data only unless you have reviewed
and approved the data-handling implications.

Ollama inference remains local. No OpenAI API key is required.

## 12. τ²-bench integration

The adapter is in `adapters/tau2_adapter.py`. It targets the pinned τ²-bench
commit listed in `requirements.txt`, wraps the airline environment, preserves its
policy/tool definitions, and intercepts assistant-side mutating tool calls. It uses
τ²-bench's original simulation evaluator for task outcomes.

Install the standard dependencies and run a small sample:

```powershell
pip install -r requirements.txt
ollama pull qwen2.5:3b
.\.venv\Scripts\python.exe -m evaluation.run_experiments `
  --split base `
  --limit 2 `
  --seed 17 `
  --model qwen2.5:3b
```

The agent, simulated user, and natural-language/semantic evaluators are directed to the
local Ollama model through LiteLLM. The adapter intentionally avoids τ²-bench's hosted
model defaults.

Without an approval file, state-changing assistant calls are blocked. An approval file
is a local experimental fixture authorizing exact tool names and argument objects; it
is not a production human approval mechanism. See
[`data/approvals.example.json`](./data/approvals.example.json) for its format. The
adapter saves task IDs, model, seed, evaluator reward, latency, gate events, and summary
metrics under `data/tau2_runs`.

The adapter's existence is not a benchmark result. Only a successful run against the
actual τ²-bench tasks and evaluator qualifies as τ²-bench data. Clearly distinguish
those runs from synthetic experiments and Promptfoo checks.

## 13. Optional local-model judge and human labels

The project includes a JSON-output LLM judge that uses the configured Ollama model:

```powershell
.\.venv\Scripts\python.exe -m evaluation.make_label_template
```

Fill in `data/human_labels.csv`, then run:

```powershell
.\.venv\Scripts\python.exe -m evaluation.score_judge
```

The command writes judge verdicts and agreement statistics under `reports/`. Agreement
uses only rows with explicit `true` or `false` human labels; blanks and unknown labels
are excluded. A model judge is an aid for analysis, not ground truth.

## 14. Configuration reference

`config.json` contains non-secret defaults:

| Setting | Meaning |
|---|---|
| `ollama_base_url` | Local Ollama HTTP API base URL |
| `ollama_model` | Local model tag |
| `audit_db` | SQLite gate audit database path |
| `langsmith_tracing` | Enables/disables the tracing wrapper unless overridden by environment |
| `langsmith_project` | Project destination used when agent variables are unset |

Environment variables override relevant defaults:

- `OLLAMA_BASE_URL`
- `OLLAMA_MODEL`
- `AUDIT_DB_PATH`
- `GUARDBENCH_CONFIG`
- `LANGSMITH_TRACING`
- `LANGSMITH_API_KEY`
- `LANGSMITH_ENDPOINT`
- `LANGSMITH_PROJECT`
- `LANGSMITH_AGENT_ID`
- `LANGSMITH_AGENT_ENVIRONMENT`

The project does not automatically read a `.env` file. Do not put API keys in
`config.json`; use environment variables or a secret manager.

## 15. Troubleshooting

### Ollama is unreachable

Open the Ollama desktop app and verify:

```powershell
.\.venv\Scripts\python.exe scripts\check_setup.py
ollama list
```

If needed, pull the configured model with `ollama pull qwen2.5:3b`.

### The model returns unsupported fields

The agent validates the model's structured decision before dispatch. Use supported
fields only; for example, `search_flights` accepts `origin` and `destination`, not
departure date or passenger count. Unsupported proposals should be declined rather than
approved.

### No LangSmith traces appear

1. Check the Streamlit sidebar for **Tracing: enabled**, **API key: configured**, and
   the expected destination.
2. Make sure the API key is available in the same shell session that launched
   Streamlit.
3. Stop and restart Streamlit after changing environment variables.
4. Send a new message in the interactive demo.
5. In LangSmith, open the destination shown in the sidebar: the selected agent and
   environment, or the configured tracing project.
6. Confirm the endpoint matches your LangSmith region/workspace.
7. Never share the API key; rotate it if it was exposed.

### The evaluation tab has no data

Run `python -m evaluation.run_experiments` for the default τ²-bench evaluation, or add
`--benchmark synthetic` to generate synthetic episodes, then refresh the dashboard.

### An action was denied or blocked

Check the exact action/arguments, make sure the booking ID exists, and approve the
specific proposal only if it is correct. A previous approval, a model claim, or an
approval for different arguments is not reusable.

## 16. Limitations and responsible use

- This project is a demonstration and research scaffold, not a production airline
  system.
- Synthetic data and tools have no external side effects.
- Synthetic fixture evaluations are deterministic and do not measure LLM performance.
- Promptfoo evaluates prompt robustness and output shape, not the trusted gate itself.
- τ²-bench benchmark claims require actual task runs and successful completion of its
  original evaluator.
- LangSmith tracing sends trace data externally when enabled. Review and minimize data
  before using any non-synthetic inputs.
- The SQLite audit log stores arguments and results locally; protect or remove it
  according to your local data-handling needs.

## 17. Suggested end-to-end learning path

1. Read this guide's request-flow and security sections.
2. Set up Python and Ollama, then run `scripts/check_setup.py`.
3. Start the Streamlit app and try a read-only booking lookup or flight search.
4. Try a state-changing request and inspect the confirmation before approving or denying.
5. Run `pytest` and inspect the security tests.
6. Run the default τ²-bench evaluation, then view its results in Streamlit.
7. Enable LangSmith and inspect a trace for an interactive request.
8. Run Promptfoo to explore adversarial prompt behavior, remembering that the Python gate
   tests are the authorization oracle.
9. Repeat τ²-bench runs with documented model, task, and seed metadata.
