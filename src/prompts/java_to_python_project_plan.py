from __future__ import annotations

import json
from typing import Any

from src.common.models import RepoAnalysis, ProjectPlan, TranslationTask
from src.prompts.formatting import strip_markdown_fence
from src.prompts.java_project_semantic_analysis import (
    format_file_tree_for_prompt,
    format_java_class_frameworks_for_prompt,
)


JAVA_TO_PYTHON_PROJECT_PLANNER_SYSTEM_PROMPT = """You are a senior repository-level code translation architect.
Design a Python 3.10 project plan for translating the given Java repository.
Return strict JSON only. Do not include Markdown fences or commentary."""


JAVA_TO_PYTHON_PROJECT_PLAN_TEMPLATE = """请基于下面输入，为 Java -> Python repo-level code translation 生成总体 Python 项目规划。

目标：
- Python 版本固定为 Python 3.10。
- 输出目标 Python 项目的架构设计、目录模块设计、Python 文件树、requirements 依赖、逐文件翻译任务。
- 规划要服务于后续“逐文件生成”，所以每个 Python 文件必须能追溯到相关 Java 文件。
- 不要机械保留 Java package 路径；要设计成真实 Python Web/服务项目目录。
- 严禁生成 app/java/... 这类目标路径。
- 严禁把 org/commoncrawl、com/taskflow 等 Java package 路径原样搬到 Python 目标项目。
- 目标 Python 目录应该按照功能模块命名，例如 app/core、app/services、app/models、app/routes、app/news、app/filters、tests。
- 如果源项目是 Spring Boot Web 项目，优先迁移为 FastAPI 或 Flask 项目，并在 requirements 中体现。
- 如果源项目不是 Web 项目，优先迁移为清晰的 Python package + pytest 测试结构。
- requirements 中必须包含运行和测试需要的依赖，Python 版本写 3.10，不要写 3.11/3.12。
- requirements 只允许写裸包名，不允许写版本限制、版本区间、兼容符号或 environment marker。例如写 pytest，不要写 pytest>=7,<8。
- 不要为源 Java 项目没有对应语义的功能主动加入第三方包。纯算法库通常只需要 pytest，甚至不需要运行时依赖。

输出必须是严格 JSON，结构如下：
{{
  "python_version": "3.10",
  "architecture_design": "目标 Python 项目的总体架构说明",
  "directory_module_design": [
    {{"path": "app/services", "purpose": "业务服务层"}}
  ],
  "python_file_tree": [
    "app/__init__.py",
    "app/main.py"
  ],
  "requirements": [
    "fastapi",
    "pytest"
  ],
  "verification_commands": [
    "python -m compileall app",
    "python -m pytest"
  ],
  "tasks": [
    {{
      "target_path": "app/main.py",
      "target_role": "application",
      "source_files": ["src/main/java/.../Application.java"],
      "description": "生成 Python 应用入口，映射 Java 启动类和运行配置。",
      "dependencies": ["fastapi"],
      "planned_exports": ["create_app", "app"],
      "planned_imports": ["fastapi.FastAPI", "app.routes.api.router"]
    }}
  ]
}}

字段约束：
- tasks[].target_path 必须出现在 python_file_tree 中。
- requirements.txt 必须作为一个 task，description 中说明要写入完整 requirements 内容；内容只允许裸包名，不允许版本约束。
- README.md 必须作为一个 task，说明目标项目如何运行和测试。
- 测试文件放到 tests/，并从 Java test 文件映射到 pytest。
- 静态资源和模板可以复制/适配，source_files 必须指向原始资源文件。
- 源项目配置文件和规则文件如果影响运行语义，需要放入 config/ 或 app/resources/，并创建对应 task。
- dependencies 写源文件或目标模块依赖线索即可，不要求完整包管理图。
- 每个 Python 源码/测试文件 task 必须规划 planned_exports 和 planned_imports。
- planned_exports 写该文件对外提供的 class/function/constant 名称，例如 ContentDetector、detect_content、URLFilterRule。
- planned_imports 写该文件预计 import 的外部包或项目内模块，例如 pathlib.Path、app.core.url_filter.FastURLFilter。
- 对 requirements.txt、README.md、yaml/json/xml/css/html 这类非 Python 文件，planned_exports/planned_imports 可以为空数组。
- 输出 JSON 中不要包含方法体代码。

## DYNAMIC_PROJECT_SEMANTICS
```markdown
{project_semantics}
```

## SOURCE_FILE_TREE
```text
{file_tree}
```

## JAVA_CLASS_FRAMEWORKS
```text
{class_frameworks}
```

"""


def build_java_to_python_project_plan_prompt(
    analysis: RepoAnalysis,
    project_semantics: str,
    deterministic_plan: ProjectPlan,
) -> str:
    return JAVA_TO_PYTHON_PROJECT_PLAN_TEMPLATE.format(
        project_semantics=project_semantics.strip() or "未生成动态语义分析报告。",
        file_tree=format_file_tree_for_prompt(analysis.file_tree),
        class_frameworks=format_java_class_frameworks_for_prompt(analysis),
    )


def parse_java_to_python_project_plan(text: str, fallback: ProjectPlan) -> tuple[ProjectPlan, dict[str, Any]]:
    try:
        data = json.loads(strip_markdown_fence(text).strip())
    except Exception:
        return fallback, {"parse_error": True, "raw_response": text}

    tasks = []
    for item in data.get("tasks", []):
        target_path = item.get("target_path")
        if not target_path:
            continue
        tasks.append(
            TranslationTask(
                target_path=target_path,
                target_role=item.get("target_role", "unknown"),
                source_files=item.get("source_files", []),
                description=item.get("description", ""),
                dependencies=item.get("dependencies", []),
                planned_exports=item.get("planned_exports", []),
                planned_imports=item.get("planned_imports", []),
            )
        )

    if not tasks:
        return fallback, data

    _ensure_project_planning_tasks(tasks, data)
    architecture = data.get("architecture_design") or fallback.architecture
    verification_commands = data.get("verification_commands") or fallback.verification_commands
    return (
        ProjectPlan(
            source_project=fallback.source_project,
            target_project=fallback.target_project,
            architecture=f"Python 3.10 target architecture. {architecture}",
            tasks=tasks,
            verification_commands=verification_commands,
        ),
        data,
    )


def _format_draft_tasks(plan: ProjectPlan) -> str:
    lines = []
    for index, task in enumerate(plan.tasks, start=1):
        sources = ", ".join(task.source_files) if task.source_files else "none"
        dependencies = ", ".join(task.dependencies) if task.dependencies else "none"
        lines.append(
            f"{index}. target={task.target_path} | role={task.target_role} | "
            f"sources={sources} | dependencies={dependencies} | description={task.description}"
        )
    return "\n".join(lines)


def _ensure_project_planning_tasks(tasks: list[TranslationTask], data: dict[str, Any]) -> None:
    by_path = {task.target_path: task for task in tasks}
    requirements = _sanitize_requirements(data.get("requirements", []))
    requirements_description = "Write Python 3.10 requirements with package names only, no version constraints: " + ", ".join(requirements)
    if "requirements.txt" in by_path:
        by_path["requirements.txt"].target_role = "requirements"
        by_path["requirements.txt"].description = requirements_description
        by_path["requirements.txt"].dependencies = requirements
        by_path["requirements.txt"].planned_exports = []
        by_path["requirements.txt"].planned_imports = []
    else:
        tasks.insert(
            0,
            TranslationTask(
                target_path="requirements.txt",
                target_role="requirements",
                source_files=[],
                description=requirements_description,
                dependencies=requirements,
                planned_exports=[],
                planned_imports=[],
            ),
        )
    if "README.md" in by_path:
        by_path["README.md"].target_role = "documentation"
        by_path["README.md"].planned_exports = []
        by_path["README.md"].planned_imports = []
        if "Python 3.10" not in by_path["README.md"].description:
            by_path["README.md"].description = (
                by_path["README.md"].description.rstrip(".")
                + ". Document Python 3.10 installation, runtime commands, and pytest validation."
            )
    else:
        tasks.append(
            TranslationTask(
                target_path="README.md",
                target_role="documentation",
                source_files=[],
                description="Document how to install, run, and test the translated Python 3.10 project.",
                planned_exports=[],
                planned_imports=[],
            )
        )


def _sanitize_requirements(requirements: Any) -> list[str]:
    if not isinstance(requirements, list):
        return []
    cleaned = []
    for item in requirements:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if not value:
            continue
        value = value.split(";", 1)[0].strip()
        value = value.split("[", 1)[0].strip()
        value = re_split_requirement(value)
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def re_split_requirement(value: str) -> str:
    for marker in ["==", ">=", "<=", "~=", "!=", ">", "<", "="]:
        if marker in value:
            return value.split(marker, 1)[0].strip()
    return value
