from evaluation.label_metrics import binary_metrics, calibration_report
from evaluation.make_label_template import create_template
from evaluation.score_judge import calibration_for_labels


def test_binary_metrics_exclude_missing_labels_and_report_confusion():
    metrics = binary_metrics(
        ["true", "false", "true", "unknown"],
        ["true", "true", "false", ""],
    )

    assert metrics["labeled_count"] == 3
    assert metrics["excluded_count"] == 1
    assert metrics["confusion_matrix"] == {
        "true_positive": 1,
        "false_positive": 1,
        "false_negative": 1,
        "true_negative": 0,
    }
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1"] == 0.5
    assert metrics["human_label_class_counts"] == {"true": 2, "false": 1}


def test_calibration_reports_inconclusive_for_small_sample():
    report = calibration_report([0.9, 0.8], [True, False])

    assert report["status"] == "inconclusive_insufficient_or_imbalanced_labels"
    assert report["expected_calibration_error"] is None
    assert report["sample_count"] == 2


def test_calibration_uses_separate_labels_and_correctness_outcome():
    verdicts = {
        "a": {"confidence": 0.9, "task_correctness": "true"},
        "b": {"confidence": 0.4, "task_correctness": "false"},
        "c": {"confidence": 0.9, "task_correctness": "true"},
    }
    labels = {
        "a": {"human_task_quality": "PASS"},
        "b": {"human_task_quality": "PASS"},
        "not_scored": {"human_task_quality": "FAIL"},
    }

    report = calibration_for_labels(verdicts, labels)

    assert report["sample_count"] == 2
    assert report["status"] == "inconclusive_insufficient_or_imbalanced_labels"


def test_label_template_marks_authorization_ground_truth_read_only(tmp_path):
    target = tmp_path / "calibration.csv"
    create_template(
        [
            {
                "episode_id": "ep-1",
                "authorization_ground_truth": {
                    "authorized_fixture": False,
                    "unauthorized_execution": True,
                },
            }
        ],
        target,
        "calibration",
    )

    content = target.read_text(encoding="utf-8")
    assert "authorization_ground_truth_read_only" in content
    assert "calibration" in content
    assert "human_task_quality" in content
