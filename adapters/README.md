# τ²-bench integration boundary

`tau2_adapter.py` targets τ²-bench commit
`05736c27219b769d0be507574dd3135010916644` and preserves the published airline
environment, policy, tool names, simulator, and original outcome evaluator.

`GatedTau2Environment` proxies the benchmark environment and intercepts assistant-side
`Environment.make_tool_call` calls. Tau² tool metadata identifies mutating tools; all
assistant mutations require exact, one-use approvals. Read-only assistant calls and
user-simulator calls preserve the original routing. Successful tool results are
unwrapped before returning them to the benchmark so the original tool response shape is
preserved. Without a locally supplied approval file, mutation attempts are blocked.

Install the pinned dependency with `pip install -r requirements.txt`, then run
`python -m adapters.tau2_adapter`. The default evaluation command is
`python -m evaluation.run_experiments`. The agent, simulated user, semantic
communication evaluator, and NL assertion evaluator use the selected local Ollama model
through LiteLLM. The adapter intentionally does not fall back to tau2's hosted-model
defaults.

The tau2 package does not include benchmark datasets. Check out the matching airline
data at the pinned commit, then set `TAU2_DATA_DIR` to the checkout's `data` directory
before running the adapter. The main README documents the Windows commands.

The adapter records the exact task IDs, model, seed, tau2 version/commit, original
evaluator rewards, latency, and gate audit evidence. Results only qualify as tau2-bench
results after the command actually runs successfully; synthetic experiments and
Promptfoo checks are reported separately.
