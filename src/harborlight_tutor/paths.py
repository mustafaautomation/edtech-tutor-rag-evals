"""Repository paths. The project is run from a source checkout so the corpus stays with the code."""

from pathlib import Path


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "data").is_dir():
            return candidate
    raise FileNotFoundError("Could not find the repository root from " + str(here))


def corpus_dir() -> Path:
    return repo_root() / "data" / "corpus"


def questions_path() -> Path:
    return repo_root() / "data" / "eval" / "questions.jsonl"


def settings_path() -> Path:
    return repo_root() / "config" / "settings.yaml"


def thresholds_path() -> Path:
    return repo_root() / "config" / "thresholds.yaml"


def snapshot_path() -> Path:
    return repo_root() / "data" / "snapshots" / "pipeline_outputs.jsonl"
