from __future__ import annotations

from src.common.models import RetrievedFile, TranslationTask
from src.prompts.formatting import render_context_blocks


PYTHON_TO_JAVA_SYSTEM_PROMPT = """You translate Python repository files into production-quality Java.
Preserve behavior, public API semantics, validation errors, data shape, and tests.
Use idiomatic Java while respecting the provided Maven target project plan and package layout.
Prefer self-contained Java implementations using the JDK standard library.
Do not invent third-party dependencies or APIs that are not already declared in the target plan.
Return only the complete target file content. Do not wrap in markdown unless explicitly asked."""


PYTHON_TO_JAVA_TRANSLATION_TEMPLATE = """Translate one target file for a {source_language}-to-{target_language} repository migration.

TARGET FILE: {target_path}
TARGET ROLE: {target_role}
TARGET DESCRIPTION: {description}
DECLARED DEPENDENCIES: {dependencies}
PLANNED EXPORTS: {planned_exports}
PLANNED IMPORTS: {planned_imports}

Rules:
- Produce exactly one complete target file.
- Keep imports/packages consistent with the target project layout.
- Implement the planned exports unless the target file is a non-code resource.
- Use the planned imports when they are valid for the generated project; if a planned import is impossible, replace it with a semantically equivalent import and keep the public exports stable.
- Preserve behavior, validation messages, data shape, and test semantics where applicable.
- If the target file is a build file or static resource, adapt framework-specific paths but keep behavior.
- For Java targets, include a package declaration when the file lives under src/main/java or src/test/java.
- For Java tests, use JUnit 5 unless the target context indicates otherwise.
- For Java targets, do not reference classes, methods, or packages that are not visible in TARGET CONTEXT or planned imports.
- For Java targets, when translating Python standard-library behavior, implement it with JDK APIs or local helper methods.
- For Java targets, avoid external libraries for Levenshtein/string similarity, regex, JSON-like simple parsing, collections, or sorting unless already present in pom.xml.
- For Java tests, compile against the generated public API only; do not call private helpers, imaginary classes, or Python-only dynamic APIs.
- For Java tests, do not make assertions stricter than the referenced Python tests.

{source_blocks}

{target_blocks}
"""


def build_directional_translation_prompt(
    task: TranslationTask,
    source_files: list[RetrievedFile],
    target_context: list[RetrievedFile],
    source_language: str,
    target_language: str,
) -> str:
    return PYTHON_TO_JAVA_TRANSLATION_TEMPLATE.format(
        source_language=source_language,
        target_language=target_language,
        target_path=task.target_path,
        target_role=task.target_role,
        description=task.description,
        dependencies=task.dependencies,
        planned_exports=task.planned_exports,
        planned_imports=task.planned_imports,
        source_blocks=render_context_blocks("SOURCE FILE", source_files),
        target_blocks=render_context_blocks("TARGET CONTEXT", target_context),
    )
