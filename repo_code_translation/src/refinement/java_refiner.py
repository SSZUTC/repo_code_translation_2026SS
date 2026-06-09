from __future__ import annotations

import re
from pathlib import Path

from src.refinement.base import FileRefinementTarget


class JavaValidationFailureAnalyzer:
    JAVA_FILE_RE = re.compile(r"(?P<path>(?:src/(?:main|test)/java)/[A-Za-z0-9_./-]+\.java)")
    ABS_JAVA_FILE_RE = re.compile(r"(?P<path>/[^\s:'\"]+/(?:src/(?:main|test)/java)/[A-Za-z0-9_./-]+\.java)")
    POM_RE = re.compile(r"\bpom\.xml\b")

    def select_targets(self, validation_report: list[dict], target_root: Path, limit: int = 6) -> list[FileRefinementTarget]:
        failed_text = "\n\n".join(
            f"$ {item.get('command', '')}\n{item.get('stdout', '')}\n{item.get('stderr', '')}"
            for item in validation_report
            if not item.get("ok")
        )
        if not failed_text.strip():
            return []

        candidates: list[FileRefinementTarget] = []
        for path in self._paths_from_output(failed_text, target_root):
            candidates.append(FileRefinementTarget(path, "referenced in Java validation failure output"))
        if self.POM_RE.search(failed_text) and (target_root / "pom.xml").is_file():
            candidates.append(FileRefinementTarget("pom.xml", "build file referenced in validation failure output"))
        if not candidates:
            for path in sorted(target_root.rglob("*.java"))[:limit]:
                candidates.append(
                    FileRefinementTarget(path.relative_to(target_root).as_posix(), "fallback Java source file after validation failure")
                )
        return self._dedupe_existing(candidates, target_root)[:limit]

    def excerpt_for_file(self, validation_report: list[dict], file_path: str, max_chars: int = 12000) -> str:
        blocks = []
        needle = file_path
        basename = Path(file_path).name
        for item in validation_report:
            if item.get("ok"):
                continue
            text = f"$ {item.get('command', '')}\n{item.get('stdout', '')}\n{item.get('stderr', '')}"
            if needle in text or basename in text or (file_path == "pom.xml" and "pom.xml" in text):
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
        for match in self.JAVA_FILE_RE.finditer(text):
            paths.append(match.group("path"))
        for match in self.ABS_JAVA_FILE_RE.finditer(text):
            absolute = Path(match.group("path"))
            try:
                paths.append(absolute.resolve().relative_to(target_root.resolve()).as_posix())
            except ValueError:
                continue
        return paths

    @staticmethod
    def _dedupe_existing(candidates: list[FileRefinementTarget], target_root: Path) -> list[FileRefinementTarget]:
        seen = set()
        deduped = []
        for item in candidates:
            if item.path in seen:
                continue
            if not (target_root / item.path).is_file():
                continue
            seen.add(item.path)
            deduped.append(item)
        return deduped
