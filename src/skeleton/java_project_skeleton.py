from __future__ import annotations

import re
import shutil
from pathlib import Path

from src.common.io_utils import read_json, write_json, write_text
from src.common.models import ProjectPlan, TranslationTask
from src.common.run_logger import RunLogger


class JavaProjectSkeletonManager:
    def __init__(self, target_root: Path, logger: RunLogger):
        self.target_root = target_root
        self.logger = logger

    def write(self, plan: ProjectPlan, project_plan: dict | None = None) -> dict:
        if project_plan is None:
            existing_path = self.path()
            project_plan = read_json(existing_path) if existing_path.exists() else {}
        payload = self.to_project_ast(project_plan, plan)
        self.logger.write_artifact("plans/java_project_sketeon.json", payload)
        write_json(self.target_root / "java_project_sketeon.json", payload)
        self.materialize(payload)
        return payload

    def path(self) -> Path:
        target_path = self.target_root / "java_project_sketeon.json"
        if target_path.exists():
            return target_path
        artifact_root = self.logger.artifact_root
        if artifact_root is not None:
            artifact_path = artifact_root / "plans" / "java_project_sketeon.json"
            if artifact_path.exists():
                return artifact_path
        return target_path

    def to_project_ast(self, project_plan: dict, plan: ProjectPlan) -> dict:
        return {
            "node_type": "JavaProjectAST",
            "java_version": project_plan.get("java_version", "17"),
            "build_tool": project_plan.get("build_tool", "maven"),
            "source_project": plan.source_project,
            "target_project": plan.target_project,
            "verification_commands": plan.verification_commands,
            "files": [self.java_ast_file(task) for task in plan.tasks],
        }

    def java_ast_file(self, task: TranslationTask) -> dict:
        path = task.target_path
        is_java = path.endswith(".java")
        return {
            "node_type": "CompilationUnit" if is_java else self.resource_node_type(path),
            "path": path,
            "package": self.package_for_target(path) if is_java else "",
            "target_role": task.target_role,
            "source_files": task.source_files,
            "description": task.description,
            "dependencies": task.dependencies,
            "imports": [self.import_node(item) for item in task.planned_imports],
            "exports": task.planned_exports,
            "types": self.type_nodes(task) if is_java else [],
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
            if target.suffix == ".java":
                write_text(target, self.render_java_file(file_node))
            elif target.name == "pom.xml":
                write_text(target, self.render_pom(project_ast))
            elif target.suffix in {".md", ".txt"}:
                write_text(target, f"# TODO\n\n{file_node.get('description', '')}\n")
            else:
                write_text(target, "")
        self.logger.event("plan", "Java sketelon materialized", target=str(sketelon_root))

    def render_java_file(self, file_node: dict) -> str:
        lines: list[str] = []
        package_name = file_node.get("package", "")
        if package_name:
            lines.extend([f"package {package_name};", ""])

        imports = sorted({self.render_import_node(item) for item in file_node.get("imports", [])})
        imports = [item for item in imports if item and not item.endswith(f".{self.primary_type_name(file_node)};")]
        if imports:
            lines.extend(imports)
            lines.append("")

        types = file_node.get("types", [])
        if not types:
            types = [{"node_type": "ClassDeclaration", "name": self.class_name_for_path(file_node.get("path", "")), "methods": []}]
        for type_node in types:
            keyword = "interface" if type_node.get("node_type") == "InterfaceDeclaration" else "enum" if type_node.get("node_type") == "EnumDeclaration" else "class"
            name = type_node.get("name") or self.class_name_for_path(file_node.get("path", ""))
            lines.append(f"public {keyword} {name} {{")
            methods = type_node.get("methods", [])
            for method in methods:
                lines.append(f"    public void {method.get('name', 'method')}() {{")
                lines.append("    }")
                lines.append("")
            lines.append("}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def render_pom(project_ast: dict) -> str:
        java_version = project_ast.get("java_version", "17")
        return f"""<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.example</groupId>
  <artifactId>translated-project-skeleton</artifactId>
  <version>1.0.0</version>
  <properties>
    <maven.compiler.source>{java_version}</maven.compiler.source>
    <maven.compiler.target>{java_version}</maven.compiler.target>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
</project>
"""

    def type_nodes(self, task: TranslationTask) -> list[dict]:
        names = [item for item in task.planned_exports if self.looks_like_type(item)]
        if not names:
            names = [self.class_name_for_path(task.target_path)]
        return [{"node_type": "ClassDeclaration", "name": name, "methods": []} for name in names]

    @staticmethod
    def import_node(value: str) -> dict:
        value = (value or "").strip()
        if value.startswith("import "):
            value = value.removeprefix("import ").strip().rstrip(";")
        return {"node_type": "ImportDeclaration", "name": value}

    @staticmethod
    def render_import_node(node: dict) -> str:
        name = node.get("name", "").strip().rstrip(";")
        if not name or "." not in name:
            return ""
        return f"import {name};"

    @staticmethod
    def resource_node_type(path: str) -> str:
        if path.endswith("pom.xml"):
            return "MavenBuildFile"
        if path.endswith(".md"):
            return "MarkdownDocument"
        return "ResourceFile"

    @staticmethod
    def package_for_target(path: str) -> str:
        parts = Path(path).parts
        if "java" not in parts:
            return ""
        after_java = parts[parts.index("java") + 1 : -1]
        return ".".join(after_java)

    @staticmethod
    def class_name_for_path(path: str) -> str:
        stem = Path(path).stem or "Application"
        cleaned = re.sub(r"[^A-Za-z0-9_]", "_", stem)
        return "".join(part[:1].upper() + part[1:] for part in cleaned.split("_") if part) or "Application"

    @staticmethod
    def primary_type_name(file_node: dict) -> str:
        types = file_node.get("types", [])
        if types:
            return types[0].get("name", "")
        return JavaProjectSkeletonManager.class_name_for_path(file_node.get("path", ""))

    @staticmethod
    def looks_like_type(name: str) -> bool:
        return bool(re.match(r"^[A-Z][A-Za-z0-9_]*$", name or ""))
