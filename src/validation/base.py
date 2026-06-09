from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValidationResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0
