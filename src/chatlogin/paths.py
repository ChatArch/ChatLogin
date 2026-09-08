"""Resolve owned runtime paths without creating files."""
from dataclasses import dataclass
from pathlib import Path
import re


def validate_instance(instance: str) -> str:
    if not isinstance(instance, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", instance):
        raise ValueError("Instance must contain 1..64 ASCII letters, digits, underscores or hyphens")
    return instance


@dataclass(frozen=True)
class StatePaths:
    directory: Path
    database: Path


def state_paths(instance: str, *, home: str | Path | None = None) -> StatePaths:
    from chatenv import get_paths
    validate_instance(instance)
    root = Path(home) if home is not None else Path(get_paths().home_dir)
    directory = root / "chatlogin" / "instances" / instance
    return StatePaths(directory, directory / "sessions.sqlite3")
