from __future__ import annotations

from pathlib import Path

from src.common.io_utils import read_text, write_text
from src.common.models import ProjectPlan
from src.common.retriever import FileRetriever
from src.common.run_logger import RunLogger
from src.common.translation_context import dedupe_retrieved, primary_sources
from src.prompts import (
    PYTHON_TO_JAVA_SYSTEM_PROMPT,
    build_directional_refine_prompt,
    build_python_to_java_refine_diagnosis_prompt,
    parse_python_to_java_refine_diagnosis,
    strip_markdown_fence,
)
from src.refinement import FileRefinementTarget, JavaValidationFailureAnalyzer
from src.refinement.java_quickfix import JavaCompileQuickFixer


class PythonToJavaRefineRunner:
    def __init__(self, source_root: Path, target_root: Path, llm, logger: RunLogger, validate_callback, project_files_callback):
        self.source_root = source_root
        self.target_root = target_root
        self.llm = llm
        self.logger = logger
        self.validate_callback = validate_callback
        self.project_files_callback = project_files_callback

    def run(self, plan: ProjectPlan, iterations: int = 2, top_k: int = 6) -> list[dict]:
        if self.llm is None:
            self.logger.event("refine", "Refine skipped because LLM is disabled")
            return self.validate_callback()

        task_by_path = {task.target_path: task for task in plan.tasks}
        analyzer = JavaValidationFailureAnalyzer()
        quickfixer = JavaCompileQuickFixer()
        results = self.validate_callback()

        for iteration in range(1, iterations + 1):
            if all(item["ok"] for item in results):
                self.logger.event("refine", "Validation already passes; no refine needed", iteration=iteration)
                return results
            quickfixed = quickfixer.apply(results, self.target_root)
            if quickfixed:
                self.logger.event(
                    "refine:quickfix",
                    f"[{iteration}/{iterations}] Applied deterministic Java compile quick fixes",
                    files=quickfixed,
                )
                results = self.validate_callback()
                if all(item["ok"] for item in results):
                    return results
            targets = self.diagnose_targets(results, analyzer, top_k, iteration)
            self.logger.event(
                "refine",
                f"[{iteration}/{iterations}] Validation failed; selected files for refinement",
                targets=[item.path for item in targets],
            )
            if not targets:
                self.logger.event("refine", "No editable Java files could be mapped from validation output")
                return results

            source_retriever = FileRetriever(self.source_root)
            target_retriever = FileRetriever(self.target_root)
            for index, target in enumerate(targets, start=1):
                target_path = self.target_root / target.path
                task = task_by_path.get(target.path)
                query_parts = [target.path, target.reason]
                if task is not None:
                    query_parts.extend([task.target_role, task.description, *task.source_files, *task.dependencies])
                    query_parts.extend([*task.planned_exports, *task.planned_imports])
                query = " ".join(query_parts)
                source_context = primary_sources(task, self.source_root) if task is not None else []
                source_context += source_retriever.retrieve(query, top_k=top_k)
                source_context = dedupe_retrieved(source_context)
                target_context = [
                    item for item in target_retriever.retrieve(query, top_k=top_k + 2) if item.path != target.path
                ][:top_k]
                validation_excerpt = self.validation_failure_log(results)
                self.logger.event(
                    "refine:file",
                    f"[{iteration}/{iterations}:{index}/{len(targets)}] 正在根据验证错误修复 {target.path}",
                    target_path=target.path,
                    reason=target.reason,
                    ref_python_files=task.source_files if task is not None else [],
                    retrieved_python_files=[item.path for item in source_context],
                    retrieved_java_context=[item.path for item in target_context],
                )
                self.logger.write_artifact(
                    f"logs/refine/{iteration}_{target.path.replace('/', '__')}.json",
                    {
                        "iteration": iteration,
                        "target_path": target.path,
                        "reason": target.reason,
                        "validation_excerpt": validation_excerpt,
                        "source_context": [{"path": item.path, "score": item.score} for item in source_context],
                        "target_context": [{"path": item.path, "score": item.score} for item in target_context],
                    },
                )
                prompt = build_directional_refine_prompt(
                    target.path,
                    read_text(target_path, max_chars=50000),
                    validation_excerpt,
                    task,
                    source_context,
                    target_context,
                    self.project_files_callback(),
                    "Python",
                    "Java",
                )
                refined = strip_markdown_fence(self.llm.complete(PYTHON_TO_JAVA_SYSTEM_PROMPT, prompt))
                write_text(target_path, refined)
                self.logger.event("refine:file", f"[{iteration}/{iterations}:{index}/{len(targets)}] 完成修复 {target.path}")
            results = self.validate_callback()
        return results

    def diagnose_targets(
        self,
        validation_report: list[dict],
        analyzer: JavaValidationFailureAnalyzer,
        limit: int,
        iteration: int,
    ) -> list[FileRefinementTarget]:
        project_files = self.project_files_callback()
        validation_log = self.validation_failure_log(validation_report, max_chars=50000)
        prompt = build_python_to_java_refine_diagnosis_prompt(
            project_files=project_files,
            validation_log=validation_log,
            limit=limit,
        )
        response = self.llm.complete(PYTHON_TO_JAVA_SYSTEM_PROMPT, prompt)
        diagnosis = parse_python_to_java_refine_diagnosis(response)
        existing_files = set(project_files)
        selected: list[FileRefinementTarget] = []
        for item in sorted(diagnosis.get("files", []), key=lambda value: value.get("priority", 999)):
            path = item["path"]
            if path not in existing_files:
                continue
            selected.append(FileRefinementTarget(path, item.get("reason", "selected by LLM diagnosis")))
            if len(selected) >= limit:
                break
        self.logger.write_artifact(f"logs/refine/{iteration}_diagnosis_prompt.md", prompt)
        self.logger.write_artifact(
            f"logs/refine/{iteration}_diagnosis.json",
            {
                "diagnosis": diagnosis,
                "selected_files": [item.path for item in selected],
            },
        )
        self.logger.event(
            "refine:diagnose",
            "LLM selected refinement files",
            summary=diagnosis.get("summary", ""),
            targets=[{"path": item.path, "reason": item.reason} for item in selected],
        )
        if selected:
            return selected
        return analyzer.select_targets(validation_report, self.target_root, limit=limit)

    @staticmethod
    def validation_failure_log(validation_report: list[dict], max_chars: int = 50000) -> str:
        blocks = [
            f"$ {item.get('command', '')}\n{item.get('stdout', '')}\n{item.get('stderr', '')}"
            for item in validation_report
            if not item.get("ok")
        ]
        text = "\n\n".join(blocks)
        if len(text) > max_chars:
            return text[:max_chars] + "\n...[truncated]..."
        return text
