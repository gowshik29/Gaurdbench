import json
import re
import time
import uuid
from pathlib import Path


def save_episode(episode, directory="data/episodes"):
    episode.setdefault("episode_id", str(uuid.uuid4()))
    episode.setdefault("created_at", time.time())
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", episode["episode_id"]):
        raise ValueError("episode_id may contain only letters, digits, ., _, and -")
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    target = path / (episode["episode_id"] + ".json")
    target.write_text(
        json.dumps(episode, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    return target


def load_episodes(directory="data/episodes"):
    path = Path(directory)
    if not path.exists():
        return []
    episodes = []
    for file_path in sorted(path.glob("*.json")):
        try:
            episode = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"Invalid episode file: {file_path}") from exc
        if not isinstance(episode, dict):
            raise ValueError(f"Episode must be a JSON object: {file_path}")
        episodes.append(episode)
    return episodes
