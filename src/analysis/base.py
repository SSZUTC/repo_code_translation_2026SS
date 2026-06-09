from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.io_utils import iter_text_files
from src.common.models import RepoAnalysis, rel_path


class BaseProjectAnalyzer:
    ignored_dirs = {
        ".git",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
        "site-packages",
        "target",
    }

    def _is_ignored(self, path: Path) -> bool:
        return any(part in self.ignored_dirs for part in path.parts)

    def extract_file_tree(self, root: Path) -> dict[str, Any]:
        return self._build_file_tree(root)

    def extract_ast_tree(self, analysis: RepoAnalysis) -> dict[str, Any]:
        return {
            "parser": self.ast_parser_name(),
            "files": [
                {
                    "path": file_info.path,
                    "kind": file_info.kind,
                    "module": file_info.package,
                    "class_name": file_info.class_name,
                    "ast_tree": file_info.ast_tree,
                }
                for file_info in analysis.files
            ],
        }

    def extract_project_semantics_prompt(self, analysis: RepoAnalysis) -> str:
        raise NotImplementedError

    def project_semantics_system_prompt(self) -> str:
        raise NotImplementedError

    def ast_parser_name(self) -> str:
        return "unknown"

    def _resource_paths(self, source_root: Path) -> list[str]:
        return [
            rel_path(path, source_root)
            for path in iter_text_files(source_root)
            if self._is_resource_file(path) and not self._is_ignored(path)
        ]

    def _build_file_tree(self, root: Path) -> dict[str, Any]:
        files = []
        tree: dict[str, Any] = {}
        for path in sorted(root.rglob("*")):
            if path.is_dir() or self._is_ignored(path):
                continue
            relative = rel_path(path, root)
            file_info = {
                "path": relative,
                "extension": path.suffix,
                "category": self._file_category(path),
                "size_bytes": path.stat().st_size,
            }
            files.append(file_info)
            cursor = tree
            parts = relative.split("/")
            for part in parts[:-1]:
                cursor = cursor.setdefault(part, {})
            cursor[parts[-1]] = file_info["category"]
        return {
            "root": str(root),
            "file_count": len(files),
            "tree": tree,
            "files": files,
        }

    def _build_info(self, root: Path) -> dict[str, Any]:
        return {
            "build_tool": self._detect_build_tool(root),
            "build_files": self._detect_build_files(root),
            "language_version": self._detect_language_version(root),
            "framework_hints": self._detect_frameworks(root),
        }

    def _detect_build_files(self, root: Path) -> list[str]:
        return [
            rel_path(path, root)
            for path in sorted(root.iterdir())
            if path.is_file() and self._file_category(path) == "build_file"
        ]

    def _is_resource_file(self, path: Path) -> bool:
        return path.suffix in {".html", ".css", ".js", ".json", ".yaml", ".yml", ".properties", ".xml", ".toml"}

    def _file_category(self, path: Path) -> str:
        return "other"

    def _detect_build_tool(self, root: Path) -> str:
        return "unknown"

    def _detect_frameworks(self, root: Path) -> list[str]:
        return []

    def _detect_language_version(self, root: Path) -> str:
        return "unknown"
