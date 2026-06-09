from __future__ import annotations

from pathlib import Path

from src.common.io_utils import read_text, write_text
from src.common.models import RetrievedFile, TranslationTask


def primary_sources(task: TranslationTask, source_root: Path) -> list[RetrievedFile]:
    files = []
    for source_file in task.source_files:
        path = source_root / source_file
        if path.exists():
            files.append(RetrievedFile(source_file, 9999.0, read_text(path, max_chars=40000)))
    return files


def dedupe_retrieved(items: list[RetrievedFile]) -> list[RetrievedFile]:
    seen = set()
    deduped = []
    for item in items:
        if item.path in seen:
            continue
        seen.add(item.path)
        deduped.append(item)
    return deduped


def copy_reference_target(task: TranslationTask, reference_target_root: Path | None, target_root: Path) -> bool:
    if reference_target_root is None:
        return False
    source = reference_target_root / task.target_path
    if not source.exists() or not source.is_file():
        return False
    write_text(target_root / task.target_path, read_text(source))
    return True
