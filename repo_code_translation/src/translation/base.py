from __future__ import annotations

from pathlib import Path

from src.common.llm_client import OpenAICompatibleClient
from src.common.models import ProjectPlan, RetrievedFile, TranslationTask
from src.common.run_logger import RunLogger


class BaseFileTranslator:
    def __init__(
        self,
        source_root: Path,
        target_root: Path,
        llm: OpenAICompatibleClient | None,
        logger: RunLogger,
        reference_target_root: Path | None = None,
    ):
        self.source_root = source_root
        self.target_root = target_root
        self.llm = llm
        self.logger = logger
        self.reference_target_root = reference_target_root

    def translate_plan(self, plan: ProjectPlan, use_llm: bool = True, top_k: int = 6) -> ProjectPlan:
        raise NotImplementedError

    @staticmethod
    def retrieval_query(task: TranslationTask) -> str:
        return " ".join(
            [
                task.target_path,
                task.target_role,
                task.description,
                *task.source_files,
                *task.dependencies,
                *task.planned_exports,
                *task.planned_imports,
            ]
        )

    def write_retrieval_artifact(
        self,
        task: TranslationTask,
        source_context: list[RetrievedFile],
        target_context: list[RetrievedFile],
        import_context: list[RetrievedFile] | None = None,
    ) -> None:
        payload = {
            "task": task.to_dict(),
            "source_context": [{"path": item.path, "score": item.score} for item in source_context],
            "target_context": [{"path": item.path, "score": item.score} for item in target_context],
        }
        if import_context is not None:
            payload["import_context"] = [{"path": item.path, "score": item.score} for item in import_context]
        self.logger.write_artifact(f"logs/retrieval/{task.target_path.replace('/', '__')}.json", payload)
