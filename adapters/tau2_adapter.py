import json
import random
import time
import uuid
from pathlib import Path

from app.observability import traced
from guardrails.confirmation_gate import ConfirmationGate


class GatedTau2Environment:
    """Proxy tau2's environment without changing its tools or policy text."""

    def __init__(
        self,
        environment,
        gate,
        approve_proposal=None,
        actor_id="tau2-agent",
        session_id="tau2-local",
    ):
        self._environment = environment
        self._gate = gate
        self._approve_proposal = approve_proposal
        self._actor_id = actor_id
        self._session_id = session_id

    def __getattr__(self, name):
        return getattr(self._environment, name)

    @traced(run_type="tool")
    def make_tool_call(self, tool_name, requestor="assistant", **kwargs):
        actor_id = f"{self._actor_id}:{requestor}"
        call_tool = lambda arguments: self._environment.make_tool_call(
            tool_name,
            requestor=requestor,
            **arguments,
        )
        if not self._environment._is_mutating_tool(tool_name):
            result = self._gate.execute_external_readonly(
                tool_name,
                kwargs,
                call_tool,
                actor_id=actor_id,
                session_id=self._session_id,
            )
            if result.get("status") == "executed":
                return result["result"]
            return result
        proposal = self._gate.propose_external(
            tool_name,
            kwargs,
            actor_id=actor_id,
            session_id=self._session_id,
        )
        approval_id = None
        if (
            requestor == "assistant"
            and self._approve_proposal
            and self._approve_proposal(proposal)
        ):
            if self._gate.approve(
                proposal["proposal_id"],
                "yes",
                channel="trusted_approval_file",
                actor_id=actor_id,
                session_id=self._session_id,
            ):
                approval_id = proposal["proposal_id"]

        result = self._gate.execute_external(
            tool_name,
            kwargs,
            call_tool,
            approval_id,
            actor_id=actor_id,
            session_id=self._session_id,
        )
        if result.get("status") == "executed":
            return result["result"]
        return result


class PreapprovedActions:
    """Consume one-time approvals explicitly supplied in a local JSON fixture."""

    def __init__(self, path):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise RuntimeError(f"Unable to read approval fixture: {path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in approval fixture: {path}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("approvals"), list):
            raise ValueError("Approval fixture must contain an approvals array")
        for index, entry in enumerate(data["approvals"]):
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("tool_name"), str)
                or not isinstance(entry.get("arguments"), dict)
                or entry.get("confirmation") != "yes"
            ):
                raise ValueError(
                    f"Approval {index} must specify tool_name, object arguments, "
                    "and the exact confirmation string 'yes'"
                )
        self._approvals = data["approvals"]
        self._used = set()

    def __call__(self, proposal):
        for index, approval in enumerate(self._approvals):
            if index in self._used:
                continue
            if (
                approval["tool_name"] == proposal["action"]
                and approval["arguments"] == proposal["arguments"]
            ):
                self._used.add(index)
                return True
        return False

    def matches(self, action, arguments):
        return any(
            approval["tool_name"] == action and approval["arguments"] == arguments
            for approval in self._approvals
        )


def _ollama_litellm_name(model):
    if not isinstance(model, str) or not model.strip():
        raise ValueError("A local Ollama model name is required")
    if "/" in model:
        raise ValueError("Pass the Ollama tag only, for example qwen2.5:3b")
    return f"ollama_chat/{model}"


@traced(run_type="chain")
def _run_original_evaluator(run_simulation, orchestrator):
    return run_simulation(orchestrator)


def _require_tau2_data(paths):
    missing_paths = [Path(path) for path in paths if not Path(path).is_file()]
    if missing_paths:
        missing = ", ".join(str(path) for path in missing_paths)
        raise RuntimeError(
            "τ²-bench data is incomplete. Set TAU2_DATA_DIR to the data directory "
            "from the pinned tau2-bench checkout, including the airline domain data "
            "and the configured language pack. Missing files: "
            f"{missing}"
        )


def _user_tools_for_task(environment, task):
    if environment.user_tools is None:
        return None
    return environment.get_user_tools(include=task.user_tools) or None


def _collect_tool_actions(messages, environment):
    actions = []
    for message in messages or []:
        for call in getattr(message, "tool_calls", None) or []:
            action = {
                "tool_name": call.name,
                "arguments": call.arguments or {},
                "requestor": call.requestor,
            }
            action["mutates_state"] = environment._is_mutating_tool(
                action["tool_name"]
            )
            actions.append(action)
    return actions


def run_tau2(args):
    try:
        import tau2.config as tau2_config

        model = _ollama_litellm_name(args.model)
        llm_args = {
            "api_base": args.ollama_base_url.rstrip("/"),
            "temperature": 0.0,
        }
        tau2_config.DEFAULT_LLM_NL_ASSERTIONS = model
        tau2_config.DEFAULT_LLM_NL_ASSERTIONS_ARGS = llm_args
        tau2_config.DEFAULT_SEMANTIC_COMMUNICATE_MODEL = model
        tau2_config.DEFAULT_SEMANTIC_COMMUNICATE_MODEL_ARGS = llm_args

        from tau2.agent import LLMAgent
        from tau2.domains.airline.environment import (
            get_environment,
            get_tasks,
        )
        from tau2.domains.airline.utils import (
            AIRLINE_DB_PATH,
            AIRLINE_POLICY_PATH,
            AIRLINE_TASK_SET_PATH,
        )
        from tau2.multilingual.runtime import language_root
        from tau2.orchestrator.orchestrator import Orchestrator
        from tau2.runner.simulation import run_simulation
        from tau2.user.user_simulator import UserSimulator
    except ImportError as exc:
        raise RuntimeError(
            "tau2-bench is not installed. Install the project dependencies with "
            "'pip install -r requirements.txt'."
        ) from exc

    _require_tau2_data(
        (
            AIRLINE_DB_PATH,
            AIRLINE_POLICY_PATH,
            AIRLINE_TASK_SET_PATH,
            language_root() / tau2_config.DEFAULT_LANGUAGE / "pack.yaml",
        )
    )
    random.seed(args.seed)
    tasks = get_tasks(task_split_name=args.split)
    random.Random(args.seed).shuffle(tasks)
    tasks = tasks[: args.limit] if args.limit else tasks
    if not tasks:
        raise ValueError(f"No tasks selected from tau2 split {args.split!r}")

    run_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + uuid.uuid4().hex[:8]
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    approvals = PreapprovedActions(args.approval_file) if args.approval_file else None
    task_results = []

    for mode in ("baseline", "gated"):
        for task_index, task in enumerate(tasks):
            base_environment = get_environment()
            environment = base_environment
            gate = None
            if mode == "gated":
                gate = ConfirmationGate(output / f"{run_id}-{mode}-{task.id}.db")
                environment = GatedTau2Environment(
                    base_environment,
                    gate,
                    approve_proposal=approvals,
                    actor_id="tau2-agent",
                    session_id=f"{run_id}-{mode}-{task.id}",
                )
            agent = LLMAgent(
                tools=base_environment.get_tools(),
                domain_policy=base_environment.get_policy(),
                llm=model,
                llm_args=llm_args,
            )
            user = UserSimulator(
                llm=model,
                instructions=task.user_scenario,
                tools=_user_tools_for_task(base_environment, task),
                llm_args=llm_args,
            )
            orchestrator = Orchestrator(
                domain="airline",
                agent=agent,
                user=user,
                environment=environment,
                task=task,
                max_steps=args.max_steps,
                seed=args.seed + task_index,
            )
            started = time.perf_counter()
            simulation = _run_original_evaluator(run_simulation, orchestrator)
            result = simulation.model_dump(mode="json")
            reward_info = result.get("reward_info") or {}
            tool_actions = _collect_tool_actions(
                simulation.messages,
                base_environment,
            )
            audit = gate.audit_events() if gate else []
            unauthorized_executions = sum(
                action["requestor"] == "assistant"
                and action["mutates_state"]
                and not (
                    approvals
                    and approvals.matches(action["tool_name"], action["arguments"])
                )
                for action in tool_actions
            ) if mode == "baseline" else 0
            blocked_actions = sum(
                event["event_type"] == "external_mutating_tool_blocked"
                for event in audit
            )
            false_blocks = sum(
                bool(
                    event["event_type"] == "external_mutating_tool_blocked"
                    and approvals
                    and approvals.matches(event["action"], event["arguments"])
                )
                for event in audit
            )
            task_result = {
                "run_id": run_id,
                "mode": mode,
                "task_id": task.id,
                "task_reward": reward_info.get("reward"),
                "latency_seconds": round(time.perf_counter() - started, 6),
                "unauthorized_executions": unauthorized_executions,
                "false_blocks": false_blocks,
                "blocked_actions": blocked_actions,
                "confirmations": sum(
                    event["event_type"] == "explicit_confirmation_received"
                    for event in audit
                ),
                "tool_actions": tool_actions,
                "security_audit": audit,
                "model": model,
                "seed": args.seed,
                "simulation": result,
            }
            task_results.append(task_result)
            print(
                f"{mode:8} task={task.id} "
                f"tau2_reward={task_result['task_reward']} "
                f"blocked={blocked_actions} "
                f"unauthorized={unauthorized_executions}"
            )

    summaries = {}
    for mode in ("baseline", "gated"):
        rows = [row for row in task_results if row["mode"] == mode]
        rewards = [
            row["task_reward"]
            for row in rows
            if isinstance(row["task_reward"], (int, float))
        ]
        summaries[mode] = {
            "tasks": len(rows),
            "mean_tau2_reward": sum(rewards) / len(rewards) if rewards else None,
            "task_success_rate": (
                sum(reward >= 1 for reward in rewards) / len(rewards)
                if rewards
                else None
            ),
            "unauthorized_executions": sum(
                row["unauthorized_executions"] for row in rows
            ),
            "false_blocks": sum(row["false_blocks"] for row in rows),
            "blocked_actions": sum(row["blocked_actions"] for row in rows),
            "confirmations": sum(row["confirmations"] for row in rows),
            "mean_latency_seconds": (
                sum(row["latency_seconds"] for row in rows) / len(rows)
                if rows
                else None
            ),
        }
    metadata = {
        "run_id": run_id,
        "created_at": time.time(),
        "tau2_version": _tau2_version(),
        "tau2_repository_commit": "05736c27219b769d0be507574dd3135010916644",
        "domain": "airline",
        "split": args.split,
        "task_ids": [task.id for task in tasks],
        "seed": args.seed,
        "agent_and_user_model": model,
        "provider": "local Ollama via LiteLLM; no paid model API configured",
        "approval_file": str(args.approval_file) if args.approval_file else None,
        "max_steps": args.max_steps,
        "summary": summaries,
    }
    (output / f"{run_id}-metadata.json").write_text(
        json.dumps(metadata, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    (output / f"{run_id}-results.json").write_text(
        json.dumps(task_results, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    print(f"Saved tau2-bench outcome-evaluator results under {output}")
    return {"metadata": metadata, "results": task_results}


def _tau2_version():
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("tau2")
    except PackageNotFoundError:
        return "unknown"


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run tau2-bench airline tasks with the original evaluator and gate comparison."
    )
    parser.add_argument("--split", default="base")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-steps", type=int, default=100)
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument(
        "--ollama-base-url",
        default="http://localhost:11434",
    )
    parser.add_argument("--approval-file", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/tau2_runs"))
    args = parser.parse_args()
    if args.limit < 1 or args.max_steps < 1:
        parser.error("--limit and --max-steps must be positive")
    run_tau2(args)


if __name__ == "__main__":
    main()
