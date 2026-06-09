from __future__ import annotations

import json
import re


JAVA_TO_PYTHON_REFINE_DIAGNOSIS_TEMPLATE = """Analyze why validation failed for a generated Python project.

You must decide which existing files should be edited in the next refinement step.

Rules:
- Return JSON only. Do not wrap it in Markdown.
- Only select files that exist in TARGET PYTHON PROJECT FILE TREE.
- If the traceback enters .venv/site-packages or another installed dependency, first consider requirements.txt as the primary file to fix.
- If an installed package is incompatible with the Python runtime, select requirements.txt and explain whether the package should be removed or kept as a bare package name.
- Prefer implementation files under app/ when the failure is caused by runtime behavior, missing exports, import errors, or dependency wiring.
- Select requirements.txt when the failure is caused by missing or incompatible packages.
- Select tests/ files only when the translated tests are clearly invalid compared with the source behavior.
- Keep the list small: 1 to {limit} files.

Dependency compatibility guidance:
- requirements.txt must use package names only. Do not recommend version constraints, version ranges, compatibility operators, comments, or environment markers.
- If a Java project is a pure algorithm/library project, requirements.txt should usually contain only pytest for tests.

JSON schema:
{{
  "summary": "short diagnosis",
  "files": [
    {{
      "path": "relative/path.py",
      "reason": "why this file should be changed",
      "priority": 1
    }}
  ]
}}

### TARGET PYTHON PROJECT FILE TREE
```text
{project_tree}
```

### PYTHON IMPORT LINT RESULT
```json
{lint_result}
```

### VALIDATION FAILURE LOG
```text
{validation_log}
```
"""


def build_refine_diagnosis_prompt(
    project_files: list[str],
    validation_log: str,
    lint_result: dict,
    limit: int = 6,
) -> str:
    return JAVA_TO_PYTHON_REFINE_DIAGNOSIS_TEMPLATE.format(
        project_tree="\n".join(_format_tree(project_files)),
        validation_log=validation_log,
        lint_result=json.dumps(lint_result, indent=2, ensure_ascii=False),
        limit=limit,
    )


def parse_refine_diagnosis(response: str) -> dict:
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return {"summary": "LLM diagnosis could not be parsed.", "files": []}
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {"summary": "LLM diagnosis could not be parsed.", "files": []}
    if not isinstance(payload, dict):
        return {"summary": "LLM diagnosis did not return an object.", "files": []}
    files = payload.get("files", [])
    if not isinstance(files, list):
        files = []
    normalized = []
    for index, item in enumerate(files, start=1):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if not path:
            continue
        normalized.append(
            {
                "path": path,
                "reason": str(item.get("reason", "selected by LLM validation diagnosis")).strip(),
                "priority": int(item.get("priority", index) or index),
            }
        )
    return {
        "summary": str(payload.get("summary", "")).strip(),
        "files": normalized,
    }


def _format_tree(paths: list[str]) -> list[str]:
    return [f"- {path}" for path in sorted(paths)]
