from __future__ import annotations

import os
import subprocess
from pathlib import Path

from src.validation.base import ValidationResult


class JavaValidator:
    def validate(self, target_root: Path, commands: list[str] | None = None) -> list[ValidationResult]:
        commands = commands or self._default_commands(target_root)
        env = os.environ.copy()
        java_home = self._detect_java_home()
        if java_home:
            env["JAVA_HOME"] = str(java_home)
            env["PATH"] = f"{java_home / 'bin'}:{env.get('PATH', '')}"
        results = []
        for command in commands:
            completed = subprocess.run(
                command,
                cwd=target_root,
                shell=True,
                text=True,
                capture_output=True,
                timeout=180,
                env=env,
            )
            results.append(
                ValidationResult(
                    command=command,
                    returncode=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                )
            )
        return results

    @staticmethod
    def _default_commands(target_root: Path) -> list[str]:
        if (target_root / "pom.xml").exists():
            return ["mvn -q test"]
        if (target_root / "build.gradle").exists() or (target_root / "build.gradle.kts").exists():
            return ["./gradlew test"]
        return ["find src/main/java -name '*.java' -print0 | xargs -0 javac -d /tmp/repo-code-translation-java-classes"]

    @staticmethod
    def _detect_java_home() -> Path | None:
        configured = os.environ.get("JAVA_PATH") or os.environ.get("JAVA_HOME")
        if configured and (Path(configured) / "bin" / "java").exists():
            return Path(configured)
        return None
