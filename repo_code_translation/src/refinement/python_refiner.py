from __future__ import annotations

import re
from pathlib import Path

from src.refinement.base import FileRefinementTarget


class PythonValidationFailureAnalyzer:
    PY_FILE_RE = re.compile(r"(?P<path>(?:app|tests)/[A-Za-z0-9_./-]+\.py)")
    ABS_PY_FILE_RE = re.compile(r"(?P<path>/[^\s:'\"]+/(?:app|tests)/[A-Za-z0-9_./-]+\.py)")
    MODULE_NOT_FOUND_RE = re.compile(r"No module named ['\"]([^'\"]+)['\"]")
    IMPORT_NAME_RE = re.compile(
        r"cannot import name ['\"](?P<symbol>[^'\"]+)['\"] from ['\"](?P<module>[^'\"]+)['\"]"
    )
    CLASS_INIT_RE = re.compile(r"\b(?P<class_name>[A-Z][A-Za-z0-9_]*)\.__init__\(\)")
    MAPPED_CLASS_RE = re.compile(r"mapped class (?P<class_name>[A-Z][A-Za-z0-9_]*)->")
    QUOTED_CLASS_RE = re.compile(r"['\"](?P<class_name>[A-Z][A-Za-z0-9_]*)['\"]")
    PIP_INSTALL_HINT_RE = re.compile(r"pip install (?P<package>[A-Za-z0-9_.-]+)")
    MISSING_REQUIREMENT_PATTERNS = (
        "No module named ",
        "ModuleNotFoundError",
        "ImportError",
        "requires ",
        "requires \"",
        "to be installed",
        "pip install ",
    )

    def select_targets(self, validation_report: list[dict], target_root: Path, limit: int = 6) -> list[FileRefinementTarget]:
        failed_text = "\n\n".join(
            f"$ {item.get('command', '')}\n{item.get('stdout', '')}\n{item.get('stderr', '')}"
            for item in validation_report
            if not item.get("ok")
        )
        if not failed_text.strip():
            return []

        candidates: list[FileRefinementTarget] = []

        if self._looks_like_requirements_failure(failed_text) and (target_root / "requirements.txt").is_file():
            packages = sorted(set(match.group("package") for match in self.PIP_INSTALL_HINT_RE.finditer(failed_text)))
            package_text = ", ".join(packages) if packages else "missing runtime dependency"
            candidates.append(FileRefinementTarget("requirements.txt", f"requirements problem: {package_text}"))

        for match in self.IMPORT_NAME_RE.finditer(failed_text):
            symbol = match.group("symbol")
            module_name = match.group("module")
            for path in self._paths_for_module(module_name, target_root):
                candidates.append(FileRefinementTarget(path, f"missing exported symbol {symbol} from module {module_name}"))

        for module_name in self.MODULE_NOT_FOUND_RE.findall(failed_text):
            for path in self._paths_for_missing_module(module_name, target_root):
                candidates.append(FileRefinementTarget(path, f"imports missing module {module_name}"))

        for class_name in self._class_names_from_output(failed_text):
            for path in self._paths_for_class(class_name, target_root):
                candidates.append(FileRefinementTarget(path, f"class {class_name} referenced in validation failure output"))

        for path in self._paths_from_output(failed_text, target_root):
            candidates.append(FileRefinementTarget(path, "referenced in validation failure output"))

        return self._rank_targets(self._dedupe_existing(candidates, target_root))[:limit]

    def _looks_like_requirements_failure(self, text: str) -> bool:
        if self.PIP_INSTALL_HINT_RE.search(text):
            return True
        if "python-multipart" in text:
            return True
        return any(pattern in text for pattern in self.MISSING_REQUIREMENT_PATTERNS)

    def excerpt_for_file(self, validation_report: list[dict], file_path: str, max_chars: int = 12000) -> str:
        blocks = []
        needle = file_path
        basename = Path(file_path).name
        for item in validation_report:
            if item.get("ok"):
                continue
            text = f"$ {item.get('command', '')}\n{item.get('stdout', '')}\n{item.get('stderr', '')}"
            if needle in text or basename in text:
                blocks.append(text)
        if not blocks:
            blocks = [
                f"$ {item.get('command', '')}\n{item.get('stdout', '')}\n{item.get('stderr', '')}"
                for item in validation_report
                if not item.get("ok")
            ]
        return "\n\n".join(blocks)[:max_chars]

    def _paths_from_output(self, text: str, target_root: Path) -> list[str]:
        paths = []
        for match in self.PY_FILE_RE.finditer(text):
            paths.append(match.group("path"))
        for match in self.ABS_PY_FILE_RE.finditer(text):
            absolute = Path(match.group("path"))
            try:
                paths.append(absolute.resolve().relative_to(target_root.resolve()).as_posix())
            except ValueError:
                continue
        return paths

    def _paths_for_missing_module(self, module_name: str, target_root: Path) -> list[str]:
        module_leaf = module_name.split(".")[-1]
        possible = [
            f"{module_leaf}.py",
            f"{module_leaf.replace('-', '_')}.py",
        ]
        matches = []
        for path in sorted(target_root.rglob("*.py")):
            if path.name in possible:
                matches.append(path.relative_to(target_root).as_posix())
        return matches

    @staticmethod
    def _paths_for_module(module_name: str, target_root: Path) -> list[str]:
        module_path = module_name.replace(".", "/")
        candidates = [
            target_root / f"{module_path}.py",
            target_root / module_path / "__init__.py",
        ]
        return [path.relative_to(target_root).as_posix() for path in candidates if path.is_file()]

    def _class_names_from_output(self, text: str) -> list[str]:
        names = []
        for regex in (self.CLASS_INIT_RE, self.MAPPED_CLASS_RE, self.QUOTED_CLASS_RE):
            names.extend(match.group("class_name") for match in regex.finditer(text))
        return sorted(set(names))

    @staticmethod
    def _paths_for_class(class_name: str, target_root: Path) -> list[str]:
        pattern = re.compile(rf"^\s*class\s+{re.escape(class_name)}\b", re.MULTILINE)
        matches = []
        for path in sorted(target_root.rglob("*.py")):
            if any(part in {"__pycache__", ".pytest_cache", ".venv", "venv"} for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if pattern.search(text):
                matches.append(path.relative_to(target_root).as_posix())
        return matches

    @staticmethod
    def _dedupe_existing(candidates: list[FileRefinementTarget], target_root: Path) -> list[FileRefinementTarget]:
        seen = set()
        deduped = []
        for item in candidates:
            path = item.path
            if path in seen:
                continue
            if not (target_root / path).is_file():
                continue
            seen.add(path)
            deduped.append(item)
        return deduped

    @staticmethod
    def _rank_targets(candidates: list[FileRefinementTarget]) -> list[FileRefinementTarget]:
        implementation_targets = [item for item in candidates if not item.path.startswith("tests/")]
        if implementation_targets:
            candidates = implementation_targets

        def priority(item: FileRefinementTarget) -> tuple[int, str]:
            if item.path == "requirements.txt":
                return (-1, item.path)
            if item.path.startswith("tests/"):
                return (2, item.path)
            if item.path.startswith("app/"):
                return (0, item.path)
            return (1, item.path)

        return sorted(candidates, key=priority)


ValidationFailureAnalyzer = PythonValidationFailureAnalyzer
