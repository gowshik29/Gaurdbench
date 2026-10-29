import argparse
import csv
import json
from pathlib import Path

from .episodes import load_episodes


def create_template(episodes, output_path, split):
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(
            f"{path} already exists; fill it in without regenerating the template."
        )
    fields = [
        "episode_id",
        "dataset_split",
        "human_task_quality",
        "human_task_success",
        "human_policy_compliant",
        "authorization_ground_truth_read_only",
        "labeler_notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for episode in episodes:
            writer.writerow(
                {
                    "episode_id": episode.get("episode_id", ""),
                    "dataset_split": split,
                    "human_task_quality": "",
                    "human_task_success": "",
                    "human_policy_compliant": "",
                    "authorization_ground_truth_read_only": json.dumps(
                        episode.get("authorization_ground_truth", {}),
                        sort_keys=True,
                    ),
                    "labeler_notes": "",
                }
            )
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Create a human-label template without overwriting existing labels."
    )
    parser.add_argument("--input", type=Path, default=Path("data/episodes"))
    parser.add_argument("--output", type=Path, default=Path("data/human_labels.csv"))
    parser.add_argument(
        "--split",
        choices=("evaluation", "calibration"),
        default="evaluation",
    )
    args = parser.parse_args(argv)
    episodes = load_episodes(args.input)
    if not episodes:
        raise RuntimeError(f"No episodes found in {args.input}")
    path = create_template(episodes, args.output, args.split)
    print(
        f"Created {path}; label human_task_quality as PASS/FAIL/UNCERTAIN. "
        "Deterministic authorization ground truth is read-only reference data."
    )


if __name__ == "__main__":
    main()
