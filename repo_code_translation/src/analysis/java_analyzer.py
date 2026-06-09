from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from tree_sitter_language_pack import get_parser

from src.analysis.base import BaseProjectAnalyzer
from src.common.io_utils import read_text
from src.common.models import JavaFileInfo, RepoAnalysis, rel_path
from src.prompts.java_project_semantic_analysis import (
    JAVA_PROJECT_SEMANTIC_ANALYSIS_SYSTEM_PROMPT,
    build_java_project_semantic_analysis_prompt,
)


TYPE_DECLARATIONS = {
    "annotation_type_declaration": "annotation",
    "class_declaration": "class",
    "enum_declaration": "enum",
    "interface_declaration": "interface",
    "record_declaration": "record",
}
MEMBER_DECLARATIONS = {
    "annotation_type_declaration",
    "class_declaration",
    "constructor_declaration",
    "enum_declaration",
    "field_declaration",
    "interface_declaration",
    "method_declaration",
    "record_declaration",
}
ANNOTATION_NODES = {"annotation", "marker_annotation"}


class JavaProjectAnalyzer(BaseProjectAnalyzer):
    ignored_dirs = {
        ".git",
        ".idea",
        ".mvn",
        "__pycache__",
        "target",
        "build",
        "dist",
        ".pytest_cache",
    }

    def __init__(self):
        self.parser = get_parser("java")

    def analyze(self, source_root: Path) -> RepoAnalysis:
        source_root = source_root.resolve()
        java_files = sorted(source_root.rglob("*.java"))
        files = [self._analyze_java_file(path, source_root) for path in java_files]
        resources = self._resource_paths(source_root)
        tests = [file_info.path for file_info in files if file_info.kind == "test"]
        return RepoAnalysis(
            source_root=str(source_root),
            build_tool=self._detect_build_tool(source_root),
            framework_hints=self._detect_frameworks(source_root),
            files=files,
            resources=resources,
            tests=tests,
            file_tree=self.extract_file_tree(source_root),
            build_info=self._build_info(source_root),
        )

    def ast_parser_name(self) -> str:
        return "tree-sitter-language-pack/java"

    def extract_project_semantics_prompt(self, analysis: RepoAnalysis) -> str:
        return build_java_project_semantic_analysis_prompt(analysis)

    def project_semantics_system_prompt(self) -> str:
        return JAVA_PROJECT_SEMANTIC_ANALYSIS_SYSTEM_PROMPT

    def _analyze_java_file(self, path: Path, root: Path) -> JavaFileInfo:
        source = read_text(path)
        root_node = self.parser.parse(source).root_node()
        source_bytes = source.encode("utf-8")
        ast_tree = self._build_ast_tree(path, root, root_node, source, source_bytes)
        primary_type = self._primary_type(ast_tree, path)

        class_name = primary_type.get("name") or path.stem
        methods = [method["name"] for type_node in ast_tree["types"] for method in type_node.get("methods", [])]
        imports = [item["name"] for item in ast_tree["imports"]]
        annotations = ast_tree["annotations"]
        dependencies = self._extract_dependencies(ast_tree)
        kind = self._classify(path, primary_type, ast_tree)

        return JavaFileInfo(
            path=rel_path(path, root),
            package=ast_tree["package"],
            class_name=class_name,
            kind=kind,
            imports=imports,
            annotations=annotations,
            methods=methods,
            dependencies=dependencies,
            symbols=self._symbols(ast_tree),
            ast_tree=ast_tree,
            summary=self._summary(kind, ast_tree),
        )

    def _build_ast_tree(self, path: Path, root: Path, root_node, source: str, source_bytes: bytes) -> dict[str, Any]:
        return {
            "node_type": "CompilationUnit",
            "parser": "tree-sitter-language-pack/java",
            "path": rel_path(path, root),
            "source_set": self._source_set(path),
            "package": self._package_name(root_node, source_bytes),
            "imports": self._imports(root_node, source_bytes),
            "annotations": self._top_level_annotations(root_node, source_bytes),
            "types": [self._type_node(child, source_bytes) for child in self._children(root_node) if self._kind(child) in TYPE_DECLARATIONS],
            "raw_tree": root_node.to_sexp(),
            "has_error": bool(root_node.has_error()),
            "source_lines": source.count("\n") + 1,
        }

    def _package_name(self, root_node, source_bytes: bytes) -> str:
        for child in self._children(root_node):
            if self._kind(child) != "package_declaration":
                continue
            for item in self._children(child):
                if self._kind(item) in {"scoped_identifier", "identifier"}:
                    return self._text(item, source_bytes)
        return ""

    def _imports(self, root_node, source_bytes: bytes) -> list[dict[str, Any]]:
        imports = []
        for child in self._children(root_node):
            if self._kind(child) not in {"import_declaration", "static_import_declaration"}:
                continue
            text = self._text(child, source_bytes).strip().rstrip(";")
            is_static = " static " in f" {text} " or self._kind(child) == "static_import_declaration"
            name = text.replace("import", "", 1).replace("static", "", 1).strip()
            imports.append(
                {
                    "name": name,
                    "static": is_static,
                    "wildcard": name.endswith(".*"),
                    "line": self._start_line(child),
                }
            )
        return imports

    def _type_node(self, node, source_bytes: bytes) -> dict[str, Any]:
        body = self._field(node, "body")
        direct_members = [child for child in self._children(body) if self._kind(child) in MEMBER_DECLARATIONS] if body else []
        type_node = {
            "node_type": "TypeDeclaration",
            "kind": TYPE_DECLARATIONS.get(self._kind(node), self._kind(node)),
            "name": self._name(node, source_bytes),
            "modifiers": self._modifiers(node, source_bytes),
            "annotations": self._annotations(node, source_bytes),
            "extends": self._extends(node, source_bytes),
            "implements": self._implements(node, source_bytes),
            "fields": [field for member in direct_members for field in self._fields(member, source_bytes)],
            "constructors": [self._constructor(member, source_bytes) for member in direct_members if self._kind(member) == "constructor_declaration"],
            "methods": [self._method(member, source_bytes) for member in direct_members if self._kind(member) == "method_declaration"],
            "nested_types": [self._nested_type(member, source_bytes) for member in direct_members if self._kind(member) in TYPE_DECLARATIONS],
            "span": {"start_line": self._start_line(node), "end_line": self._end_line(node)},
        }
        type_node["constructors"] = [item for item in type_node["constructors"] if item]
        type_node["methods"] = [item for item in type_node["methods"] if item]
        return type_node

    def _fields(self, node, source_bytes: bytes) -> list[dict[str, Any]]:
        if self._kind(node) != "field_declaration":
            return []
        type_node = self._field(node, "type")
        field_type = self._text(type_node, source_bytes) if type_node else ""
        fields = []
        for child in self._children(node):
            if self._kind(child) != "variable_declarator":
                continue
            name_node = self._field(child, "name") or self._first_child(child, {"identifier"})
            fields.append(
                {
                    "node_type": "FieldDeclaration",
                    "name": self._text(name_node, source_bytes) if name_node else self._text(child, source_bytes),
                    "type": field_type,
                    "modifiers": self._modifiers(node, source_bytes),
                    "annotations": self._annotations(node, source_bytes),
                    "span": {"start_line": self._start_line(node), "end_line": self._end_line(node)},
                }
            )
        return fields

    def _constructor(self, node, source_bytes: bytes) -> dict[str, Any] | None:
        if self._kind(node) != "constructor_declaration":
            return None
        return {
            "node_type": "ConstructorDeclaration",
            "name": self._name(node, source_bytes),
            "parameters": self._parameters(self._field(node, "parameters"), source_bytes),
            "modifiers": self._modifiers(node, source_bytes),
            "annotations": self._annotations(node, source_bytes),
            "throws": self._throws(node, source_bytes),
            "has_body": self._field(node, "body") is not None,
            "span": {"start_line": self._start_line(node), "end_line": self._end_line(node)},
        }

    def _method(self, node, source_bytes: bytes) -> dict[str, Any] | None:
        if self._kind(node) != "method_declaration":
            return None
        type_node = self._field(node, "type")
        return {
            "node_type": "MethodDeclaration",
            "name": self._name(node, source_bytes),
            "return_type": self._text(type_node, source_bytes) if type_node else "",
            "parameters": self._parameters(self._field(node, "parameters"), source_bytes),
            "modifiers": self._modifiers(node, source_bytes),
            "annotations": self._annotations(node, source_bytes),
            "throws": self._throws(node, source_bytes),
            "has_body": self._field(node, "body") is not None,
            "span": {"start_line": self._start_line(node), "end_line": self._end_line(node)},
        }

    def _nested_type(self, node, source_bytes: bytes) -> dict[str, Any]:
        return {
            "node_type": "NestedTypeDeclaration",
            "kind": TYPE_DECLARATIONS.get(self._kind(node), self._kind(node)),
            "name": self._name(node, source_bytes),
            "modifiers": self._modifiers(node, source_bytes),
            "annotations": self._annotations(node, source_bytes),
            "span": {"start_line": self._start_line(node), "end_line": self._end_line(node)},
        }

    def _parameters(self, parameters_node, source_bytes: bytes) -> list[dict[str, str]]:
        if not parameters_node:
            return []
        params = []
        for child in self._children(parameters_node):
            if self._kind(child) not in {"formal_parameter", "spread_parameter"}:
                continue
            type_node = self._field(child, "type")
            name_node = self._field(child, "name")
            params.append(
                {
                    "name": self._text(name_node, source_bytes) if name_node else "",
                    "type": self._text(type_node, source_bytes) if type_node else "",
                }
            )
        return params

    def _top_level_annotations(self, root_node, source_bytes: bytes) -> list[str]:
        annotations = []
        for child in self._children(root_node):
            if self._kind(child) in TYPE_DECLARATIONS:
                annotations.extend(self._annotations(child, source_bytes))
        return sorted(set(annotations))

    def _annotations(self, node, source_bytes: bytes) -> list[str]:
        annotations = []
        for modifier in self._modifier_nodes(node):
            for child in self._walk(modifier):
                if self._kind(child) not in ANNOTATION_NODES:
                    continue
                name_node = self._first_descendant(child, {"identifier", "scoped_identifier"})
                name = self._text(name_node, source_bytes) if name_node else self._text(child, source_bytes).lstrip("@")
                annotations.append(name.split("(", 1)[0].strip())
        return sorted(set(item for item in annotations if item))

    def _modifiers(self, node, source_bytes: bytes) -> list[str]:
        modifiers = []
        for modifier in self._modifier_nodes(node):
            for child in self._children(modifier):
                if self._kind(child) in ANNOTATION_NODES:
                    continue
                value = self._text(child, source_bytes).strip()
                if value:
                    modifiers.append(value)
        return sorted(set(modifiers))

    def _modifier_nodes(self, node) -> list[Any]:
        return [child for child in self._children(node) if self._kind(child) == "modifiers"]

    def _extends(self, node, source_bytes: bytes) -> list[str]:
        values = []
        for child in self._children(node):
            if self._kind(child) in {"superclass", "extends_interfaces"}:
                values.extend(self._named_type_texts(child, source_bytes))
        return values

    def _implements(self, node, source_bytes: bytes) -> list[str]:
        values = []
        for child in self._children(node):
            if self._kind(child) == "super_interfaces":
                values.extend(self._named_type_texts(child, source_bytes))
        return values

    def _throws(self, node, source_bytes: bytes) -> list[str]:
        for child in self._children(node):
            if self._kind(child) == "throws":
                return self._named_type_texts(child, source_bytes)
        return []

    def _named_type_texts(self, node, source_bytes: bytes) -> list[str]:
        values = []
        for child in self._children(node):
            if self._kind(child) in {"type_identifier", "scoped_type_identifier", "generic_type", "identifier", "scoped_identifier"}:
                values.append(self._text(child, source_bytes))
        if not values:
            text = self._text(node, source_bytes)
            text = re.sub(r"^(extends|implements|throws)\s+", "", text).strip()
            values = [item.strip() for item in text.split(",") if item.strip()]
        return values

    @staticmethod
    def _primary_type(ast_tree: dict[str, Any], path: Path) -> dict[str, Any]:
        types = ast_tree.get("types", [])
        if not types:
            return {"name": path.stem, "kind": "unknown", "annotations": [], "fields": [], "methods": []}
        for type_node in types:
            if type_node.get("name") == path.stem:
                return type_node
        return types[0]

    @staticmethod
    def _symbols(ast_tree: dict[str, Any]) -> dict[str, Any]:
        return {
            "types": [item["name"] for item in ast_tree["types"]],
            "methods": [method["name"] for item in ast_tree["types"] for method in item.get("methods", [])],
            "fields": [field["name"] for item in ast_tree["types"] for field in item.get("fields", [])],
            "constructors": [ctor["name"] for item in ast_tree["types"] for ctor in item.get("constructors", [])],
        }

    @staticmethod
    def _classify(path: Path, primary_type: dict[str, Any], ast_tree: dict[str, Any]) -> str:
        if ast_tree.get("source_set") == "test":
            return "test"
        type_kind = primary_type.get("kind", "unknown")
        if type_kind in {"class", "interface", "enum", "record", "annotation"}:
            return f"java_{type_kind}"
        if not ast_tree.get("types"):
            return "java_compilation_unit"
        return "java_type"

    @staticmethod
    def _source_set(path: Path) -> str:
        parts = path.parts
        if "src" in parts:
            for index, part in enumerate(parts):
                if part == "src" and index + 1 < len(parts):
                    candidate = parts[index + 1]
                    if candidate in {"main", "test", "integrationTest"}:
                        return candidate
        if path.name.endswith("Test.java") or path.name.endswith("Tests.java"):
            return "test"
        return "unknown"

    @staticmethod
    def _summary(kind: str, ast_tree: dict[str, Any]) -> str:
        type_count = len(ast_tree["types"])
        method_count = sum(len(item.get("methods", [])) for item in ast_tree["types"])
        field_count = sum(len(item.get("fields", [])) for item in ast_tree["types"])
        parse_status = "with parse errors" if ast_tree.get("has_error") else "parsed"
        return f"{kind} file {parse_status}: {type_count} type(s), {method_count} method(s), {field_count} field(s)"

    @staticmethod
    def _extract_dependencies(ast_tree: dict[str, Any]) -> list[str]:
        deps = set()
        package = ast_tree.get("package", "")
        root_package = ".".join(package.split(".")[:3]) if package else ""
        for item in ast_tree["imports"]:
            import_name = item["name"]
            if root_package and import_name.startswith(root_package):
                deps.add(import_name.rsplit(".", 1)[-1].replace("*", ""))
        for type_node in ast_tree["types"]:
            for field in type_node.get("fields", []):
                deps.add(JavaProjectAnalyzer._simple_type(field["type"]))
            for constructor in type_node.get("constructors", []):
                for parameter in constructor.get("parameters", []):
                    deps.add(JavaProjectAnalyzer._simple_type(parameter["type"]))
            for method in type_node.get("methods", []):
                deps.add(JavaProjectAnalyzer._simple_type(method["return_type"]))
                for parameter in method.get("parameters", []):
                    deps.add(JavaProjectAnalyzer._simple_type(parameter["type"]))
        return sorted(dep for dep in deps if dep and dep not in JavaProjectAnalyzer._primitive_and_standard_types())

    @staticmethod
    def _simple_type(type_name: str) -> str:
        cleaned = re.sub(r"<.*>", "", type_name)
        cleaned = cleaned.replace("[]", "").replace("...", "")
        return cleaned.rsplit(".", 1)[-1].strip()

    @staticmethod
    def _primitive_and_standard_types() -> set[str]:
        return {
            "boolean",
            "byte",
            "char",
            "double",
            "float",
            "int",
            "long",
            "short",
            "void",
            "Boolean",
            "Byte",
            "Character",
            "Double",
            "Float",
            "Integer",
            "Long",
            "Short",
            "String",
            "Object",
            "List",
            "Set",
            "Map",
            "Collection",
            "Optional",
            "LocalDate",
            "LocalDateTime",
        }

    def _name(self, node, source_bytes: bytes) -> str:
        name_node = self._field(node, "name") or self._first_child(node, {"identifier", "type_identifier"})
        return self._text(name_node, source_bytes) if name_node else ""

    @staticmethod
    def _field(node, name: str):
        if not node:
            return None
        return node.child_by_field_name(name)

    def _first_child(self, node, kinds: set[str]):
        for child in self._children(node):
            if self._kind(child) in kinds:
                return child
        return None

    def _first_descendant(self, node, kinds: set[str]):
        for child in self._walk(node):
            if self._kind(child) in kinds:
                return child
        return None

    def _walk(self, node):
        if not node:
            return
        yield node
        for child in self._children(node):
            yield from self._walk(child)

    @staticmethod
    def _children(node) -> list[Any]:
        if not node:
            return []
        return [node.child(index) for index in range(node.child_count())]

    @staticmethod
    def _kind(node) -> str:
        return node.kind()

    @staticmethod
    def _text(node, source_bytes: bytes) -> str:
        if not node:
            return ""
        return source_bytes[node.start_byte() : node.end_byte()].decode("utf-8", errors="replace")

    @staticmethod
    def _start_line(node) -> int:
        return node.start_position().row + 1

    @staticmethod
    def _end_line(node) -> int:
        return node.end_position().row + 1

    @staticmethod
    def _is_resource_file(path: Path) -> bool:
        normalized = path.as_posix()
        return "/src/main/resources/" in normalized or path.suffix in {".html", ".css", ".js", ".properties", ".xml", ".yaml", ".yml"}

    @staticmethod
    def _file_category(path: Path) -> str:
        normalized = path.as_posix()
        if path.suffix == ".java":
            if "/src/test/" in normalized:
                return "java_test"
            return "java_source"
        if path.name in {"pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"}:
            return "build_file"
        if "/src/main/resources/" in normalized:
            return "resource"
        if path.suffix in {".html", ".css", ".js"}:
            return "web_asset"
        if path.suffix in {".properties", ".yaml", ".yml", ".xml"}:
            return "config"
        return "other"

    @classmethod
    def _build_info(cls, root: Path) -> dict[str, Any]:
        build_tool = cls._detect_build_tool(root)
        build_files = cls()._detect_build_files(root)
        return {
            "build_tool": build_tool,
            "build_files": build_files,
            "java_version": cls._detect_java_version(root),
            "language_version": cls._detect_java_version(root),
            "framework_hints": cls._detect_frameworks(root),
        }

    @staticmethod
    def _detect_java_version(root: Path) -> str:
        candidates = [root / "pom.xml", root / "build.gradle", root / "build.gradle.kts"]
        text = "\n".join(read_text(path, max_chars=30000) for path in candidates if path.exists())
        patterns = [
            r"<maven\.compiler\.release>([^<]+)</maven\.compiler\.release>",
            r"<maven\.compiler\.source>([^<]+)</maven\.compiler\.source>",
            r"<java\.version>([^<]+)</java\.version>",
            r"sourceCompatibility\s*=\s*['\"]?([^'\"\n]+)",
            r"JavaVersion\.VERSION_([0-9_]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).replace("_", ".").strip()
        return "unknown"

    @staticmethod
    def _detect_build_tool(root: Path) -> str:
        if (root / "pom.xml").exists():
            return "maven"
        if (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
            return "gradle"
        if (root / "BUILD").exists() or (root / "WORKSPACE").exists():
            return "bazel"
        return "unknown"

    @staticmethod
    def _detect_frameworks(root: Path) -> list[str]:
        text = ""
        for candidate in [
            root / "pom.xml",
            root / "build.gradle",
            root / "build.gradle.kts",
            root / "settings.gradle",
            root / "settings.gradle.kts",
        ]:
            if candidate.exists():
                text += "\n" + read_text(candidate, max_chars=30000)
        hints = []
        for token, name in [
            ("spring-boot", "Spring Boot"),
            ("spring-boot-starter-web", "Spring MVC REST"),
            ("spring-boot-starter-data-jpa", "Spring Data JPA"),
            ("thymeleaf", "Thymeleaf"),
            ("h2database", "H2 Database"),
            ("junit", "JUnit"),
            ("mockito", "Mockito"),
            ("jakarta.persistence", "Jakarta Persistence"),
            ("javax.persistence", "Javax Persistence"),
            ("quarkus", "Quarkus"),
            ("micronaut", "Micronaut"),
            ("vertx", "Vert.x"),
            ("hibernate", "Hibernate"),
        ]:
            if token in text:
                hints.append(name)
        return hints
