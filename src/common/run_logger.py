from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.common.io_utils import write_json, write_text


class RunLogger:
    def __init__(self, artifact_root: Path | None = None, verbose: bool = True):
        self.artifact_root = artifact_root.resolve() if artifact_root else None
        self.verbose = verbose
        if self.artifact_root:
            (self.artifact_root / "logs").mkdir(parents=True, exist_ok=True)
            (self.artifact_root / "analysis").mkdir(parents=True, exist_ok=True)
            (self.artifact_root / "plans").mkdir(parents=True, exist_ok=True)
            (self.artifact_root / "validation").mkdir(parents=True, exist_ok=True)

    def event(self, stage: str, message: str, **data: Any) -> None:
        payload = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "stage": stage,
            "message": message,
            "data": data,
        }
        if self.verbose:
            suffix = ""
            if data:
                visible = {key: value for key, value in data.items() if key not in {"prompt", "content"}}
                suffix = " " + json.dumps(visible, ensure_ascii=False)
            print(f"[{stage}] {message}{suffix}", flush=True)
        if self.artifact_root:
            line = json.dumps(payload, ensure_ascii=False)
            with (self.artifact_root / "logs" / "events.jsonl").open("a", encoding="utf-8") as file:
                file.write(line + "\n")
            with (self.artifact_root / "logs" / "progress.log").open("a", encoding="utf-8") as file:
                suffix = ""
                if data:
                    visible = {key: value for key, value in data.items() if key not in {"prompt", "content"}}
                    suffix = " " + json.dumps(visible, ensure_ascii=False)
                file.write(f"{payload['timestamp']} [{stage}] {message}{suffix}\n")

    def write_artifact(self, relative_path: str, data: Any) -> None:
        if not self.artifact_root:
            return
        path = self.artifact_root / relative_path
        if isinstance(data, str):
            write_text(path, data)
        else:
            write_json(path, data)
