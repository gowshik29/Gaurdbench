import csv
import json

from evaluation.report import build_report
from evaluation.run_experiments import run_experiment
from guardrails.action_policy import ActionPolicy, DEFAULT_POLICY


def test_ablation_metadata_and_outcomes_are_reproducible(tmp_path):
    result = run_experiment(8, tmp_path, seed=17)

    assert {episode["mode"] for episode in result["episodes"]} == {
        "baseline",
        "gated",
        "risk_aware",
    }
    assert all(
        episode["authorization_ground_truth"]["actual_execution"]
        == (episode["result"]["status"] == "executed")
        for episode in result["episodes"]
    )
    metadata_files = list(tmp_path.glob("*-metadata.json"))
    metadata = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    assert metadata["hypothesis"]
    assert metadata["predeclared_metrics"]
    assert metadata["benchmark"] == "synthetic; tau2-bench was not run"
    preregistration = json.loads(
        (tmp_path / metadata["preregistration_file"]).read_text(encoding="utf-8")
    )
    assert preregistration["registered_at"] <= metadata["started_at"]
    assert preregistration["hypothesis"] == metadata["hypothesis"]
    assert metadata["configuration"]["policy_mappings"]["gated"][
        "cancel_booking"
    ] == {"approval_required": True, "risk_level": "HIGH"}
    reproducibility_files = list(
        (tmp_path / "reports").glob("*-reproducibility.md")
    )
    reproduction = reproducibility_files[0].read_text(encoding="utf-8")
    assert "Benchmark provenance" in reproduction or "## Provenance" in reproduction
    assert "--benchmark synthetic --episodes 8 --seed 17" in reproduction
    assert "Limitations" in reproduction

    report = result["report"]
    assert report["sample_sizes"] == {
        "baseline": 8,
        "gated": 8,
        "risk_aware": 8,
    }
    assert report["modes"]["baseline"]["unauthorized_executions"] > 0
    assert report["modes"]["gated"]["unauthorized_executions"] == 0
    assert report["modes"]["risk_aware"]["unauthorized_executions"] > 0
    assert report["modes"]["gated"]["confirmation_rate"] == 0.5
    assert report["modes"]["gated"]["human_task_quality_labels"] == 0
    assert report["modes"]["gated"]["model_judge_predictions"] == 0
    assert report["adversarial_checks"]["case_count"] == 30
    with (tmp_path / "reports" / f"{report['run_id']}.csv").open(
        newline="", encoding="utf-8"
    ) as report_file:
        csv_rows = list(csv.DictReader(report_file))
    assert [row["mode"] for row in csv_rows] == [
        "baseline",
        "gated",
        "risk_aware",
    ]
    assert all(row["confirmation_rate"] for row in csv_rows)
    assert report["adversarial_checks"]["evidence_scope"].startswith(
        "Untrusted text was supplied as an invalid approval identifier"
    )
    assert all(
        row["blocked"] == row["cases"]
        for row in report["adversarial_checks"][
            "attack_category_breakdown"
        ].values()
    )


def test_empty_mode_metrics_are_not_reported_as_zero():
    report = build_report(
        [
            {
                "mode": "gated",
                "task_success": True,
                "policy_compliant": True,
                "sensitive": False,
                "latency_seconds": 0.1,
            }
        ]
    )

    assert report["modes"]["baseline"]["task_success_rate"] is None
    assert report["modes"]["baseline"]["unauthorized_execution_rate"] is None


def test_policy_ablation_has_a_distinct_version():
    rules = dict(DEFAULT_POLICY.rules)
    assert ActionPolicy(rules).version == DEFAULT_POLICY.version
