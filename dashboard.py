import os
import json
import sqlite3
import uuid
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from app.action_agent import ActionAgent
from app.gated_tools import GatedAirlineTools
from app.settings import get_settings, langsmith_tracing_enabled
from evaluation.episodes import load_episodes
from guardrails.action_policy import ACTION_NAMES


st.set_page_config(page_title="GuardBench", page_icon="🛡️", layout="wide")
st.title("GuardBench")
st.caption(
    "Local synthetic airline demo and evaluation dashboard. "
    "No real airline service is connected."
)

with st.sidebar:
    st.subheader("LangSmith tracing")
    tracing_enabled = langsmith_tracing_enabled()
    key_present = bool(os.getenv("LANGSMITH_API_KEY"))
    agent_id = os.getenv("LANGSMITH_AGENT_ID")
    agent_environment = os.getenv("LANGSMITH_AGENT_ENVIRONMENT")
    if bool(agent_id) != bool(agent_environment):
        destination = "Incomplete agent destination"
    elif agent_id and agent_environment:
        destination = f"Agent: {agent_id} / {agent_environment}"
    else:
        destination = f"Project: {get_settings()['langsmith_project']}"
    st.write(f"Tracing: {'enabled' if tracing_enabled else 'disabled'}")
    st.write(f"API key: {'configured' if key_present else 'not found'}")
    st.write(f"Destination: {destination}")
    if not tracing_enabled:
        st.warning("Enable tracing in config.json or set LANGSMITH_TRACING=true.")
    elif not key_present:
        st.warning("Set LANGSMITH_API_KEY in the shell that starts Streamlit.")
    elif destination == "Incomplete agent destination":
        st.warning("Set both LangSmith agent ID and environment, or unset both.")


def _get_chat_runtime():
    if "guardbench_session_id" not in st.session_state:
        st.session_state.guardbench_session_id = str(uuid.uuid4())
    if "guardbench_tools" not in st.session_state:
        st.session_state.guardbench_tools = GatedAirlineTools(
            actor_id="local-user",
            session_id=st.session_state.guardbench_session_id,
        )
    if "guardbench_agent" not in st.session_state:
        st.session_state.guardbench_agent = ActionAgent()
    if "guardbench_messages" not in st.session_state:
        st.session_state.guardbench_messages = []
    if "guardbench_pending" not in st.session_state:
        st.session_state.guardbench_pending = None
    return (
        st.session_state.guardbench_tools,
        st.session_state.guardbench_agent,
    )


def _complete_action(tools, pending, approved):
    if not approved:
        tools.approve(pending["proposal_id"], "no")
        st.session_state.guardbench_messages.append(
            {"role": "assistant", "content": "Action denied; no tool was executed."}
        )
        st.session_state.guardbench_pending = None
        return

    if not tools.approve(pending["proposal_id"], "yes"):
        st.session_state.guardbench_messages.append(
            {
                "role": "assistant",
                "content": "This approval is no longer valid. No action was executed.",
            }
        )
        st.session_state.guardbench_pending = None
        return

    result = tools.dispatch(
        pending["action"],
        pending["arguments"],
        pending["proposal_id"],
    )
    tool_result = result.get("result")
    failed = result.get("status") != "executed" or (
        isinstance(tool_result, dict) and tool_result.get("ok") is False
    )
    if failed:
        detail = (
            tool_result.get("error", "The tool rejected the request.")
            if isinstance(tool_result, dict)
            else result.get("reason") or result.get("error") or "The tool failed."
        )
        content = f"The action could not be completed: {detail}"
    else:
        content = pending["response"]

    st.session_state.guardbench_messages.append(
        {
            "role": "assistant",
            "content": content,
            "tool_result": result,
        }
    )
    st.session_state.guardbench_pending = None


def _render_interactive_demo():
    st.subheader("Interactive synthetic airline agent")
    st.write(
        "Try a flight search or ask about an existing synthetic booking. "
        "State-changing actions require approval of the exact action and arguments."
    )
    st.caption("Known demo bookings: DEMO-100 and DEMO-200. Type `quit` to clear the chat.")
    tools, agent = _get_chat_runtime()

    if st.button("Clear chat", disabled=st.session_state.guardbench_pending is not None):
        st.session_state.guardbench_messages = []
        st.rerun()

    for message in st.session_state.guardbench_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "tool_result" in message:
                st.json(message["tool_result"])

    pending = st.session_state.guardbench_pending
    if pending is not None:
        st.warning("Review the exact state-changing action before approving it.")
        st.json(
            {
                "action": pending["action"],
                "arguments": pending["arguments"],
                "risk_level": pending["risk_level"],
                "policy_version": pending["policy_version"],
                "expires_at": pending["expires_at"],
            }
        )
        approve_column, deny_column = st.columns(2)
        if approve_column.button("Approve this exact action", type="primary"):
            try:
                _complete_action(tools, pending, approved=True)
            except (ValueError, json.JSONDecodeError, sqlite3.Error, requests.RequestException) as exc:
                st.error(f"Action failed: {type(exc).__name__}: {exc}")
                st.session_state.guardbench_pending = None
            st.rerun()
        if deny_column.button("Deny", type="secondary"):
            try:
                _complete_action(tools, pending, approved=False)
            except sqlite3.Error as exc:
                st.error(f"Could not record denial: {type(exc).__name__}: {exc}")
                st.session_state.guardbench_pending = None
            st.rerun()

    prompt = st.chat_input(
        "Message the synthetic airline agent",
        disabled=st.session_state.guardbench_pending is not None,
    )
    if prompt is None:
        return
    if prompt.strip().lower() in {"quit", "exit"}:
        st.session_state.guardbench_messages = []
        st.session_state.guardbench_pending = None
        st.rerun()

    st.session_state.guardbench_messages.append({"role": "user", "content": prompt})
    try:
        decision = agent.decide(
            prompt,
            state={"known_booking_ids": tools.booking_ids},
        )
        action = decision["action"]
        arguments = decision["arguments"]
        if action == "none":
            st.session_state.guardbench_messages.append(
                {"role": "assistant", "content": decision["response"]}
            )
        elif action not in ACTION_NAMES:
            st.session_state.guardbench_messages.append(
                {"role": "assistant", "content": "Blocked: unknown action."}
            )
        else:
            proposal = tools.propose(action, arguments)
            if proposal["requires_confirmation"]:
                st.session_state.guardbench_pending = {
                    "proposal_id": proposal["proposal_id"],
                    "action": action,
                    "arguments": arguments,
                    "response": decision["response"],
                    "risk_level": proposal["risk_level"],
                    "policy_version": proposal["policy_version"],
                    "expires_at": proposal["expires_at"],
                }
            else:
                result = tools.dispatch(action, arguments)
                tool_result = result.get("result")
                failed = result.get("status") != "executed" or (
                    isinstance(tool_result, dict) and tool_result.get("ok") is False
                )
                content = (
                    "The action could not be completed: "
                    + (
                        tool_result.get("error", "The tool rejected the request.")
                        if isinstance(tool_result, dict)
                        else result.get("reason") or result.get("error") or "The tool failed."
                    )
                    if failed
                    else decision["response"]
                )
                st.session_state.guardbench_messages.append(
                    {
                        "role": "assistant",
                        "content": content,
                        "tool_result": result,
                    }
                )
    except (ValueError, json.JSONDecodeError, sqlite3.Error, requests.RequestException) as exc:
        st.session_state.guardbench_messages.append(
            {
                "role": "assistant",
                "content": f"Request failed: {type(exc).__name__}: {exc}",
            }
        )
    st.rerun()


def _render_evaluation_dashboard():
    st.subheader("Evaluation dashboard")
    st.caption("τ²-bench is the default evaluation. Synthetic results are available separately.")
    tau2_runs = Path("data/tau2_runs")
    metadata_files = sorted(
        tau2_runs.glob("*-metadata.json"),
        reverse=True,
    ) if tau2_runs.exists() else []
    if metadata_files:
        metadata_by_run = {}
        results_by_run = {}
        for metadata_file in metadata_files:
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            run_id = metadata.get("run_id")
            if not isinstance(run_id, str):
                continue
            results_file = metadata_file.with_name(
                metadata_file.name.replace("-metadata.json", "-results.json")
            )
            if results_file.exists():
                metadata_by_run[run_id] = metadata
                results_by_run[run_id] = json.loads(
                    results_file.read_text(encoding="utf-8")
                )
        if metadata_by_run:
            selected_run = st.selectbox(
                "τ²-bench run",
                list(metadata_by_run),
            )
            metadata = metadata_by_run[selected_run]
            summary = metadata.get("summary", {})
            st.caption(
                f"τ²-bench {metadata.get('tau2_version', 'unknown')} · "
                f"split {metadata.get('split', 'unknown')} · "
                f"model {metadata.get('agent_and_user_model', 'unknown')}"
            )
            mode = st.selectbox(
                "Agent mode",
                ["All", "baseline", "gated"],
                key="tau2_agent_mode",
            )
            modes = ["baseline", "gated"] if mode == "All" else [mode]
            rows = []
            for selected_mode in modes:
                metrics = summary.get(selected_mode, {})
                rows.append(
                    {
                        "mode": selected_mode,
                        "tasks": metrics.get("tasks", 0),
                        "mean τ² reward": metrics.get("mean_tau2_reward"),
                        "task success rate": metrics.get("task_success_rate"),
                        "blocked actions": metrics.get("blocked_actions", 0),
                        "unauthorized executions": metrics.get(
                            "unauthorized_executions", 0
                        ),
                        "false blocks": metrics.get("false_blocks", 0),
                        "mean latency (s)": metrics.get("mean_latency_seconds"),
                    }
                )
            st.dataframe(rows, use_container_width=True, hide_index=True)
            all_results = results_by_run[selected_run]
            filtered_results = [
                result
                for result in all_results
                if mode == "All" or result.get("mode") == mode
            ]
            st.subheader("τ²-bench task outcomes")
            st.dataframe(
                [
                    {
                        "mode": result.get("mode"),
                        "task_id": result.get("task_id"),
                        "reward": result.get("task_reward"),
                        "blocked_actions": result.get("blocked_actions"),
                        "unauthorized_executions": result.get(
                            "unauthorized_executions"
                        ),
                        "latency_seconds": result.get("latency_seconds"),
                    }
                    for result in filtered_results
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("τ²-bench metadata was found, but no complete result files are available.")
    else:
        st.info(
            "No τ²-bench results yet. Run "
            "`python -m evaluation.run_experiments` to create the default benchmark run."
        )

    with st.expander("Synthetic deterministic evaluation"):
        _render_synthetic_evaluation_dashboard()


def _render_synthetic_evaluation_dashboard():
    st.subheader("Deterministic adversarial gate checks")
    st.caption(
        "Gate-level checks only; prompt text is not sent to a model and this is "
        "not a model-refusal measurement."
    )
    ablation_root = Path("data/ablations")
    adversarial_metadata_files = (
        sorted(ablation_root.glob("*-metadata.json"), reverse=True)
        if ablation_root.exists()
        else []
    )
    adversarial_runs = {}
    for metadata_file in adversarial_metadata_files:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        if metadata.get("adversarial_checks"):
            adversarial_runs[metadata["run_id"]] = metadata["adversarial_checks"]
    if adversarial_runs:
        attack_run = st.selectbox(
            "Adversarial gate-check run",
            list(adversarial_runs),
            key="guardbench_adversarial_run",
        )
        attack_rows = {}
        for case in adversarial_runs[attack_run]:
            category = case["category"]
            outcome = case["observed_outcome"]
            attack_rows.setdefault(category, {}).setdefault(outcome, 0)
            attack_rows[category][outcome] += 1
        st.dataframe(
            [
                {
                    "Attack category": category,
                    "Cases": sum(counts.values()),
                    "Blocked": counts.get("blocked", 0),
                    "Executed": counts.get("executed", 0),
                    "Failed": counts.get("failed", 0),
                }
                for category, counts in sorted(attack_rows.items())
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No saved deterministic adversarial gate-check report is available.")

    episode_sources = {
        "Default synthetic episodes": Path("data/episodes"),
        "Ablation episodes": Path("data/ablations/episodes"),
    }
    available_sources = {
        label: path
        for label, path in episode_sources.items()
        if path.exists() and list(path.glob("*.json"))
    }
    if len(available_sources) > 1:
        source_label = st.selectbox(
            "Synthetic episode source",
            list(available_sources),
            key="guardbench_episode_source",
        )
    else:
        source_label = next(iter(available_sources), None)
    episodes = (
        load_episodes(available_sources[source_label])
        if source_label
        else []
    )
    if not episodes:
        st.info(
            "No synthetic episodes yet. Run "
            "`python -m evaluation.run_experiments --benchmark synthetic`."
        )
        return

    run_ids = sorted(
        {episode.get("run_id", "legacy") for episode in episodes},
        reverse=True,
    )
    selected_run = st.selectbox("Evaluation run", run_ids)
    selected_mode = st.selectbox(
        "Agent mode",
        ["All", "baseline", "gated", "risk_aware"],
    )
    filtered = [
        episode
        for episode in episodes
        if episode.get("run_id", "legacy") == selected_run
        and (selected_mode == "All" or episode.get("mode") == selected_mode)
    ]
    if not filtered:
        st.info("No episodes are available for the selected run and mode.")
        return

    count = len(filtered)
    success_rate = (
        sum(bool(item.get("task_success")) for item in filtered) / count if count else 0
    )
    compliance_rate = (
        sum(bool(item.get("policy_compliant")) for item in filtered) / count if count else 0
    )
    unauthorized = sum(bool(item.get("unauthorized_execution")) for item in filtered)
    false_blocks = sum(bool(item.get("false_block")) for item in filtered)
    unauthorized_attempts = sum(
        bool(item.get("sensitive")) and not bool(item.get("authorized_fixture"))
        for item in filtered
    )
    authorized_attempts = sum(
        bool(item.get("sensitive")) and bool(item.get("authorized_fixture"))
        for item in filtered
    )
    latencies = [float(item.get("latency_seconds", 0)) for item in filtered]
    mean_latency = sum(latencies) / len(latencies) if latencies else 0
    confirmations = sum(bool(item.get("confirmation_provided")) for item in filtered)
    mutating = sum(bool(item.get("sensitive")) for item in filtered)

    columns = st.columns(6)
    columns[0].metric("Episodes", count)
    columns[1].metric("Policy-aware task success", f"{success_rate:.1%}")
    columns[2].metric("Policy compliance", f"{compliance_rate:.1%}")
    columns[3].metric("Unauthorized executions", unauthorized)
    columns[4].metric("False blocks", false_blocks)
    columns[5].metric("Mean latency", f"{mean_latency:.6f}s")
    st.metric(
        "Confirmations (count / mutating actions)",
        f"{confirmations} / {mutating}",
    )
    rate_columns = st.columns(2)
    rate_columns[0].metric(
        "False-allow rate",
        f"{unauthorized / unauthorized_attempts:.1%}"
        if unauthorized_attempts
        else "not measured",
    )
    rate_columns[1].metric(
        "False-block rate",
        f"{false_blocks / authorized_attempts:.1%}"
        if authorized_attempts
        else "not measured",
    )

    st.subheader("Latency by episode")
    latency_rows = [
        {
            "episode": index + 1,
            "latency_seconds": float(episode.get("latency_seconds", 0)),
            "mode": episode.get("mode", "unknown"),
        }
        for index, episode in enumerate(filtered)
    ]
    if latency_rows:
        st.line_chart(
            pd.DataFrame(latency_rows),
            x="episode",
            y="latency_seconds",
            color="mode",
        )

    st.subheader("Episode outcomes")
    st.dataframe(
        [
            {
                "mode": episode.get("mode"),
                "request": episode.get("request"),
                "action": episode.get("action"),
                "risk_level": episode.get("risk_level"),
                "policy_version": episode.get("policy_version"),
                "result": episode.get("result", {}).get("status"),
                "task_success": episode.get("task_success"),
                "policy_compliant": episode.get("policy_compliant"),
                "unauthorized_execution": episode.get("unauthorized_execution"),
                "false_block": episode.get("false_block"),
                "human_task_quality_label": episode.get("human_task_quality_label"),
                "model_judge_prediction": episode.get("model_judge_prediction"),
                "latency_seconds": episode.get("latency_seconds"),
                "result_detail": episode.get("result", {}).get("reason")
                or episode.get("result", {}).get("error"),
            }
            for episode in filtered
        ],
        use_container_width=True,
        hide_index=True,
    )
    with st.expander("Proposal, gate decision, and audit event drill-down"):
        selected_episode_id = st.selectbox(
            "Episode",
            [episode.get("episode_id", "unknown") for episode in filtered],
            key="guardbench_audit_episode",
        )
        selected_episode = next(
            episode
            for episode in filtered
            if episode.get("episode_id", "unknown") == selected_episode_id
        )
        st.json(
            {
                "proposal": selected_episode.get("proposal"),
                "gate_decision": selected_episode.get("result"),
                "authorization_ground_truth": selected_episode.get(
                    "authorization_ground_truth"
                ),
                "audit_events": selected_episode.get("security_audit_events", []),
            }
        )

    st.subheader("Failure categories")
    failures = {}
    for episode in filtered:
        result = episode.get("result", {})
        if not episode.get("task_success"):
            reason = (
                result.get("reason")
                or result.get("error")
                or "unexpected execution result"
            )
            failures[reason] = failures.get(reason, 0) + 1
    if failures:
        st.bar_chart(
            pd.DataFrame(
                {
                    "failure_category": list(failures),
                    "count": list(failures.values()),
                }
            ).set_index("failure_category")
        )
    else:
        st.write("No policy-aware task failures in this selection.")

    st.subheader("Human-label agreement and judge calibration")
    judge_report_path = Path("reports/judge_evaluation.json")
    if not judge_report_path.exists():
        st.info(
            "No judge evaluation report is available. Run the local judge and "
            "complete evaluation/calibration labels before interpreting these metrics."
        )
    else:
        judge_report = json.loads(judge_report_path.read_text(encoding="utf-8"))
        st.write(
            {
                "Human task-quality agreement": judge_report.get(
                    "human_task_quality_agreement"
                ),
                "Policy-compliance agreement": judge_report.get(
                    "policy_compliance_agreement"
                ),
                "Human-label coverage": judge_report.get("human_label_coverage"),
                "Calibration status": (judge_report.get("calibration") or {}).get(
                    "status"
                ),
            }
        )
        calibration_bins = (judge_report.get("calibration") or {}).get(
            "reliability_bins",
            [],
        )
        if calibration_bins:
            st.line_chart(
                pd.DataFrame(calibration_bins),
                x="mean_confidence",
                y="observed_accuracy",
            )


interactive_tab, evaluation_tab = st.tabs(
    ["Interactive airline demo", "Evaluation dashboard"]
)
with interactive_tab:
    _render_interactive_demo()
with evaluation_tab:
    _render_evaluation_dashboard()
