from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class JavaFileInfo:
    path: str
    package: str
    class_name: str
    kind: str
    imports: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    symbols: dict[str, Any] = field(default_factory=dict)
    ast_tree: dict[str, Any] = field(default_factory=dict)
    summary: str = ""


@dataclass
class RepoAnalysis:
    source_root: str
    build_tool: str
    framework_hints: list[str]
    files: list[JavaFileInfo]
    resources: list[str]
    tests: list[str]
    file_tree: dict[str, Any] = field(default_factory=dict)
    build_info: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TranslationTask:
    target_path: str
    target_role: str
    source_files: list[str]
    description: str
    dependencies: list[str] = field(default_factory=list)
    planned_exports: list[str] = field(default_factory=list)
    planned_imports: list[str] = field(default_factory=list)
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectPlan:
    source_project: str
    target_project: str
    architecture: str
    tasks: list[TranslationTask]
    verification_commands: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_project": self.source_project,
            "target_project": self.target_project,
            "architecture": self.architecture,
            "tasks": [task.to_dict() for task in self.tasks],
            "verification_commands": self.verification_commands,
        }


@dataclass
class RetrievedFile:
    path: str
    score: float
    content: str


def rel_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
