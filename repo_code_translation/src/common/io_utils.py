from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TEXT_EXTENSIONS = {
    ".java",
    ".py",
    ".xml",
    ".properties",
    ".yml",
    ".yaml",
    ".html",
    ".css",
    ".js",
    ".md",
    ".txt",
    ".toml",
}


def read_text(path: Path, max_chars: int | None = None) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]..."
    return text


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))


def iter_text_files(root: Path) -> list[Path]:
    ignored = {".git", "target", "build", ".gradle", "__pycache__", ".pytest_cache", "node_modules"}
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored for part in path.parts):
            continue
        if path.suffix in TEXT_EXTENSIONS:
            files.append(path)
    return sorted(files)
