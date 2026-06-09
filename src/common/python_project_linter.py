from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.common.io_utils import read_text, write_text


THIRD_PARTY_REQUIREMENTS = {
    "dateutil": "python-dateutil>=2.8,<3",
    "dynaconf": "dynaconf>=3,<4",
    "fastapi": "fastapi>=0.110,<1",
    "httpx": "httpx>=0.27,<1",
    "multipart": "python-multipart>=0.0.9,<1",
    "pydantic": "pydantic>=2,<3",
    "pytest": "pytest>=8,<9",
    "python-multipart": "python-multipart>=0.0.9,<1",
    "sqlalchemy": "sqlalchemy>=1.4,<3",
    "uvicorn": "uvicorn>=0.17,<1",
    "yaml": "PyYAML>=6,<7",
}


@dataclass
class ModuleInfo:
    module: str
    path: Path
    exports: set[str] = field(default_factory=set)
    imports: list[tuple[str, list[str]]] = field(default_factory=list)


@dataclass
class LintResult:
    created_files: list[str] = field(default_factory=list)
    updated_files: list[str] = field(default_factory=list)
    unresolved_imports: list[str] = field(default_factory=list)
    added_requirements: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.updated_files or self.added_requirements)

    def to_dict(self) -> dict:
        return {
            "created_files": self.created_files,
            "updated_files": self.updated_files,
            "unresolved_imports": self.unresolved_imports,
            "added_requirements": self.added_requirements,
            "changed": self.changed,
        }


class PythonProjectLinter:
    """Import-level linter for generated Python projects.

    This linter intentionally does not repair business logic, framework behavior,
    tests, model constructors, or runtime semantics. It only checks whether local
    imports resolve and whether known third-party imports are present in
    requirements.txt.
    """

    def lint(self, project_root: Path) -> LintResult:
        result = LintResult()
        modules = self._scan_modules(project_root)
        local_roots = self._local_roots(modules)
        self._collect_unresolved_local_imports(modules, local_roots, result)
        self._update_requirements(project_root, modules, local_roots, result)
        return result

    def _scan_modules(self, project_root: Path) -> dict[str, ModuleInfo]:
        modules = {}
        for path in sorted(project_root.rglob("*.py")):
            if self._ignore(path):
                continue
            module = self._module_name(project_root, path)
            info = ModuleInfo(module=module, path=path)
            try:
                tree = ast.parse(read_text(path), filename=str(path))
            except SyntaxError:
                modules[module] = info
                continue

            for node in tree.body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    info.exports.add(node.name)
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    for target in targets:
                        if isinstance(target, ast.Name):
                            info.exports.add(target.id)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name != "*":
                            info.exports.add(alias.asname or alias.name)

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        info.imports.append((alias.name, []))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    symbols = [alias.name for alias in node.names if alias.name != "*"]
                    info.imports.append((node.module, symbols))

            modules[module] = info
        return modules

    def _collect_unresolved_local_imports(
        self,
        modules: dict[str, ModuleInfo],
        local_roots: set[str],
        result: LintResult,
    ) -> None:
        unresolved = []
        for info in sorted(modules.values(), key=lambda item: item.module):
            for module_name, symbols in info.imports:
                if not self._is_local_module(module_name, local_roots):
                    continue
                provider = modules.get(module_name)
                if provider is None:
                    unresolved.append(f"{info.module}: missing module {module_name}")
                    continue
                for symbol in sorted(symbol for symbol in symbols if symbol not in provider.exports):
                    unresolved.append(f"{info.module}: missing symbol {symbol} from {module_name}")
        result.unresolved_imports.extend(sorted(set(unresolved)))

    def _update_requirements(
        self,
        project_root: Path,
        modules: dict[str, ModuleInfo],
        local_roots: set[str],
        result: LintResult,
    ) -> None:
        requirements_path = project_root / "requirements.txt"
        existing_lines = []
        if requirements_path.exists():
            existing_lines = [
                line.strip()
                for line in read_text(requirements_path).splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]

        existing_names = {self._requirement_name(line) for line in existing_lines}
        additions = []
        for root in sorted(self._third_party_import_roots(modules, local_roots)):
            requirement = THIRD_PARTY_REQUIREMENTS.get(root)
            if requirement and self._requirement_name(requirement) not in existing_names:
                additions.append(requirement)
                existing_names.add(self._requirement_name(requirement))
        for requirement in self._runtime_requirements(project_root):
            if self._requirement_name(requirement) not in existing_names:
                additions.append(requirement)
                existing_names.add(self._requirement_name(requirement))

        if additions:
            write_text(requirements_path, "\n".join(existing_lines + additions) + "\n")
            result.updated_files.append("requirements.txt")
            result.added_requirements.extend(additions)

    def _third_party_import_roots(self, modules: dict[str, ModuleInfo], local_roots: set[str]) -> set[str]:
        roots = set()
        stdlib = getattr(sys, "stdlib_module_names", set())
        for info in modules.values():
            for module_name, _ in info.imports:
                root = module_name.split(".", 1)[0]
                if root in local_roots or root in stdlib:
                    continue
                roots.add(root)
        return roots

    def _runtime_requirements(self, project_root: Path) -> set[str]:
        requirements = set()
        for path in sorted(project_root.rglob("*.py")):
            if self._ignore(path):
                continue
            text = read_text(path)
            if self._uses_fastapi_multipart_features(text):
                requirements.add(THIRD_PARTY_REQUIREMENTS["python-multipart"])
        return requirements

    @staticmethod
    def _uses_fastapi_multipart_features(text: str) -> bool:
        imports_form_helpers = bool(
            re.search(r"from\s+fastapi\s+import\s+.*\b(Form|File|UploadFile)\b", text)
            or re.search(r"import\s+fastapi\b", text)
        )
        calls_form_helpers = bool(re.search(r"\b(Form|File)\s*\(", text) or "UploadFile" in text)
        return imports_form_helpers and calls_form_helpers

    @staticmethod
    def _local_roots(modules: dict[str, ModuleInfo]) -> set[str]:
        return {module.split(".", 1)[0] for module in modules}

    @staticmethod
    def _is_local_module(module_name: str, local_roots: set[str]) -> bool:
        return module_name.split(".", 1)[0] in local_roots

    @staticmethod
    def _module_name(project_root: Path, path: Path) -> str:
        relative = path.relative_to(project_root).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)

    @staticmethod
    def _ignore(path: Path) -> bool:
        ignored = {"__pycache__", ".pytest_cache", ".venv", "venv"}
        return any(part in ignored for part in path.parts)

    @staticmethod
    def _requirement_name(line: str) -> str:
        return re.split(r"[<>=!~\[]", line, 1)[0].strip().lower()
