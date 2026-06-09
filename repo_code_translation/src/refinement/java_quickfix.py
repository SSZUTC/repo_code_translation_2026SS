from __future__ import annotations

import re
from pathlib import Path

from src.common.io_utils import read_text, write_text


class JavaCompileQuickFixer:
    JAVA_TEST_PATH_RE = re.compile(r"(?P<path>src/test/java/[A-Za-z0-9_./-]+\.java)")

    def apply(self, validation_report: list[dict], target_root: Path) -> list[str]:
        failure_text = self._failure_text(validation_report)
        if not failure_text.strip():
            return []

        changed: list[str] = []
        for relative_path in sorted(set(self.JAVA_TEST_PATH_RE.findall(failure_text))):
            path = target_root / relative_path
            if not path.is_file():
                continue
            original = read_text(path, max_chars=200000)
            updated = original
            if "cannot find symbol\n  symbol:   class List" in failure_text or "symbol:   class List" in failure_text:
                updated = self._ensure_import(updated, "java.util.List")
            if "java.lang.String[] cannot be converted to java.util.List" in failure_text:
                updated = self._convert_string_arrays_to_lists(updated)
            if updated != original:
                write_text(path, updated)
                changed.append(relative_path)
        return changed

    @staticmethod
    def _failure_text(validation_report: list[dict]) -> str:
        return "\n\n".join(
            f"$ {item.get('command', '')}\n{item.get('stdout', '')}\n{item.get('stderr', '')}"
            for item in validation_report
            if not item.get("ok")
        )

    @staticmethod
    def _ensure_import(content: str, import_line: str) -> str:
        line = f"import {import_line};"
        if line in content:
            return content
        package_match = re.search(r"^package\s+[^;]+;\s*$", content, flags=re.MULTILINE)
        if package_match:
            insert_at = package_match.end()
            return content[:insert_at] + "\n\n" + line + content[insert_at:]
        return line + "\n" + content

    def _convert_string_arrays_to_lists(self, content: str) -> str:
        content = self._ensure_import(content, "java.util.List")
        content = re.sub(
            r"String\[\]\s+(\w+)\s*=\s*\{([^}]*)\};",
            lambda match: f"List<String> {match.group(1)} = java.util.Arrays.asList({match.group(2).strip()});",
            content,
        )
        content = re.sub(r"new\s+String\[\]\s*\{\s*\}", "java.util.Collections.emptyList()", content)
        content = re.sub(r"arrayContains\((\w+),\s*([^)]+)\)", r"\1.contains(\2)", content)
        return content
