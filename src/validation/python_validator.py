from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import sys
from pathlib import Path

from src.validation.base import ValidationResult


class PythonValidator:
    def validate(self, target_root: Path, commands: list[str] | None = None) -> list[ValidationResult]:
        commands = commands or ["python -m compileall app", "python -m pytest"]
        setup_result = self._ensure_project_venv(target_root)
        if not setup_result.ok:
            return [setup_result]
        env = self._python_env(target_root)
        results = [setup_result]
        for command in commands:
            executable_command = self._resolve_python_command(target_root, command)
            completed = subprocess.run(
                executable_command,
                cwd=target_root,
                shell=True,
                text=True,
                capture_output=True,
                timeout=120,
                env=env,
            )
            results.append(
                ValidationResult(
                    command=executable_command,
                    returncode=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                )
            )
        return results

    @classmethod
    def _ensure_project_venv(cls, target_root: Path) -> ValidationResult:
        venv_python = cls._project_venv_python(target_root)
        venv_root = venv_python.parent.parent
        requirements = target_root / "requirements.txt"
        requirements_hash = cls._requirements_hash(requirements)
        stamp = venv_root / ".requirements.sha256"

        if venv_python.exists() and stamp.exists() and stamp.read_text(encoding="utf-8").strip() == requirements_hash:
            return ValidationResult(
                command=f"{shlex.quote(str(venv_python))} -m pip install -r requirements.txt",
                returncode=0,
                stdout="Project venv already prepared; requirements unchanged.\n",
                stderr="",
            )

        if not venv_python.exists():
            create_command = [sys.executable, "-m", "venv", str(venv_root)]
            created = subprocess.run(create_command, cwd=target_root, text=True, capture_output=True, timeout=180)
            if created.returncode != 0:
                return ValidationResult(
                    command=" ".join(shlex.quote(item) for item in create_command),
                    returncode=created.returncode,
                    stdout=created.stdout,
                    stderr=created.stderr,
                )

        if not requirements.exists():
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(requirements_hash, encoding="utf-8")
            return ValidationResult(
                command=f"{shlex.quote(str(venv_python))} -m pip install -r requirements.txt",
                returncode=0,
                stdout="No requirements.txt found; project venv created without dependency install.\n",
                stderr="",
            )

        install_command = f"{shlex.quote(str(venv_python))} -m pip install -r requirements.txt"
        installed = subprocess.run(
            install_command,
            cwd=target_root,
            shell=True,
            text=True,
            capture_output=True,
            timeout=300,
        )
        if installed.returncode == 0:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(requirements_hash, encoding="utf-8")
        return ValidationResult(
            command=install_command,
            returncode=installed.returncode,
            stdout=installed.stdout,
            stderr=installed.stderr,
        )

    @classmethod
    def _resolve_python_command(cls, target_root: Path, command: str) -> str:
        executable = shlex.quote(str(cls._project_venv_python(target_root)))
        for prefix in ("python3 ", "python "):
            if command.startswith(prefix):
                return f"{executable} {command[len(prefix):]}"
        return command

    @classmethod
    def _python_env(cls, target_root: Path) -> dict[str, str]:
        env = os.environ.copy()
        python = cls._project_venv_python(target_root)
        venv_root = python.parent.parent
        env["VIRTUAL_ENV"] = str(venv_root)
        env["PATH"] = f"{python.parent}:{env.get('PATH', '')}"
        return env

    @staticmethod
    def _project_venv_python(target_root: Path) -> Path:
        return target_root / ".venv" / "bin" / "python"

    @staticmethod
    def _requirements_hash(path: Path) -> str:
        if not path.exists():
            return "no-requirements"
        return hashlib.sha256(path.read_bytes()).hexdigest()
