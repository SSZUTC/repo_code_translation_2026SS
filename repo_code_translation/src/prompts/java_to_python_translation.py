from __future__ import annotations

from src.common.models import RetrievedFile, TranslationTask
from src.prompts.formatting import render_context_blocks


TRANSLATOR_SYSTEM_PROMPT = """You translate Java repository files into production-quality Python.
Preserve behavior, public API semantics, validation errors, data shape, and tests.
Use idiomatic Python while respecting the provided target project plan and architecture.
Return only the complete target file content. Do not wrap in markdown unless explicitly asked."""


JAVA_TO_PYTHON_TRANSLATION_TEMPLATE = """Translate one target file for a Java-to-Python repository migration.

TARGET FILE: {target_path}
TARGET ROLE: {target_role}
TARGET DESCRIPTION: {description}
DECLARED DEPENDENCIES: {dependencies}
PLANNED EXPORTS: {planned_exports}
PLANNED IMPORTS: {planned_imports}

Rules:
- Produce exactly one complete target file.
- Keep imports consistent with the target Python project.
- Implement the planned exports unless the target file is a non-code resource.
- Use the planned imports when they are valid for the generated project; if a planned import is impossible, replace it with a semantically equivalent import and keep the public exports stable.
- Preserve Java behavior, validation messages, JSON field names, and test semantics where applicable.
- If the target file is static HTML/CSS/JS, adapt framework-specific paths but keep user-visible behavior.
- If TARGET FILE is requirements.txt, output package names only, one per line. Do not include version constraints such as ==, >=, <=, <, >, ~=, or environment markers.
- If the Java source project is a pure algorithm/library project, avoid adding unrelated runtime dependencies. Use only packages that are necessary for the generated Python code or tests.

{source_blocks}

{import_blocks}

{target_blocks}
"""


def build_translation_prompt(
    task: TranslationTask,
    source_files: list[RetrievedFile],
    target_context: list[RetrievedFile],
    import_context: list[RetrievedFile] | None = None,
) -> str:
    return JAVA_TO_PYTHON_TRANSLATION_TEMPLATE.format(
        target_path=task.target_path,
        target_role=task.target_role,
        description=task.description,
        dependencies=task.dependencies,
        planned_exports=task.planned_exports,
        planned_imports=task.planned_imports,
        source_blocks=render_context_blocks("SOURCE FILE", source_files),
        import_blocks=render_context_blocks("IMPORT PYTHON CONTEXT", import_context or []),
        target_blocks=render_context_blocks("TARGET CONTEXT", target_context),
    )
