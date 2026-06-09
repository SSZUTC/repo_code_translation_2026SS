from __future__ import annotations

from src.common.models import RetrievedFile, TranslationTask
from src.prompts.formatting import render_context_blocks


JAVA_TO_PYTHON_REFINE_TEMPLATE = """Refine one target file after repository-level validation failed.

TARGET FILE TO FIX: {target_path}
{task_block}

Rules:
- Return exactly one complete replacement for TARGET FILE TO FIX.
- Make the smallest change that can address the validation failure.
- Keep imports consistent with this Python project layout.
- Do not edit unrelated behavior.
- If the error is an import/path problem, prefer fixing this file's imports to match existing files.
- If TARGET FILE TO FIX is requirements.txt, return only valid requirements.txt lines with package names only.
- requirements.txt must not include version constraints, version ranges, compatibility operators, comments, or environment markers.
- If validation fails inside .venv/site-packages, prefer removing unnecessary dependencies or replacing them with bare package names.
- Do not add dependencies that are unrelated to the source Java project semantics.

### VALIDATION FAILURE EXCERPT
```text
{validation_excerpt}
```

### TARGET PROJECT FILES
```text
{project_tree}
```

### CURRENT CONTENT OF TARGET FILE TO FIX
```text
{current_content}
```

{source_blocks}

{target_blocks}
"""


def build_refine_prompt(
    target_path: str,
    current_content: str,
    validation_excerpt: str,
    task: TranslationTask | None,
    source_files: list[RetrievedFile],
    target_context: list[RetrievedFile],
    project_files: list[str],
) -> str:
    task_block = "No translation task metadata found."
    if task is not None:
        task_block = (
            f"TARGET ROLE: {task.target_role}\n"
            f"TARGET DESCRIPTION: {task.description}\n"
            f"DECLARED DEPENDENCIES: {task.dependencies}\n"
            f"PLANNED EXPORTS: {task.planned_exports}\n"
            f"PLANNED IMPORTS: {task.planned_imports}\n"
            f"REFERENCE JAVA FILES: {task.source_files}"
        )
    return JAVA_TO_PYTHON_REFINE_TEMPLATE.format(
        target_path=target_path,
        task_block=task_block,
        validation_excerpt=validation_excerpt,
        project_tree="\n".join(f"- {path}" for path in project_files[:300]),
        current_content=current_content,
        source_blocks=render_context_blocks("SOURCE FILE", source_files),
        target_blocks=render_context_blocks("TARGET CONTEXT", target_context),
    )
