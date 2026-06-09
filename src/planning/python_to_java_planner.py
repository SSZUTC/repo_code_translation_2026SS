from __future__ import annotations

import re
from pathlib import Path

from src.common.models import RepoAnalysis, ProjectPlan, TranslationTask
from src.planning.base import BaseProjectPlanner


def pascal_case(name: str) -> str:
    pieces = re.split(r"[_\-.]+", name)
    text = "".join(piece[:1].upper() + piece[1:] for piece in pieces if piece)
    return re.sub(r"[^A-Za-z0-9_]", "", text) or "Application"


class PythonToJavaProjectPlanner(BaseProjectPlanner):
    materialize_writes_plan = True
    base_package = "com.translated"

    def plan(self, analysis: RepoAnalysis, target_root: Path) -> ProjectPlan:
        tasks: list[TranslationTask] = []
        for file_info in analysis.files:
            if file_info.path.endswith("__init__.py"):
                continue
            target_path = self._target_path(file_info.kind, file_info.path, file_info.class_name)
            tasks.append(
                TranslationTask(
                    target_path=target_path,
                    target_role=file_info.kind,
                    source_files=[file_info.path],
                    description=self._description(file_info.kind, file_info.path, file_info.class_name, file_info.methods),
                    dependencies=file_info.dependencies,
                )
            )
        tasks.extend(self._resource_tasks(analysis))
        self._ensure_support_files(tasks)
        return ProjectPlan(
            source_project=analysis.source_root,
            target_project=str(target_root.resolve()),
            architecture=(
                "Python repository to Java Maven translation. Preserve package-level layers: "
                "models, DTOs, repositories, services, common logic, controllers, resources, and tests."
            ),
            tasks=self._merge_tasks(tasks),
            verification_commands=["mvn -q test"],
        )

    def _target_path(self, kind: str, source_path: str, class_name: str) -> str:
        simple_name = self._java_class_name(source_path, class_name, kind)
        if kind == "test":
            return f"src/test/java/{self.base_package.replace('.', '/')}/{simple_name}.java"
        layer = {
            "controller": "controller",
            "service": "service",
            "repository": "repository",
            "model": "model",
            "dto": "dto",
            "common": "common",
            "application": "",
        }.get(kind, "common")
        package_dir = self.base_package.replace(".", "/")
        if layer:
            package_dir = f"{package_dir}/{layer}"
        return f"src/main/java/{package_dir}/{simple_name}.java"

    @staticmethod
    def _java_class_name(source_path: str, class_name: str, kind: str) -> str:
        if class_name and class_name not in {"Main", "App", "Init"}:
            name = pascal_case(class_name)
        else:
            name = pascal_case(Path(source_path).stem)
        if kind == "test" and not name.endswith("Test"):
            name += "Test"
        if kind == "application" and name.lower() in {"main", "app"}:
            name = "Application"
        return name

    @staticmethod
    def _description(kind: str, source_path: str, class_name: str, methods: list[str]) -> str:
        methods_text = ", ".join(methods) if methods else "module-level behavior and public API"
        return f"Translate Python {kind} file {source_path} into Java class {class_name}. Preserve behavior for: {methods_text}."

    @staticmethod
    def _resource_tasks(analysis: RepoAnalysis) -> list[TranslationTask]:
        tasks = []
        for resource in analysis.resources:
            path = Path(resource)
            if path.suffix in {".html", ".css", ".js"}:
                target = path.name
                if "templates" in path.parts:
                    target_path = f"src/main/resources/templates/{target}"
                    role = "template"
                else:
                    target_path = f"src/main/resources/static/{target}"
                    role = "static"
            else:
                target_path = f"src/main/resources/{path.name}"
                role = "resource"
            tasks.append(
                TranslationTask(
                    target_path=target_path,
                    target_role=role,
                    source_files=[resource],
                    description="Copy or adapt Python project resource into the Java resource tree.",
                )
            )
        return tasks

    @staticmethod
    def _ensure_support_files(tasks: list[TranslationTask]) -> None:
        existing = {task.target_path for task in tasks}
        support = {
            "pom.xml": "Maven build file with JUnit dependencies.",
            "README.md": "Target Java project usage notes.",
        }
        for path, description in support.items():
            if path not in existing:
                tasks.insert(0, TranslationTask(path, "support", [], description))
                existing.add(path)

    def _placeholder(self, task: TranslationTask) -> str:
        if task.target_path == "pom.xml":
            return self._pom_xml()
        if task.target_path.endswith(".java"):
            class_name = Path(task.target_path).stem
            package = self._package_for_target(task.target_path)
            return f"package {package};\n\n// TODO: {task.description}\npublic class {class_name} {{\n}}\n"
        if task.target_path.endswith(".md"):
            return f"# TODO\n\n{task.description}\n"
        return f"// TODO: {task.description}\n"

    def _package_for_target(self, target_path: str) -> str:
        marker = "src/main/java/"
        if target_path.startswith("src/test/java/"):
            marker = "src/test/java/"
        package_path = str(Path(target_path).parent).split(marker, 1)[-1]
        return package_path.replace("/", ".")

    @staticmethod
    def _pom_xml() -> str:
        return """<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.translated</groupId>
  <artifactId>translated-java-project</artifactId>
  <version>1.0.0</version>
  <properties>
    <maven.compiler.source>11</maven.compiler.source>
    <maven.compiler.target>11</maven.compiler.target>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.junit.jupiter</groupId>
      <artifactId>junit-jupiter</artifactId>
      <version>5.10.2</version>
      <scope>test</scope>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-surefire-plugin</artifactId>
        <version>3.2.5</version>
      </plugin>
    </plugins>
  </build>
</project>
"""

