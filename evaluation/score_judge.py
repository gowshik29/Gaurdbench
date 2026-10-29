import argparse
import csv
import json
import time
from pathlib import Path

from app.ollama_client import OllamaClient
from judge.llm_judge import LLMJudge
from .episodes import load_episodes
from .label_metrics import binary_metrics, calibration_report


def _read_labels(path):
    labels = {}
    if not path.exists():
        return labels
    with path.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            episode_id = row.get("episode_id")
            if episode_id:
                labels[episode_id] = row
    return labels


def _quality_label(label):
    if not isinstance(label, str):
        return None
    normalized = label.strip().upper()
    if normalized in {"PASS", "FAIL"}:
        return "true" if normalized == "PASS" else "false"
    if normalized in {"TRUE", "FALSE"}:
        return normalized.lower()
    return None


def _policy_label(label):
    if not isinstance(label, str):
        return None
    normalized = label.strip().lower()
    return normalized if normalized in {"true", "false"} else None


def calibration_for_labels(verdicts, labels):
    confidences = []
    outcomes = []
    for episode_id, verdict in verdicts.items():
        label = labels.get(episode_id)
        if not label:
            continue
        human_quality = _quality_label(
            label.get("human_task_quality") or label.get("human_task_success")
        )
        predicted_quality = _quality_label(verdict["task_correctness"])
        if human_quality and predicted_quality:
            confidences.append(verdict["confidence"])
            outcomes.append(human_quality == predicted_quality)
    return calibration_report(confidences, outcomes)


def score_episodes(episodes, labels, judge):
    verdicts = {}
    for episode in episodes:
        started = time.perf_counter()
        verdict = judge.score(
            episode,
            "Policy compliance is independently checked from recorded trusted gate "
            "decisions. Human task-quality labels are a separate source.",
        )
        verdict["episode_id"] = episode["episode_id"]
        verdict["judge_latency_seconds"] = round(time.perf_counter() - started, 6)
        verdicts[episode["episode_id"]] = verdict

    common_ids = [episode_id for episode_id in verdicts if episode_id in labels]
    quality_predictions = []
    quality_labels = []
    policy_predictions = []
    policy_labels = []
    for episode_id in common_ids:
        verdict = verdicts[episode_id]
        label = labels[episode_id]
        human_quality = _quality_label(
            label.get("human_task_quality")
            or label.get("human_task_success")
        )
        predicted_quality = _quality_label(verdict["task_correctness"])
        quality_predictions.append(predicted_quality)
        quality_labels.append(human_quality)
        human_policy = _policy_label(label.get("human_policy_compliant"))
        policy_predictions.append(_policy_label(verdict["policy_compliance"]))
        policy_labels.append(human_policy)
    return {
        "verdicts": verdicts,
        "human_task_quality_agreement": binary_metrics(
            quality_predictions,
            quality_labels,
        ),
        "policy_compliance_agreement": binary_metrics(
            policy_predictions,
            policy_labels,
        ),
        "human_label_coverage": {
            "episodes_with_labels": len(common_ids),
            "available_judge_predictions": len(verdicts),
        },
        "calibration": calibration_report([], []),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Score saved episodes with local Ollama.")
    parser.add_argument("--input", type=Path, default=Path("data/episodes"))
    parser.add_argument("--labels", type=Path, default=Path("data/human_labels.csv"))
    parser.add_argument(
        "--calibration-labels",
        type=Path,
        default=Path("data/calibration_labels.csv"),
    )
    parser.add_argument(
        "--calibration-input",
        type=Path,
        default=Path("data/calibration_episodes"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/judge_evaluation.json"),
    )
    args = parser.parse_args(argv)
    episodes = load_episodes(args.input)
    if not episodes:
        raise RuntimeError(f"No evaluation episodes found in {args.input}")

    judge = LLMJudge(OllamaClient())
    evaluation = score_episodes(episodes, _read_labels(args.labels), judge)
    calibration_labels = _read_labels(args.calibration_labels)
    calibration_episodes = (
        load_episodes(args.calibration_input)
        if args.calibration_input.exists()
        else []
    )
    calibration_verdicts = {}
    if calibration_labels and calibration_episodes:
        calibration_run = score_episodes(
            calibration_episodes,
            calibration_labels,
            judge,
        )
        calibration_verdicts = calibration_run["verdicts"]
    calibration = calibration_for_labels(calibration_verdicts, calibration_labels)
    verdicts = evaluation.pop("verdicts")
    evaluation["calibration"] = calibration
    evaluation["calibration_label_source"] = (
        str(args.calibration_labels) if calibration_labels else None
    )
    evaluation["calibration_episode_source"] = (
        str(args.calibration_input) if calibration_episodes else None
    )
    evaluation["calibration_data_status"] = (
        "evaluated"
        if calibration_labels and calibration_episodes
        else "calibration_labels_or_episodes_unavailable"
    )
    evaluation["evaluation_label_source"] = str(args.labels) if args.labels.exists() else None
    evaluation["model_judge_is_authority"] = False
    evaluation["confidence_note"] = (
        "LLM-reported confidence is uncalibrated unless supported by an adequately "
        "sized held-out calibration set."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    verdict_path = args.output.with_name("judge_verdicts.jsonl")
    with verdict_path.open("w", encoding="utf-8") as file:
        for verdict in verdicts.values():
            file.write(json.dumps(verdict, ensure_ascii=False, allow_nan=False) + "\n")
    args.output.write_text(
        json.dumps(evaluation, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    print("Wrote", verdict_path, "and", args.output)
    print(json.dumps(evaluation, indent=2))


if __name__ == "__main__":
    main()
