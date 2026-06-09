from __future__ import annotations

import re
from pathlib import Path

from src.common.models import RepoAnalysis, ProjectPlan, TranslationTask
from src.planning.base import BasePlanPromptBuilder, BaseProjectPlanner, RefinedPlanBuilder, copy_resource_if_direct


def snake_case(name: str) -> str:
    text = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
    return text.replace("-", "_").lower()


class JavaToPythonProjectPlanner(BaseProjectPlanner):
    def plan(self, analysis: RepoAnalysis, target_root: Path) -> ProjectPlan:
        tasks: list[TranslationTask] = []
        for file_info in analysis.files:
            if file_info.kind == "test":
                continue
            role = file_info.kind
            target_path = self._target_path(file_info)
            tasks.append(
                TranslationTask(
                    target_path=target_path,
                    target_role=role,
                    source_files=[file_info.path],
                    description=self._description(role, file_info.class_name, file_info.methods),
                    dependencies=file_info.dependencies,
                )
            )

        tasks.extend(self._resource_tasks(analysis))
        tasks.extend(self._test_tasks(analysis))
        self._ensure_support_files(tasks)
        tasks = self._merge_tasks(tasks)

        return ProjectPlan(
            source_project=analysis.source_root,
            target_project=str(target_root.resolve()),
            architecture=(
                "Java Spring Boot to Python Flask/SQLAlchemy translation. "
                "Preserve package-level layers: models, schemas, repositories, services, common logic, routes, UI, tests."
            ),
            tasks=tasks,
            verification_commands=["python -m compileall app", "python -m pytest"],
        )

    @staticmethod
    def _target_path(file_info) -> str:
        package_path = file_info.package.replace(".", "/") if file_info.package else "default_package"
        name = snake_case(file_info.class_name or Path(file_info.path).stem)
        return f"app/java/{package_path}/{name}.py"

    @staticmethod
    def _description(kind: str, class_name: str, methods: list[str]) -> str:
        methods_text = ", ".join(methods) if methods else "no public methods detected"
        return f"Translate Java {kind} {class_name}. Preserve behavior for: {methods_text}."

    @staticmethod
    def _resource_tasks(analysis: RepoAnalysis) -> list[TranslationTask]:
        tasks = []
        for resource in analysis.resources:
            if resource.endswith("templates/index.html"):
                tasks.append(
                    TranslationTask(
                        target_path="app/templates/index.html",
                        target_role="template",
                        source_files=[resource],
                        description="Translate Thymeleaf HTML template to Flask/Jinja-compatible HTML.",
                    )
                )
            elif "/static/" in resource:
                target = resource.split("src/main/resources/static/", 1)[-1]
                tasks.append(
                    TranslationTask(
                        target_path=f"app/static/{target}",
                        target_role="static",
                        source_files=[resource],
                        description="Copy or adapt static browser asset.",
                    )
                )
        return tasks

    @staticmethod
    def _test_tasks(analysis: RepoAnalysis) -> list[TranslationTask]:
        tasks = []
        for test_path in analysis.tests:
            test_name = Path(test_path).stem
            py_name = snake_case(test_name)
            if py_name.endswith("_test"):
                py_name = py_name[:-5]
            target_path = f"tests/test_{py_name}.py"
            tasks.append(
                TranslationTask(
                    target_path=target_path,
                    target_role="test",
                    source_files=[test_path],
                    description=f"Translate JUnit test {test_name} to pytest for the Python implementation.",
                )
            )
        return tasks

    @staticmethod
    def _ensure_support_files(tasks: list[TranslationTask]) -> None:
        existing = {task.target_path for task in tasks}
        support = {
            "app/__init__.py": "Python package initializer.",
            "app/database.py": "Database engine/session setup.",
            "app/models/__init__.py": "Model package exports.",
            "app/schemas/__init__.py": "Schema package exports.",
            "app/common/__init__.py": "Common package exports.",
            "tests/conftest.py": "pytest fixtures.",
            "requirements.txt": "Python dependencies.",
            "README.md": "Target project usage notes.",
        }
        for path, description in support.items():
            if path not in existing:
                tasks.insert(0, TranslationTask(path, "support", [], description))
                existing.add(path)

    @staticmethod
    def _placeholder(task: TranslationTask) -> str:
        if task.target_path.endswith(".py"):
            return f'"""TODO: {task.description}"""\n'
        if task.target_path.endswith(".txt"):
            return "# TODO\n"
        if task.target_path.endswith(".md"):
            return f"# TODO\n\n{task.description}\n"
        return f"<!-- TODO: {task.description} -->\n"


class PlanPromptBuilder(BasePlanPromptBuilder):
    def build_prompt(self, analysis: RepoAnalysis, deterministic_plan: ProjectPlan) -> str:
        return (
            "You are planning a repository-level Java to Python translation.\n"
            "Given the Java analysis and a deterministic draft plan, refine the target Python project plan.\n"
            "Return JSON with a top-level 'tasks' array. Each task must contain target_path, target_role, "
            "source_files, description, dependencies.\n\n"
            f"JAVA_ANALYSIS:\n{analysis.to_dict()}\n\n"
            f"DRAFT_PLAN:\n{deterministic_plan.to_dict()}\n"
        )

    @staticmethod
    def _valid_target_path(path: str) -> bool:
        return bool(path) and not path.endswith(".java")
