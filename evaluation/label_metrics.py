from collections import Counter


def binary_metrics(predictions, labels, positive="true"):
    pairs = [
        (str(prediction).lower(), str(label).lower())
        for prediction, label in zip(predictions, labels)
        if str(prediction).lower() in {"true", "false"}
        and str(label).lower() in {"true", "false"}
    ]
    tp = sum(pred == positive and label == positive for pred, label in pairs)
    tn = sum(pred != positive and label != positive for pred, label in pairs)
    fp = sum(pred == positive and label != positive for pred, label in pairs)
    fn = sum(pred != positive and label == positive for pred, label in pairs)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else 0.0
        if precision == 0 or recall == 0
        else None
    )
    accuracy = (tp + tn) / len(pairs) if pairs else None
    observed = accuracy
    pred_positive = (tp + fp) / len(pairs) if pairs else 0.0
    label_positive = (tp + fn) / len(pairs) if pairs else 0.0
    expected = (
        pred_positive * label_positive
        + (1 - pred_positive) * (1 - label_positive)
    )
    kappa = (observed - expected) / (1 - expected) if observed is not None and expected < 1 else None
    counts = Counter(label for _, label in pairs)
    minority = min(counts.values()) if counts else 0
    majority = max(counts.values()) if counts else 0
    return {
        "labeled_count": len(pairs),
        "excluded_count": len(predictions) - len(pairs),
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "cohen_kappa": kappa,
        "confusion_matrix": {
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "true_negative": tn,
        },
        "human_label_class_counts": dict(counts),
        "class_imbalance_ratio": majority / minority if minority else None,
    }


def calibration_report(confidences, outcomes, minimum_samples=30, bins=10):
    pairs = [
        (float(confidence), bool(outcome))
        for confidence, outcome in zip(confidences, outcomes)
        if isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        and 0 <= confidence <= 1
        and outcome in {True, False}
    ]
    counts = Counter(outcome for _, outcome in pairs)
    base = {
        "sample_count": len(pairs),
        "minimum_sample_count": minimum_samples,
        "human_outcome_counts": {
            "correct": counts.get(True, 0),
            "incorrect": counts.get(False, 0),
        },
        "interpretation": (
            "Model confidence is not assumed to be calibrated probability."
        ),
    }
    if len(pairs) < minimum_samples or len(counts) < 2:
        return {
            **base,
            "status": "inconclusive_insufficient_or_imbalanced_labels",
            "expected_calibration_error": None,
            "reliability_bins": [],
        }

    reliability_bins = []
    weighted_error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        group = [
            (confidence, outcome)
            for confidence, outcome in pairs
            if lower <= confidence < upper
            or (index == bins - 1 and confidence == 1)
        ]
        if not group:
            continue
        mean_confidence = sum(conf for conf, _ in group) / len(group)
        observed_accuracy = sum(outcome for _, outcome in group) / len(group)
        weighted_error += (
            len(group) / len(pairs) * abs(mean_confidence - observed_accuracy)
        )
        reliability_bins.append(
            {
                "lower_bound": lower,
                "upper_bound": upper,
                "count": len(group),
                "mean_confidence": mean_confidence,
                "observed_accuracy": observed_accuracy,
            }
        )
    return {
        **base,
        "status": "descriptive_only",
        "expected_calibration_error": weighted_error,
        "reliability_bins": reliability_bins,
    }
