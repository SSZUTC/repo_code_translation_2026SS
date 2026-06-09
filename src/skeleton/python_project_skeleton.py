from __future__ import annotations

import re
import shutil
from pathlib import Path

from src.common.io_utils import read_json, write_json, write_text
from src.common.models import ProjectPlan, TranslationTask
from src.common.run_logger import RunLogger


class PythonProjectSkeletonManager:
    def __init__(self, target_root: Path, logger: RunLogger):
        self.target_root = target_root
        self.logger = logger

    def write(self, plan: ProjectPlan, project_plan: dict | None = None) -> dict:
        if project_plan is None:
            existing_path = self.path()
            project_plan = read_json(existing_path) if existing_path.exists() else {}
        payload = self.to_project_ast(project_plan, plan)
        self.logger.write_artifact("plans/python_project_sketeon.json", payload)
        write_json(self.target_root / "python_project_sketeon.json", payload)
        self.materialize(payload)
        return payload

    def load_plan(self, fallback_factory) -> ProjectPlan:
        plan_path = self.path()
        if not plan_path.exists():
            return fallback_factory()
        data = read_json(plan_path)
        if data.get("node_type") != "PythonProjectAST":
            raise ValueError(f"Unsupported project plan format: {plan_path}")
        return self.plan_from_project_ast(data)

    def path(self) -> Path:
        target_path = self.target_root / "python_project_sketeon.json"
        if target_path.exists():
            return target_path
        artifact_root = self.logger.artifact_root
        if artifact_root is not None:
            artifact_path = artifact_root / "plans" / "python_project_sketeon.json"
            if artifact_path.exists():
                return artifact_path
        return target_path

    def to_project_ast(self, project_plan: dict, plan: ProjectPlan) -> dict:
        return {
            "node_type": "PythonProjectAST",
            "python_version": project_plan.get("python_version", "3.10"),
            "source_project": plan.source_project,
            "target_project": plan.target_project,
            "verification_commands": plan.verification_commands,
            "files": [self.python_ast_file(task) for task in plan.tasks],
        }

    def python_ast_file(self, task: TranslationTask) -> dict:
        return {
            "node_type": "Module",
            "path": task.target_path,
            "target_role": task.target_role,
            "source_files": task.source_files,
            "description": task.description,
            "dependencies": task.dependencies,
            "imports": [self.import_node(item) for item in task.planned_imports],
            "exports": task.planned_exports,
            "classes": [{"node_type": "ClassDef", "name": item, "methods": []} for item in task.planned_exports if self.looks_like_class(item)],
            "functions": [{"node_type": "FunctionDef", "name": item, "args": []} for item in task.planned_exports if self.looks_like_function(item)],
            "constants": [{"node_type": "Name", "name": item} for item in task.planned_exports if self.looks_like_constant(item)],
            "status": task.status,
        }

    def materialize(self, project_ast: dict) -> None:
        if self.logger.artifact_root is None:
            return
        sketelon_root = self.logger.artifact_root / "plans" / "sketelon"
        if sketelon_root.exists():
            shutil.rmtree(sketelon_root)
        for file_node in project_ast.get("files", []):
            target = sketelon_root / file_node.get("path", "")
            if target.suffix == ".py":
                write_text(target, self.render_python_file(file_node))
                self.ensure_package_init_files(sketelon_root, target.parent)
            elif target.name == "requirements.txt":
                write_text(target, "\n".join(file_node.get("dependencies", [])) + "\n")
            elif target.suffix in {".md", ".txt"}:
                write_text(target, f"# TODO\n\n{file_node.get('description', '')}\n")
            else:
                write_text(target, "")
        self.logger.event("plan", "Python sketelon materialized", target=str(sketelon_root))

    def render_python_file(self, file_node: dict) -> str:
        lines = [f'"""Skeleton for {file_node.get("description", "").strip()}"""', ""]
        import_lines = [self.render_import_node(item) for item in file_node.get("imports", [])]
        import_lines = [line for line in import_lines if line]
        if import_lines:
            lines.extend(import_lines)
            lines.append("")
        for constant in file_node.get("constants", []):
            lines.append(f"{constant.get('name')} = None")
        if file_node.get("constants"):
            lines.append("")
        for class_node in file_node.get("classes", []):
            lines.append(f"class {class_node.get('name')}:")
            methods = class_node.get("methods", [])
            if methods:
                for method in methods:
                    args = ", ".join(method.get("args", [])) or "self"
                    lines.append(f"    def {method.get('name')}({args}):")
                    lines.append("        pass")
                    lines.append("")
            else:
                lines.append("    pass")
                lines.append("")
        for function in file_node.get("functions", []):
            args = ", ".join(function.get("args", []))
            lines.append(f"def {function.get('name')}({args}):")
            lines.append("    pass")
            lines.append("")
        if len(lines) <= 2:
            lines.append("pass")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def plan_from_project_ast(self, data: dict) -> ProjectPlan:
        tasks = []
        for file_node in data.get("files", []):
            planned_imports = [self.import_text(item) for item in file_node.get("imports", [])]
            tasks.append(
                TranslationTask(
                    target_path=file_node["path"],
                    target_role=file_node.get("target_role", "module"),
                    source_files=file_node.get("source_files", []),
                    description=file_node.get("description", ""),
                    dependencies=file_node.get("dependencies", []),
                    planned_exports=file_node.get("exports", []),
                    planned_imports=planned_imports,
                    status=file_node.get("status", "pending"),
                )
            )
        return ProjectPlan(
            source_project=data.get("source_project", ""),
            target_project=data.get("target_project", str(self.target_root)),
            architecture="Python AST project skeleton.",
            tasks=tasks,
            verification_commands=data.get("verification_commands", ["python -m compileall app", "python -m pytest"]),
        )

    @staticmethod
    def import_node(value: str) -> dict:
        if not value:
            return {"node_type": "Import", "module": ""}
        if value.startswith("import "):
            value = value.removeprefix("import ").strip()
        if " as " in value:
            module, alias = [item.strip() for item in value.split(" as ", 1)]
            return {"node_type": "Import", "module": module, "alias": alias}
        if "." not in value:
            return {"node_type": "Import", "module": value}
        module, name = value.rsplit(".", 1)
        if re.match(r"^[A-Z_][A-Za-z0-9_]*$", name) or name in {"app", "array", "client", "defaultdict", "router"}:
            return {"node_type": "ImportFrom", "module": module, "name": name}
        return {"node_type": "Import", "module": value}

    @staticmethod
    def import_text(node: dict) -> str:
        if node.get("node_type") == "ImportFrom":
            return ".".join(item for item in [node.get("module", ""), node.get("name", "")] if item)
        if node.get("alias"):
            return f"{node.get('module', '')} as {node.get('alias')}"
        return node.get("module", "")

    @staticmethod
    def render_import_node(node: dict) -> str:
        if node.get("node_type") == "ImportFrom":
            return f"from {node.get('module')} import {node.get('name')}"
        module = node.get("module", "")
        if not module:
            return ""
        if node.get("alias"):
            return f"import {module} as {node.get('alias')}"
        return f"import {module}"

    @staticmethod
    def ensure_package_init_files(root: Path, directory: Path) -> None:
        try:
            directory.relative_to(root)
        except ValueError:
            return
        current = directory
        while current != root:
            if current.name in {"app", "tests"} or (root / "app") in current.parents or (root / "tests") in current.parents:
                init_file = current / "__init__.py"
                if not init_file.exists():
                    write_text(init_file, "")
            current = current.parent

    @staticmethod
    def looks_like_class(name: str) -> bool:
        return bool(re.match(r"^[A-Z][A-Za-z0-9_]*$", name))

    @staticmethod
    def looks_like_function(name: str) -> bool:
        return (
            bool(re.match(r"^[a-z_][A-Za-z0-9_]*$", name))
            and not name.isupper()
            and not PythonProjectSkeletonManager.looks_like_constant(name)
        )

    @staticmethod
    def looks_like_constant(name: str) -> bool:
        return name.isupper() or name in {"app", "router"}
