from __future__ import annotations

from pathlib import Path

from src.common.io_utils import read_text, write_json, write_text
from src.common.models import ProjectPlan, TranslationTask
from src.common.retriever import FileRetriever
from src.common.translation_context import copy_reference_target, dedupe_retrieved, primary_sources
from src.prompts import PYTHON_TO_JAVA_SYSTEM_PROMPT, build_directional_translation_prompt, strip_markdown_fence
from src.translation.base import BaseFileTranslator


class PythonToJavaFileTranslator(BaseFileTranslator):
    def translate_plan(self, plan: ProjectPlan, use_llm: bool = True, top_k: int = 6) -> ProjectPlan:
        self.logger.event(
            "translate",
            "Starting per-file translation",
            tasks=len(plan.tasks),
            use_llm=use_llm,
        )
        source_retriever = FileRetriever(self.source_root)
        target_retriever = FileRetriever(self.target_root)

        for index, task in enumerate(plan.tasks, start=1):
            self._translate_task(index, len(plan.tasks), task, source_retriever, target_retriever, use_llm, top_k)

        write_json(self.target_root / "translation_plan.json", plan.to_dict())
        self.logger.event("translate", "Translation stage complete")
        return plan

    def _translate_task(
        self,
        index: int,
        total: int,
        task: TranslationTask,
        source_retriever: FileRetriever,
        target_retriever: FileRetriever,
        use_llm: bool,
        top_k: int,
    ) -> None:
        self.logger.event(
            "translate",
            f"[{index}/{total}] Processing {task.target_path}",
            role=task.target_role,
            source_files=task.source_files,
        )
        if self._copy_resource_if_direct(task):
            task.status = "copied"
            self.logger.event("translate", f"[{index}/{total}] Copied resource {task.target_path}")
            return
        if copy_reference_target(task, self.reference_target_root, self.target_root):
            task.status = "translated-from-reference"
            ref_path = (self.reference_target_root / task.target_path).as_posix() if self.reference_target_root else ""
            self.logger.event(
                "translate:file",
                f"[{index}/{total}] 完成 Java 文件实现 {task.target_path}",
                target_path=task.target_path,
                ref_python_files=task.source_files,
                ref_java_file=ref_path,
                mode="reference-guided",
            )
            return
        if not use_llm or self.llm is None:
            task.status = "plan-only"
            self.logger.event(
                "translate:file",
                f"[{index}/{total}] 跳过具体实现翻译，保留规划占位文件 {task.target_path}",
                target_path=task.target_path,
                ref_python_files=task.source_files,
                reason="LLM disabled and no reference target file available",
            )
            return

        query = self.retrieval_query(task)
        source_context = primary_sources(task, self.source_root) + source_retriever.retrieve(query, top_k=top_k)
        source_context = dedupe_retrieved(source_context)
        target_context = target_retriever.retrieve(query, top_k=top_k)
        self.logger.event(
            "translate:file",
            f"[{index}/{total}] 正在翻译 Java 文件 {task.target_path}",
            target_path=task.target_path,
            target_role=task.target_role,
            ref_python_files=task.source_files,
            planned_exports=task.planned_exports,
            planned_imports=task.planned_imports,
            retrieved_python_files=[item.path for item in source_context],
            retrieved_java_context=[item.path for item in target_context],
            mode="llm",
        )
        self.write_retrieval_artifact(task, source_context, target_context)
        prompt = build_directional_translation_prompt(task, source_context, target_context, "Python", "Java")
        generated = strip_markdown_fence(self.llm.complete(PYTHON_TO_JAVA_SYSTEM_PROMPT, prompt))
        write_text(self.target_root / task.target_path, generated)
        task.status = "translated"
        self.logger.event(
            "translate:file",
            f"[{index}/{total}] Translated {task.target_path}",
            source_context=[item.path for item in source_context],
            target_context=[item.path for item in target_context],
        )

    def _copy_resource_if_direct(self, task: TranslationTask) -> bool:
        if task.target_role not in {"static", "template", "resource"} or not task.source_files:
            return False
        source = self.source_root / task.source_files[0]
        if not source.exists() or not source.is_file():
            return False
        write_text(self.target_root / task.target_path, read_text(source))
        return True
