from __future__ import annotations

from pathlib import Path

from src.analysis.java_analyzer import JavaProjectAnalyzer
from src.common.llm_client import OpenAICompatibleClient
from src.common.models import ProjectPlan
from src.pipeline.base import BaseRepoTranslator
from src.prompts import (
    JAVA_TO_PYTHON_PROJECT_PLANNER_SYSTEM_PROMPT,
    build_java_to_python_project_plan_prompt,
    parse_java_to_python_project_plan,
)
from src.refinement.java_to_python_refine_runner import JavaToPythonRefineRunner
from src.common.python_project_linter import PythonProjectLinter
from src.planning import JavaToPythonProjectPlanner, RefinedPlanBuilder
from src.skeleton.python_project_skeleton import PythonProjectSkeletonManager
from src.translation import JavaToPythonFileTranslator
from src.common.io_utils import read_text
from src.validation import PythonValidator


class JavaToPythonRepoTranslator(BaseRepoTranslator):
    source_language = "Java"
    target_language = "Python"
    project_file_suffixes = {".py", ".txt", ".md", ".html", ".css", ".js", ".json"}
    ignored_project_parts = {"__pycache__", ".pytest_cache"}

    def __init__(
        self,
        source_root: Path,
        target_root: Path,
        llm: OpenAICompatibleClient | None = None,
        artifact_root: Path | None = None,
        reference_target_root: Path | None = None,
        verbose: bool = True,
    ):
        super().__init__(source_root, target_root, llm, artifact_root, reference_target_root, verbose)
        self.analyzer = JavaProjectAnalyzer()
        self.planner = JavaToPythonProjectPlanner()
        self.refiner = RefinedPlanBuilder()
        self.skeleton = PythonProjectSkeletonManager(self.target_root, self.logger)

    def build_plan(self, use_llm: bool = False) -> ProjectPlan:
        self.logger.event("plan", "Building target Python project plan", use_llm=self.llm is not None)
        analysis = self.analyze()
        plan = self.planner.plan(analysis, self.target_root)
        project_plan = {}
        if self.llm is not None:
            self.logger.event(
                "plan:llm",
                "Requesting LLM Python project architecture plan",
                python_version="3.10",
            )
            project_semantics = self._load_project_semantics()
            planning_prompt = build_java_to_python_project_plan_prompt(analysis, project_semantics, plan)
            self.logger.write_artifact("plans/python_project_plan_prompt.md", planning_prompt)
            response = self.llm.complete(
                JAVA_TO_PYTHON_PROJECT_PLANNER_SYSTEM_PROMPT,
                planning_prompt,
            )
            plan, project_plan = parse_java_to_python_project_plan(response, plan)
            self.logger.write_artifact("plans/python_project_plan.json", project_plan)
        self.logger.event("plan", "项目规划完成", tasks=len(plan.tasks))
        refined_plan = self.refiner.refine(plan)
        self.log_refined_plan(refined_plan, plan, target_label="Python", source_ref_key="ref_java_files")
        self.planner.materialize(plan, self.target_root)
        self.skeleton.write(plan, project_plan)
        self._lint_python_project(self.logger.artifact_root / "plans" / "sketelon" if self.logger.artifact_root else self.target_root, "plan:lint")
        self.logger.event("plan", "Target project plan materialized", tasks=len(plan.tasks), target=str(self.target_root))
        return plan

    def translate(self, use_llm: bool = True, top_k: int = 6) -> ProjectPlan:
        plan = self._load_or_create_plan()
        file_translator = JavaToPythonFileTranslator(
            source_root=self.source_root,
            target_root=self.target_root,
            llm=self.llm,
            logger=self.logger,
            reference_target_root=self.reference_target_root,
        )
        file_translator.translate_plan(plan, use_llm=use_llm, top_k=top_k)
        self._lint_python_project(self.target_root, "translate:lint")
        self.skeleton.write(plan)
        return plan

    def validate(self) -> list[dict]:
        plan = self._load_or_create_plan()
        self._lint_python_project(self.target_root, "validate:lint")
        self.logger.event("validate", "Running validation commands", commands=plan.verification_commands)
        results = PythonValidator().validate(self.target_root, plan.verification_commands)
        return self.validation_payload(results)

    def refine(self, iterations: int = 2, top_k: int = 6) -> list[dict]:
        plan = self._load_or_create_plan()
        runner = JavaToPythonRefineRunner(
            source_root=self.source_root,
            target_root=self.target_root,
            llm=self.llm,
            logger=self.logger,
            validate_callback=self.validate,
            project_files_callback=self.project_files,
        )
        return runner.run(plan, iterations=iterations, top_k=top_k)

    def _lint_python_project(self, project_root: Path | None, stage: str) -> None:
        if project_root is None or not project_root.exists():
            return
        result = PythonProjectLinter().lint(project_root)
        self.logger.write_artifact(f"logs/lint/{stage.replace(':', '_')}.json", result.to_dict())
        if result.changed or result.unresolved_imports:
            self.logger.event(
                stage,
                "Python project import/dependency lint completed",
                created_files=result.created_files,
                updated_files=result.updated_files,
                added_requirements=result.added_requirements,
                unresolved_imports=result.unresolved_imports,
            )

    def _load_or_create_plan(self) -> ProjectPlan:
        return self.skeleton.load_plan(lambda: self.build_plan(use_llm=self.llm is not None))

    def _load_project_semantics(self) -> str:
        if self.latest_project_semantics:
            return self.latest_project_semantics
        artifact_root = self.logger.artifact_root
        if artifact_root is not None:
            path = artifact_root / "analysis" / "project_semantics.md"
            if path.exists():
                return read_text(path, max_chars=50000)
        return ""
