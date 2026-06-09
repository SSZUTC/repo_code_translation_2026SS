from __future__ import annotations

from pathlib import Path

from src.analysis.python_analyzer import PythonProjectAnalyzer
from src.common.llm_client import OpenAICompatibleClient
from src.common.models import ProjectPlan, TranslationTask
from src.pipeline.base import BaseRepoTranslator
from src.prompts import (
    PYTHON_TO_JAVA_PROJECT_PLANNER_SYSTEM_PROMPT,
    build_python_to_java_project_plan_prompt,
    parse_python_to_java_project_plan,
)
from src.refinement.python_to_java_refine_runner import PythonToJavaRefineRunner
from src.planning import PythonToJavaProjectPlanner, RefinedPlanBuilder
from src.common.io_utils import read_json, read_text
from src.skeleton import JavaProjectSkeletonManager
from src.translation import PythonToJavaFileTranslator
from src.validation import JavaValidator


class PythonToJavaRepoTranslator(BaseRepoTranslator):
    source_language = "Python"
    target_language = "Java"
    project_file_suffixes = {".java", ".xml", ".md", ".html", ".css", ".js", ".json", ".properties"}
    ignored_project_parts = {"target"}

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
        self.analyzer = PythonProjectAnalyzer()
        self.planner = PythonToJavaProjectPlanner()
        self.refiner = RefinedPlanBuilder()
        self.skeleton = JavaProjectSkeletonManager(self.target_root, self.logger)

    def build_plan(self, use_llm: bool = False) -> ProjectPlan:
        self.logger.event("plan", "Building target Java project plan", use_llm=use_llm)
        analysis = self.analyze()
        plan = self.planner.plan(analysis, self.target_root)
        project_plan = {}
        if use_llm and self.llm is not None:
            self.logger.event("plan:llm", "Requesting LLM project plan refinement")
            planning_prompt = build_python_to_java_project_plan_prompt(analysis, self._load_project_semantics(), plan)
            self.logger.write_artifact("plans/java_project_plan_prompt.md", planning_prompt)
            response = self.llm.complete(
                PYTHON_TO_JAVA_PROJECT_PLANNER_SYSTEM_PROMPT,
                planning_prompt,
            )
            plan, project_plan = parse_python_to_java_project_plan(response, plan)
            self.logger.write_artifact("plans/java_project_plan.json", project_plan)
        self.logger.event("plan", "项目规划完成", tasks=len(plan.tasks))
        refined_plan = self.refiner.refine(plan)
        self.log_refined_plan(refined_plan, plan, target_label="Java", source_ref_key="ref_python_files")
        self.skeleton.write(plan, project_plan)
        self.planner.materialize(plan, self.target_root)
        self.logger.event("plan", "Target project plan materialized", tasks=len(plan.tasks), target=str(self.target_root))
        return plan

    def translate(self, use_llm: bool = True, top_k: int = 6) -> ProjectPlan:
        plan = self._load_or_create_plan()
        file_translator = PythonToJavaFileTranslator(
            source_root=self.source_root,
            target_root=self.target_root,
            llm=self.llm,
            logger=self.logger,
            reference_target_root=self.reference_target_root,
        )
        return file_translator.translate_plan(plan, use_llm=use_llm, top_k=top_k)

    def validate(self) -> list[dict]:
        plan = self._load_or_create_plan()
        self.logger.event("validate", "Running validation commands", commands=plan.verification_commands)
        results = JavaValidator().validate(self.target_root, plan.verification_commands)
        return self.validation_payload(results)

    def refine(self, iterations: int = 2, top_k: int = 6) -> list[dict]:
        plan = self._load_or_create_plan()
        runner = PythonToJavaRefineRunner(
            source_root=self.source_root,
            target_root=self.target_root,
            llm=self.llm,
            logger=self.logger,
            validate_callback=self.validate,
            project_files_callback=self.project_files,
        )
        return runner.run(plan, iterations=iterations, top_k=top_k)

    def _load_or_create_plan(self) -> ProjectPlan:
        plan_path = self.target_root / "translation_plan.json"
        if not plan_path.exists():
            return self.build_plan(use_llm=self.llm is not None)
        data = read_json(plan_path)
        return ProjectPlan(
            source_project=data["source_project"],
            target_project=data["target_project"],
            architecture=data["architecture"],
            tasks=[
                TranslationTask(
                    target_path=item["target_path"],
                target_role=item["target_role"],
                source_files=item.get("source_files", []),
                description=item.get("description", ""),
                dependencies=item.get("dependencies", []),
                planned_exports=item.get("planned_exports", []),
                planned_imports=item.get("planned_imports", []),
                status=item.get("status", "pending"),
            )
                for item in data["tasks"]
            ],
            verification_commands=data.get("verification_commands", ["mvn -q test"]),
        )

    def _load_project_semantics(self) -> str:
        if self.latest_project_semantics:
            return self.latest_project_semantics
        artifact_root = self.logger.artifact_root
        if artifact_root is not None:
            path = artifact_root / "analysis" / "project_semantics.md"
            if path.exists():
                return read_text(path, max_chars=50000)
        return ""
