from __future__ import annotations

from src.common.models import RetrievedFile, TranslationTask
from src.prompts.formatting import render_context_blocks


PYTHON_TO_JAVA_REFINE_TEMPLATE = """Refine one {target_language} file after repository-level validation failed.

TARGET FILE TO FIX: {target_path}
{task_block}

Rules:
- Return exactly one complete replacement for TARGET FILE TO FIX.
- Make the smallest change that can address the validation failure.
- Keep imports/packages consistent with this {target_language} project layout.
- Do not edit unrelated behavior.
- For Java targets, keep package declarations and public class names consistent with the file path.
- If TARGET FILE TO FIX is pom.xml, return only a complete valid pom.xml file.
- If TARGET FILE TO FIX is not a Java source file, preserve that file format exactly.
- For Java compile failures, fix the provider class when a method/class is missing; fix the caller only when the call is clearly invalid.
- Do not solve missing methods by adding new external dependencies unless the source project explicitly requires that dependency.
- Prefer small JDK-only implementations for missing algorithms such as string similarity, token sorting, regex processing, and list ranking.
- If tests call an imaginary helper class or private method, rewrite the test to use the generated public API that matches the source Python test intent.
- If the validation log shows the same Maven dependency cannot be resolved, remove that dependency and replace usage with local Java code.

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


def build_directional_refine_prompt(
    target_path: str,
    current_content: str,
    validation_excerpt: str,
    task: TranslationTask | None,
    source_files: list[RetrievedFile],
    target_context: list[RetrievedFile],
    project_files: list[str],
    source_language: str,
    target_language: str,
) -> str:
    task_block = "No translation task metadata found."
    if task is not None:
        task_block = (
            f"TARGET ROLE: {task.target_role}\n"
            f"TARGET DESCRIPTION: {task.description}\n"
            f"DECLARED DEPENDENCIES: {task.dependencies}\n"
            f"PLANNED EXPORTS: {task.planned_exports}\n"
            f"PLANNED IMPORTS: {task.planned_imports}\n"
            f"REFERENCE {source_language.upper()} FILES: {task.source_files}"
        )
    return PYTHON_TO_JAVA_REFINE_TEMPLATE.format(
        target_language=target_language,
        target_path=target_path,
        task_block=task_block,
        validation_excerpt=validation_excerpt,
        project_tree="\n".join(f"- {path}" for path in project_files[:300]),
        current_content=current_content,
        source_blocks=render_context_blocks("SOURCE FILE", source_files),
        target_blocks=render_context_blocks("TARGET CONTEXT", target_context),
    )
