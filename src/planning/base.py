from __future__ import annotations

import json
from pathlib import Path

from src.common.io_utils import read_text, write_json, write_text
from src.common.models import ProjectPlan, RepoAnalysis, TranslationTask


class BaseProjectPlanner:
    materialize_writes_plan = False

    def plan(self, analysis: RepoAnalysis, target_root: Path) -> ProjectPlan:
        raise NotImplementedError

    def materialize(self, plan: ProjectPlan, target_root: Path) -> None:
        target_root.mkdir(parents=True, exist_ok=True)
        if self.materialize_writes_plan:
            write_json(target_root / "translation_plan.json", plan.to_dict())
        for task in plan.tasks:
            path = target_root / task.target_path
            if path.exists():
                continue
            write_text(path, self._placeholder(task))

    def _placeholder(self, task: TranslationTask) -> str:
        raise NotImplementedError

    @staticmethod
    def _merge_tasks(tasks: list[TranslationTask]) -> list[TranslationTask]:
        merged: dict[str, TranslationTask] = {}
        for task in tasks:
            existing = merged.get(task.target_path)
            if existing is None:
                merged[task.target_path] = task
                continue
            existing.source_files = sorted(set(existing.source_files + task.source_files))
            existing.dependencies = sorted(set(existing.dependencies + task.dependencies))
            if task.target_role not in existing.target_role:
                existing.target_role = f"{existing.target_role}+{task.target_role}"
            existing.description = existing.description.rstrip(".") + ". " + task.description
        return list(merged.values())


class BasePlanPromptBuilder:
    def build_prompt(self, analysis: RepoAnalysis, deterministic_plan: ProjectPlan) -> str:
        raise NotImplementedError

    @classmethod
    def parse_plan(cls, text: str, fallback: ProjectPlan) -> ProjectPlan:
        try:
            stripped = cls._strip_json_response(text)
            data = json.loads(stripped)
            tasks = []
            for item in data.get("tasks", []):
                target_path = item.get("target_path", "")
                if not cls._valid_target_path(target_path):
                    return fallback
                tasks.append(
                    TranslationTask(
                        target_path=target_path,
                        target_role=item.get("target_role", "unknown"),
                        source_files=item.get("source_files", []),
                        description=item.get("description", ""),
                        dependencies=item.get("dependencies", []),
                        planned_exports=item.get("planned_exports", []),
                        planned_imports=item.get("planned_imports", []),
                    )
                )
            if not tasks:
                return fallback
            return ProjectPlan(
                source_project=fallback.source_project,
                target_project=fallback.target_project,
                architecture=data.get("architecture", fallback.architecture),
                tasks=tasks,
                verification_commands=data.get("verification_commands", fallback.verification_commands),
            )
        except Exception:
            return fallback

    @staticmethod
    def _strip_json_response(text: str) -> str:
        stripped = text.strip()
        if "```" in stripped:
            stripped = stripped.split("```", 2)[1]
            if stripped.startswith("json"):
                stripped = stripped[4:]
        return stripped

    @staticmethod
    def _valid_target_path(path: str) -> bool:
        return bool(path)


class RefinedPlanBuilder:
    def refine(self, plan: ProjectPlan) -> list[dict]:
        refined = []
        for index, task in enumerate(plan.tasks, start=1):
            refined.append(
                {
                    "index": index,
                    "target_path": task.target_path,
                    "target_role": task.target_role,
                    "reference_java_files": task.source_files,
                    "dependencies": task.dependencies,
                    "planned_exports": task.planned_exports,
                    "planned_imports": task.planned_imports,
                    "expected_symbols": self._expected_symbols(task.description),
                    "semantic_contract": task.description,
                    "retrieval_query": self._retrieval_query(task),
                }
            )
        return refined

    @staticmethod
    def _expected_symbols(description: str) -> list[str]:
        marker = "Preserve behavior for:"
        if marker not in description:
            return []
        symbols = []
        for part in description.split(marker)[1:]:
            chunk = part.split(".", 1)[0]
            symbols.extend(item.strip() for item in chunk.split(",") if item.strip())
        return [symbol for symbol in symbols if symbol != "no public methods detected"]

    @staticmethod
    def _retrieval_query(task: TranslationTask) -> str:
        return " ".join(
            [
                task.target_path,
                task.target_role,
                task.description,
                *task.source_files,
                *task.dependencies,
                *task.planned_exports,
                *task.planned_imports,
            ]
        )


def copy_resource_if_direct(task: TranslationTask, source_root: Path, target_root: Path) -> bool:
    if task.target_role not in {"static", "template"} or not task.source_files:
        return False
    source = source_root / task.source_files[0]
    if not source.exists():
        return False
    write_text(target_root / task.target_path, read_text(source))
    return True
