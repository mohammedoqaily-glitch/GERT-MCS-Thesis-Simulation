from __future__ import annotations

import json
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]


def load_config(path: str | Path) -> dict:
    """Load the JSON-compatible YAML configuration without optional dependencies."""
    config_path = Path(path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["config_path"] = str(config_path)
    for key in ("output_directory", "cache_directory"):
        value = Path(config[key])
        config[key] = str((BASE / value).resolve() if not value.is_absolute() else value.resolve())
    if config["baseline_replications"] <= 0:
        raise ValueError("baseline_replications must be positive")
    if not 0 < config["confidence_level"] < 1:
        raise ValueError("confidence_level must be between 0 and 1")
    if config["bootstrap_resamples"] < 1000:
        raise ValueError("bootstrap_resamples must be at least 1,000")
    if any(n <= 0 for n in config["replication_counts"]):
        raise ValueError("replication_counts must be positive")
    if config["baseline_replications"] not in config["replication_counts"]:
        raise ValueError("replication_counts must include baseline_replications")
    return config
