import json
from pathlib import Path


def render_reproducibility_report(metadata, report):
    lines = [
        f"# Reproducibility report: {metadata['run_id']}",
        "",
        "## Provenance",
        "",
        f"- Benchmark: {metadata['benchmark']}",
        f"- Dataset/fixture: {metadata['fixture']}",
        f"- Dataset provenance: {metadata['dataset_provenance']}",
        f"- Run ID: {metadata['run_id']}",
        f"- Preregistration: {metadata['preregistration_file']}",
        f"- Preregistration SHA-256: {metadata['preregistration_sha256']}",
        f"- Git revision: {metadata.get('git_revision') or 'unavailable (no Git metadata)'}",
        f"- Seed: {metadata['seed']}",
        f"- Sample size per mode: {metadata['episodes_per_mode']}",
        f"- Task IDs: {', '.join(metadata['task_ids'])}",
        f"- Started: {metadata['started_at']}",
        f"- Ended: {metadata['ended_at']}",
        "",
        "## Configuration",
        "",
        "```json",
        json.dumps(metadata["configuration"], indent=2, sort_keys=True),
        "```",
        "",
        "## Hypothesis and predeclared metrics",
        "",
        metadata["hypothesis"],
        "",
        ", ".join(metadata["predeclared_metrics"]),
        "",
        "## Results",
        "",
        "| Mode | Episodes | Task success | Policy compliance | Unauthorized executions | False blocks | Confirmations | Confirmation rate | Mean latency (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, metrics in report["modes"].items():
        task_success = (
            f"{metrics['task_success_rate']:.1%}"
            if metrics["task_success_rate"] is not None
            else "not measured"
        )
        compliance = (
            f"{metrics['policy_compliance_rate']:.1%}"
            if metrics["policy_compliance_rate"] is not None
            else "not measured"
        )
        confirmation_rate = (
            f"{metrics['confirmation_rate']:.1%}"
            if metrics["confirmation_rate"] is not None
            else "not measured"
        )
        latency = (
            f"{metrics['mean_latency_seconds']:.6f}"
            if metrics["mean_latency_seconds"] is not None
            else "not measured"
        )
        lines.append(
            f"| {mode} | {metrics['episodes']} | {task_success} | {compliance} | "
            f"{metrics['unauthorized_executions']} | {metrics['false_blocks']} | "
            f"{metrics['confirmations']} | {confirmation_rate} | {latency} |"
        )
    lines.extend(
        [
            "",
            "## Deterministic adversarial gate checks",
            "",
            "These are gate-level checks only; no model refusal was measured.",
            "",
            "| Category | Cases | Blocked | Executed |",
            "|---|---:|---:|---:|",
        ]
    )
    for category, metrics in report["adversarial_checks"][
        "attack_category_breakdown"
    ].items():
        lines.append(
            f"| {category} | {metrics['cases']} | {metrics['blocked']} | "
            f"{metrics['executed']} |"
        )
    lines.extend(
        [
            "",
            "## Limitations",
            "",
            *[f"- {limitation}" for limitation in report["limitations"]],
            "- This synthetic study does not validate local-model task quality or τ²-bench behavior.",
            "- Hash-chained audit records are tamper-evident but are not anchored outside the database.",
            "",
            "## Exact reproduction command",
            "",
            "```powershell",
            metadata["reproduction_command"],
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_reproducibility_report(metadata, report, output_path):
    path = Path(output_path)
    path.write_text(
        render_reproducibility_report(metadata, report),
        encoding="utf-8",
    )
    return path
