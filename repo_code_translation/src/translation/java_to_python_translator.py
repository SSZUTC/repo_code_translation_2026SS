from __future__ import annotations

from pathlib import Path

from src.common.io_utils import read_text, write_text
from src.common.models import ProjectPlan, RetrievedFile, TranslationTask
from src.common.retriever import FileRetriever
from src.planning import copy_resource_if_direct
from src.prompts import (
    TRANSLATOR_SYSTEM_PROMPT,
    build_translation_prompt,
    strip_markdown_fence,
)
from src.common.sketelon_io import copy_sketelon_to_target, sketelon_root_for
from src.common.translation_context import copy_reference_target, dedupe_retrieved, primary_sources
from src.translation.base import BaseFileTranslator


class JavaToPythonFileTranslator(BaseFileTranslator):
    def translate_plan(self, plan: ProjectPlan, use_llm: bool = True, top_k: int = 6) -> ProjectPlan:
        self.logger.event(
            "translate",
            "Starting per-file translation",
            tasks=len(plan.tasks),
            use_llm=use_llm,
        )
        sketelon_root = sketelon_root_for(self.logger.artifact_root)
        if copy_sketelon_to_target(sketelon_root, self.target_root):
            self.logger.event(
                "translate",
                "Copied planned sketelon into translated target",
                source=str(sketelon_root),
                target=str(self.target_root),
            )

        source_retriever = FileRetriever(self.source_root)
        target_retriever = FileRetriever(self.target_root)
        ordered_tasks = self._ordered_tasks_by_local_imports(plan.tasks)
        if [task.target_path for task in ordered_tasks] != [task.target_path for task in plan.tasks]:
            self.logger.event(
                "translate:order",
                "Reordered translation tasks by local Python import dependencies",
                order=[task.target_path for task in ordered_tasks],
            )
        for index, task in enumerate(ordered_tasks, start=1):
            self._translate_task(index, len(plan.tasks), task, source_retriever, target_retriever, use_llm, top_k)

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
        if copy_resource_if_direct(task, self.source_root, self.target_root):
            task.status = "copied"
            self.logger.event("translate", f"[{index}/{total}] Copied resource {task.target_path}")
            return
        if copy_reference_target(task, self.reference_target_root, self.target_root):
            task.status = "translated-from-reference"
            self.logger.event(
                "translate:file",
                f"[{index}/{total}] 正在翻译 Python 文件 {task.target_path}",
                target_path=task.target_path,
                target_role=task.target_role,
                ref_java_files=task.source_files,
                ref_python_file=(self.reference_target_root / task.target_path).as_posix()
                if self.reference_target_root is not None
                else "",
                mode="reference-guided",
            )
            self.logger.event(
                "translate:file",
                f"[{index}/{total}] 完成 Python 文件实现 {task.target_path}",
                target_path=task.target_path,
                status=task.status,
            )
            return
        if not use_llm or self.llm is None:
            task.status = "plan-only"
            self.logger.event(
                "translate:file",
                f"[{index}/{total}] 跳过具体实现翻译，保留规划占位文件 {task.target_path}",
                target_path=task.target_path,
                ref_java_files=task.source_files,
                reason="LLM disabled and no reference target file available",
            )
            return

        query = self.retrieval_query(task)
        source_context = primary_sources(task, self.source_root) + source_retriever.retrieve(query, top_k=top_k)
        source_context = dedupe_retrieved(source_context)
        import_context = self._planned_import_context(task, self._module_path_map_for_plan_targets())
        target_context = [
            item for item in target_retriever.retrieve(query, top_k=top_k)
            if item.path not in {context.path for context in import_context}
        ]
        self.logger.event(
            "translate:file",
            f"[{index}/{total}] 正在翻译 Python 文件 {task.target_path}",
            target_path=task.target_path,
            target_role=task.target_role,
            ref_java_files=task.source_files,
            planned_exports=task.planned_exports,
            planned_imports=task.planned_imports,
            retrieved_java_files=[item.path for item in source_context],
            import_python_files=[item.path for item in import_context],
            retrieved_python_context=[item.path for item in target_context],
            mode="llm",
        )
        self.write_retrieval_artifact(task, source_context, target_context, import_context)

        prompt = build_translation_prompt(task, source_context, target_context, import_context)
        generated = strip_markdown_fence(self.llm.complete(TRANSLATOR_SYSTEM_PROMPT, prompt))
        write_text(self.target_root / task.target_path, generated)
        task.status = "translated"
        self.logger.event(
            "translate:file",
            f"[{index}/{total}] Translated {task.target_path}",
            source_context=[item.path for item in source_context],
            import_context=[item.path for item in import_context],
            target_context=[item.path for item in target_context],
        )

    def _ordered_tasks_by_local_imports(self, tasks: list[TranslationTask]) -> list[TranslationTask]:
        module_to_task = self._module_path_map(tasks)
        task_by_path = {task.target_path: task for task in tasks}
        dependencies = {
            task.target_path: {
                dep
                for dep in self._local_import_task_paths(task, module_to_task)
                if dep != task.target_path
            }
            for task in tasks
        }
        remaining = set(task_by_path)
        completed: set[str] = set()
        ordered: list[TranslationTask] = []
        while remaining:
            ready = [
                task_by_path[path]
                for path in remaining
                if dependencies[path].issubset(completed)
            ]
            if not ready:
                ready = [task_by_path[path] for path in remaining]
            ready.sort(key=lambda task: (len(dependencies[task.target_path] - completed), self._task_order_bucket(task), task.target_path))
            task = ready[0]
            ordered.append(task)
            remaining.remove(task.target_path)
            completed.add(task.target_path)
        return ordered

    def _planned_import_context(self, task: TranslationTask, module_to_path: dict[str, str]) -> list[RetrievedFile]:
        contexts = []
        seen = set()
        import_names = list(task.planned_imports) + self._imports_from_existing_target_file(task.target_path)
        for import_name in import_names:
            path = self._resolve_import_to_task_path(import_name, module_to_path)
            if not path or path == task.target_path or path in seen:
                continue
            target = self.target_root / path
            if not target.exists() or not target.is_file():
                continue
            contexts.append(RetrievedFile(path=path, score=999.0, content=read_text(target, max_chars=20000)))
            seen.add(path)
        return contexts

    def _module_path_map_for_plan_targets(self) -> dict[str, str]:
        paths = [
            path.relative_to(self.target_root).as_posix()
            for path in self.target_root.rglob("*.py")
            if not self._ignored_path(path)
        ]
        mapping = {}
        for path in paths:
            module = self._module_name_for_path(path)
            if module:
                mapping[module] = path
        return mapping

    def _module_path_map(self, tasks: list[TranslationTask]) -> dict[str, str]:
        mapping = {}
        for task in tasks:
            if not task.target_path.endswith(".py"):
                continue
            module = self._module_name_for_path(task.target_path)
            if module:
                mapping[module] = task.target_path
        return mapping

    def _local_import_task_paths(self, task: TranslationTask, module_to_path: dict[str, str]) -> set[str]:
        paths = set()
        import_names = list(task.planned_imports) + self._imports_from_existing_target_file(task.target_path)
        for import_name in import_names:
            path = self._resolve_import_to_task_path(import_name, module_to_path)
            if path:
                paths.add(path)
        return paths

    def _imports_from_existing_target_file(self, target_path: str) -> list[str]:
        path = self.target_root / target_path
        if not path.exists() or path.suffix != ".py" or self._ignored_path(path):
            return []
        imports = []
        for line in read_text(path, max_chars=20000).splitlines():
            stripped = line.strip()
            if stripped.startswith("from "):
                parts = stripped.split()
                if len(parts) >= 2:
                    imports.append(parts[1])
            elif stripped.startswith("import "):
                imports.extend(item.strip().split(" as ", 1)[0] for item in stripped[7:].split(","))
        return imports

    @staticmethod
    def _resolve_import_to_task_path(import_name: str, module_to_path: dict[str, str]) -> str | None:
        module = import_name.strip()
        if not module:
            return None
        parts = module.split(".")
        for end in range(len(parts), 0, -1):
            candidate = ".".join(parts[:end])
            if candidate in module_to_path:
                return module_to_path[candidate]
        return None

    @staticmethod
    def _module_name_for_path(path: str) -> str:
        if not path.endswith(".py"):
            return ""
        module = path[:-3].replace("/", ".")
        return module[:-9] if module.endswith(".__init__") else module

    @staticmethod
    def _ignored_path(path: Path) -> bool:
        ignored = {"__pycache__", ".pytest_cache", ".venv", "venv"}
        return any(part in ignored for part in path.parts)

    @staticmethod
    def _task_order_bucket(task: TranslationTask) -> int:
        path = task.target_path
        role = task.target_role.lower()
        if path.endswith(".txt") or role in {"requirements", "config"}:
            return 0
        if role in {"enum", "data_model", "model", "schema", "dto", "logic", "common"}:
            return 1
        if role in {"repository", "service", "service_logic"}:
            return 2
        if role in {"api", "controller", "application"}:
            return 3
        if role == "test" or path.startswith("tests/"):
            return 4
        return 2
