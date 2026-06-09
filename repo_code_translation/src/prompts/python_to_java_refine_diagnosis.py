from __future__ import annotations

import json
import re


PYTHON_TO_JAVA_REFINE_DIAGNOSIS_TEMPLATE = """Analyze why validation failed for a generated Java project.

You must decide which existing files should be edited in the next refinement step.

Rules:
- Return JSON only. Do not wrap it in Markdown.
- Only select files that exist in TARGET JAVA PROJECT FILE TREE.
- Prefer implementation files under src/main/java when the failure is caused by compile errors, missing symbols, package/import problems, constructor mismatch, or runtime behavior.
- Select src/test/java files only when the translated tests are clearly invalid compared with source behavior.
- Select pom.xml when the failure is caused by missing dependencies, plugin configuration, Java version configuration, or Maven build setup.
- If a missing dependency is only used for an algorithm that can be implemented locally, select pom.xml and the Java files importing/using that dependency.
- If javac reports a missing method used by tests, select the implementation class expected to define that method before selecting tests.
- If javac reports an imaginary test helper class, select the test file.
- If javac/maven reports "cannot find symbol", select the file that should define the missing symbol and the file that uses it when both are visible.
- If a public class name does not match its file name, select that Java file.
- Keep the list small: 1 to {limit} files.

JSON schema:
{{
  "summary": "short diagnosis",
  "files": [
    {{
      "path": "relative/path.java",
      "reason": "why this file should be changed",
      "priority": 1
    }}
  ]
}}

### TARGET JAVA PROJECT FILE TREE
```text
{project_tree}
```

### VALIDATION FAILURE LOG
```text
{validation_log}
```
"""


def build_python_to_java_refine_diagnosis_prompt(
    project_files: list[str],
    validation_log: str,
    limit: int = 6,
) -> str:
    return PYTHON_TO_JAVA_REFINE_DIAGNOSIS_TEMPLATE.format(
        project_tree="\n".join(f"- {path}" for path in sorted(project_files)),
        validation_log=validation_log,
        limit=limit,
    )


def parse_python_to_java_refine_diagnosis(response: str) -> dict:
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
