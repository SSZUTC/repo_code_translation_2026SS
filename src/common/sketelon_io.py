from __future__ import annotations

import shutil
from pathlib import Path


def sketelon_root_for(artifact_root: Path | None) -> Path | None:
    if artifact_root is None:
        return None
    return artifact_root / "plans" / "sketelon"


def copy_sketelon_to_target(sketelon_root: Path | None, target_root: Path) -> bool:
    if sketelon_root is None or not sketelon_root.exists():
        return False
    target_root.mkdir(parents=True, exist_ok=True)
    for source in sketelon_root.rglob("*"):
        if not source.is_file() or "__pycache__" in source.parts:
            continue
        relative = source.relative_to(sketelon_root)
        target = target_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return True
