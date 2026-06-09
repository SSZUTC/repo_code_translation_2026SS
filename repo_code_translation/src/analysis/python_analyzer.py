from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from src.analysis.base import BaseProjectAnalyzer
from src.common.models import JavaFileInfo, RepoAnalysis, rel_path
from src.common.io_utils import read_text
from src.prompts.python_project_semantic_analysis import (
    PYTHON_PROJECT_SEMANTIC_ANALYSIS_SYSTEM_PROMPT,
    build_python_project_semantic_analysis_prompt,
)


class PythonProjectAnalyzer(BaseProjectAnalyzer):
    ignored_dirs = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "site-packages",
    }

    def analyze(self, source_root: Path) -> RepoAnalysis:
        source_root = source_root.resolve()
        python_files = [
            path
            for path in sorted(source_root.rglob("*.py"))
            if not self._is_ignored(path)
        ]
        files = [self._analyze_python_file(path, source_root) for path in python_files]
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
        return "python.ast"

    def extract_project_semantics_prompt(self, analysis: RepoAnalysis) -> str:
        return build_python_project_semantic_analysis_prompt(analysis)

    def project_semantics_system_prompt(self) -> str:
        return PYTHON_PROJECT_SEMANTIC_ANALYSIS_SYSTEM_PROMPT

    def _analyze_python_file(self, path: Path, root: Path) -> JavaFileInfo:
        text = read_text(path, max_chars=120000)
        module = rel_path(path, root).removesuffix(".py").replace("/", ".")
        ast_tree = self._build_ast_tree(path, root, text)
        class_names = [item["name"] for item in ast_tree.get("classes", [])]
        function_names = [item["name"] for item in ast_tree.get("functions", [])]
        imports = [item["name"] for item in ast_tree.get("imports", [])]
        assignments = [item["name"] for item in ast_tree.get("assignments", [])]
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.append(node.module or "")
        except SyntaxError:
            pass

        class_name = class_names[0] if class_names else self._module_class_name(path)
        kind = self._classify(path, ast_tree)
        return JavaFileInfo(
            path=rel_path(path, root),
            package=module,
            class_name=class_name,
            kind=kind,
            imports=sorted(set(item for item in imports if item)),
            annotations=[],
            methods=function_names,
            dependencies=self._extract_local_dependencies(imports),
            symbols={
                "classes": class_names,
                "functions": function_names,
                "assignments": assignments,
            },
            ast_tree=ast_tree,
            summary=self._summary(kind, ast_tree),
        )

    def _build_ast_tree(self, path: Path, root: Path, source: str) -> dict[str, Any]:
        relative = rel_path(path, root)
        base = {
            "node_type": "Module",
            "parser": "python.ast",
            "path": relative,
            "module": relative.removesuffix(".py").replace("/", "."),
            "source_set": self._source_set(path),
            "imports": [],
            "classes": [],
            "functions": [],
            "assignments": [],
            "has_error": False,
            "source_lines": source.count("\n") + 1,
        }
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            base["has_error"] = True
            base["error"] = {
                "message": exc.msg,
                "line": exc.lineno,
                "offset": exc.offset,
            }
            return base

        for node in tree.body:
            if isinstance(node, ast.Import):
                base["imports"].extend(self._import_nodes(node))
            elif isinstance(node, ast.ImportFrom):
                base["imports"].extend(self._import_from_nodes(node))
            elif isinstance(node, ast.ClassDef):
                base["classes"].append(self._class_node(node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                base["functions"].append(self._function_node(node))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                base["assignments"].extend(self._assignment_nodes(node))
        base["raw_tree"] = ast.dump(tree, include_attributes=False)
        return base

    def _class_node(self, node: ast.ClassDef) -> dict[str, Any]:
        fields = []
        methods = []
        nested_classes = []
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(self._function_node(child))
            elif isinstance(child, ast.ClassDef):
                nested_classes.append(self._class_node(child))
            elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                fields.extend(self._assignment_nodes(child))
        return {
            "node_type": "ClassDef",
            "name": node.name,
            "bases": [self._expr_text(item) for item in node.bases],
            "decorators": [self._expr_text(item) for item in node.decorator_list],
            "fields": fields,
            "methods": methods,
            "nested_classes": nested_classes,
            "span": {"start_line": getattr(node, "lineno", None), "end_line": getattr(node, "end_lineno", None)},
        }

    def _function_node(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any]:
        return {
            "node_type": "AsyncFunctionDef" if isinstance(node, ast.AsyncFunctionDef) else "FunctionDef",
            "name": node.name,
            "parameters": self._parameters(node.args),
            "decorators": [self._expr_text(item) for item in node.decorator_list],
            "returns": self._expr_text(node.returns) if node.returns else "",
            "is_async": isinstance(node, ast.AsyncFunctionDef),
            "span": {"start_line": getattr(node, "lineno", None), "end_line": getattr(node, "end_lineno", None)},
        }

    @staticmethod
    def _parameters(args: ast.arguments) -> list[dict[str, str]]:
        parameters = []
        positional = list(args.posonlyargs) + list(args.args)
        defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
        for arg, default in zip(positional, defaults):
            parameters.append(
                {
                    "name": arg.arg,
                    "annotation": PythonProjectAnalyzer._expr_text(arg.annotation) if arg.annotation else "",
                    "has_default": default is not None,
                }
            )
        if args.vararg:
            parameters.append({"name": f"*{args.vararg.arg}", "annotation": PythonProjectAnalyzer._expr_text(args.vararg.annotation) if args.vararg.annotation else "", "has_default": False})
        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            parameters.append(
                {
                    "name": arg.arg,
                    "annotation": PythonProjectAnalyzer._expr_text(arg.annotation) if arg.annotation else "",
                    "has_default": default is not None,
                }
            )
        if args.kwarg:
            parameters.append({"name": f"**{args.kwarg.arg}", "annotation": PythonProjectAnalyzer._expr_text(args.kwarg.annotation) if args.kwarg.annotation else "", "has_default": False})
        return parameters

    @staticmethod
    def _assignment_nodes(node: ast.Assign | ast.AnnAssign) -> list[dict[str, Any]]:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        annotation = PythonProjectAnalyzer._expr_text(node.annotation) if isinstance(node, ast.AnnAssign) and node.annotation else ""
        assignments = []
        for target in targets:
            name = PythonProjectAnalyzer._target_name(target)
            if not name:
                continue
            assignments.append(
                {
                    "node_type": "Assign",
                    "name": name,
                    "annotation": annotation,
                    "span": {"start_line": getattr(node, "lineno", None), "end_line": getattr(node, "end_lineno", None)},
                }
            )
        return assignments

    @staticmethod
    def _target_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return PythonProjectAnalyzer._expr_text(node)
        return ""

    @staticmethod
    def _import_nodes(node: ast.Import) -> list[dict[str, Any]]:
        return [
            {
                "node_type": "Import",
                "name": alias.name,
                "alias": alias.asname or "",
                "line": getattr(node, "lineno", None),
            }
            for alias in node.names
        ]

    @staticmethod
    def _import_from_nodes(node: ast.ImportFrom) -> list[dict[str, Any]]:
        module = "." * node.level + (node.module or "")
        return [
            {
                "node_type": "ImportFrom",
                "name": module,
                "symbol": alias.name,
                "alias": alias.asname or "",
                "line": getattr(node, "lineno", None),
            }
            for alias in node.names
        ]

    @staticmethod
    def _expr_text(node: ast.AST | None) -> str:
        if node is None:
            return ""
        try:
            return ast.unparse(node)
        except Exception:
            return node.__class__.__name__

    @staticmethod
    def _module_class_name(path: Path) -> str:
        parts = [part for part in path.with_suffix("").parts if part not in {"app", "src", "tests"}]
        stem = parts[-1] if parts else path.stem
        return "".join(piece.capitalize() for piece in stem.replace("-", "_").split("_")) or "Application"

    @staticmethod
    def _classify(path: Path, ast_tree: dict[str, Any]) -> str:
        if ast_tree.get("source_set") == "test":
            return "test"
        if ast_tree.get("classes"):
            return "python_class_module"
        if ast_tree.get("functions"):
            return "python_function_module"
        return "python_module"

    @staticmethod
    def _extract_local_dependencies(imports: list[str]) -> list[str]:
        deps = []
        for import_name in imports:
            if import_name.startswith(("app.", "src.")):
                deps.append(import_name.rsplit(".", 1)[-1])
        return sorted(set(deps))

    def _detect_build_tool(self, root: Path) -> str:
        if (root / "pyproject.toml").exists():
            return "pyproject"
        if (root / "requirements.txt").exists():
            return "requirements.txt"
        return "unknown"

    @staticmethod
    def _source_set(path: Path) -> str:
        parts = path.parts
        if "tests" in parts or path.name.startswith("test_") or path.name.endswith("_test.py"):
            return "test"
        return "main"

    def _detect_frameworks(self, root: Path) -> list[str]:
        text = ""
        for candidate in [root / "requirements.txt", root / "pyproject.toml"]:
            if candidate.exists():
                text += read_text(candidate, max_chars=30000).lower()
        hints = []
        for token, name in [
            ("flask", "Flask"),
            ("fastapi", "FastAPI"),
            ("sqlalchemy", "SQLAlchemy"),
            ("pydantic", "Pydantic"),
            ("pytest", "pytest"),
            ("django", "Django"),
        ]:
            if token in text:
                hints.append(name)
        return hints

    @staticmethod
    def _summary(kind: str, ast_tree: dict[str, Any]) -> str:
        parse_status = "with parse errors" if ast_tree.get("has_error") else "parsed"
        class_count = len(ast_tree.get("classes", []))
        function_count = len(ast_tree.get("functions", []))
        assignment_count = len(ast_tree.get("assignments", []))
        method_count = sum(len(item.get("methods", [])) for item in ast_tree.get("classes", []))
        return (
            f"{kind} file {parse_status}: {class_count} class(es), "
            f"{function_count} top-level function(s), {method_count} method(s), {assignment_count} assignment(s)"
        )

    @staticmethod
    def _file_category(path: Path) -> str:
        if path.suffix == ".py":
            if PythonProjectAnalyzer._source_set(path) == "test":
                return "python_test"
            return "python_source"
        if path.name in {"pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile", "poetry.lock"}:
            return "build_file"
        if path.suffix in {".html", ".css", ".js"}:
            return "web_asset"
        if path.suffix in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".properties"}:
            return "config"
        return "other"

    @classmethod
    def _build_info(cls, root: Path) -> dict[str, Any]:
        analyzer = cls()
        return {
            "build_tool": analyzer._detect_build_tool(root),
            "build_files": analyzer._detect_build_files(root),
            "python_version": cls._detect_python_version(root),
            "framework_hints": analyzer._detect_frameworks(root),
        }

    @staticmethod
    def _detect_python_version(root: Path) -> str:
        candidates = [root / "pyproject.toml", root / "runtime.txt", root / "Pipfile"]
        text = "\n".join(read_text(path, max_chars=30000) for path in candidates if path.exists())
        patterns = [
            r"requires-python\s*=\s*['\"]([^'\"]+)['\"]",
            r"python_version\s*=\s*['\"]([^'\"]+)['\"]",
            r"python_full_version\s*=\s*['\"]([^'\"]+)['\"]",
            r"python-([0-9.]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return "unknown"
