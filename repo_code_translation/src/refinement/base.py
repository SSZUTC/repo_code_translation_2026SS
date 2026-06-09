from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FileRefinementTarget:
    path: str
    reason: str
