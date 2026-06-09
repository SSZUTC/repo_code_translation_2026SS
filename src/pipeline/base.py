from __future__ import annotations

from pathlib import Path
from typing import Any

from src.common.llm_client import OpenAICompatibleClient
from src.common.models import ProjectPlan, RepoAnalysis
from src.common.run_logger import RunLogger
from src.common.io_utils import write_json


class BaseRepoTranslator:
    source_language = "source"
    target_language = "target"
    project_file_suffixes: set[str] = set()
    ignored_project_parts: set[str] = set()

    def __init__(
        self,
        source_root: Path,
        target_root: Path,
        llm: OpenAICompatibleClient | None = None,
        artifact_root: Path | None = None,
        reference_target_root: Path | None = None,
        verbose: bool = True,
    ):
        self.source_root = source_root.resolve()
        self.target_root = target_root.resolve()
        self.reference_target_root = reference_target_root.resolve() if reference_target_root else None
        self.llm = llm
        self.logger = RunLogger(artifact_root, verbose=verbose)
        self.latest_project_semantics = ""

    def analyze(self) -> RepoAnalysis:
        self.logger.event("analyze", f"Analyzing {self.source_language} project", source=str(self.source_root))
        analysis = self.analyzer.analyze(self.source_root)
        self.target_root.mkdir(parents=True, exist_ok=True)
        self.logger.write_artifact("analysis/file_tree.json", self.analyzer.extract_file_tree(self.source_root))
        self.logger.write_artifact("analysis/ast_tree.json", self.analyzer.extract_ast_tree(analysis))
        if self.llm is not None:
            self.logger.event("analyze:llm", f"Requesting LLM semantic {self.source_language} project analysis")
            semantic_prompt = self.analyzer.extract_project_semantics_prompt(analysis)
            self.logger.write_artifact("analysis/project_semantics_prompt.md", semantic_prompt)
            semantic_report = self.llm.complete(
                self.analyzer.project_semantics_system_prompt(),
                semantic_prompt,
            )
            self.latest_project_semantics = semantic_report
            self.logger.write_artifact("analysis/project_semantics.md", semantic_report)
        self.logger.event(
            "analyze",
            f"{self.source_language} project analysis complete",
            files=len(analysis.files),
            build_tool=analysis.build_tool,
            frameworks=analysis.framework_hints,
        )
        return analysis

    def log_refined_plan(self, refined_plan: list[dict], plan: ProjectPlan, target_label: str, source_ref_key: str) -> None:
        for item in refined_plan:
            event_payload: dict[str, Any] = {
                "target_path": item["target_path"],
                "target_role": item["target_role"],
                source_ref_key: item["reference_java_files"],
                "expected_symbols": item["expected_symbols"],
                "planned_exports": item["planned_exports"],
                "planned_imports": item["planned_imports"],
                "description": item["semantic_contract"],
            }
            self.logger.event(
                "plan:file",
                f"[{item['index']}/{len(plan.tasks)}] 规划 {target_label} 目标文件 {item['target_path']}",
                **event_payload,
            )

    def validation_payload(self, results) -> list[dict]:
        payload = [
            {
                "command": result.command,
                "returncode": result.returncode,
                "ok": result.ok,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            for result in results
        ]
        write_json(self.target_root / "validation_report.json", payload)
        self.logger.write_artifact("validation/validation_report.json", payload)
        for result in payload:
            status = "PASS" if result["ok"] else "FAIL"
            self.logger.event("validate", f"{status}: {result['command']}", returncode=result["returncode"])
        return payload

    def project_files(self) -> list[str]:
        return sorted(
            path.relative_to(self.target_root).as_posix()
            for path in self.target_root.rglob("*")
            if path.is_file()
            and not any(part in self.ignored_project_parts for part in path.parts)
            and path.suffix in self.project_file_suffixes
        )

    @staticmethod
    def target_framework_summary(plan: ProjectPlan) -> dict:
        by_role: dict[str, list[str]] = {}
        for task in plan.tasks:
            by_role.setdefault(task.target_role, []).append(task.target_path)
        return {
            "target_project": plan.target_project,
            "architecture": plan.architecture,
            "layers": by_role,
            "verification_commands": plan.verification_commands,
        }
