from __future__ import annotations

import json
from typing import Any

from src.common.models import ProjectPlan, RepoAnalysis, TranslationTask
from src.prompts.formatting import strip_markdown_fence
from src.prompts.java_project_semantic_analysis import format_file_tree_for_prompt
from src.prompts.python_project_semantic_analysis import format_python_module_frameworks_for_prompt


PYTHON_TO_JAVA_PROJECT_PLANNER_SYSTEM_PROMPT = """You are a senior repository-level code translation architect.
Design a Java Maven project plan for translating the given Python repository.
Return strict JSON only. Do not include Markdown fences or commentary."""


PYTHON_TO_JAVA_PROJECT_PLAN_TEMPLATE = """请基于下面输入，为 Python -> Java repo-level code translation 生成总体 Java 项目规划。

目标：
- 目标项目固定为 Java + Maven。
- 输出目标 Java 项目的架构设计、目录模块设计、Java 文件树、pom.xml 依赖、逐文件翻译任务。
- 规划要服务于后续“逐文件生成”，所以每个 Java 文件必须能追溯到相关 Python 文件。
- 不要机械保留 Python package 路径；要设计成真实 Java 项目目录。
- Java 源码必须放在 src/main/java/<package>/Name.java。
- Java 测试必须放在 src/test/java/<package>/NameTest.java。
- 构建文件必须是 pom.xml。
- 静态资源和模板可以放在 src/main/resources/static 或 src/main/resources/templates。
- 严禁生成任何 .py 目标文件。
- 默认只使用 JDK 标准库和 JUnit 5。不要为了字符串相似度、集合处理、JSON 小逻辑、日期时间、正则、文件 I/O 主动引入第三方依赖。
- 只有当 Python 源项目显式依赖某个外部库，且 JDK 标准库无法合理替代时，才允许把等价 Java 依赖加入 pom.xml。
- 如果源项目依赖的是 Python 标准库，例如 difflib、re、json、csv、time、collections，Java 规划必须用 JDK 自带能力或项目内自实现代码完成。
- 测试规划必须跟随简化后的 Python test 文件，不要生成比源测试更细、更强或访问私有方法的 JUnit 测试。

输出必须是严格 JSON，结构如下：
{{
  "java_version": "17",
  "build_tool": "maven",
  "architecture_design": "目标 Java 项目的总体架构说明",
  "directory_module_design": [
    {{"path": "src/main/java/com/example/service", "purpose": "业务服务层"}}
  ],
  "java_file_tree": [
    "pom.xml",
    "src/main/java/com/example/Application.java"
  ],
  "maven_dependencies": [
    {{"groupId": "org.junit.jupiter", "artifactId": "junit-jupiter", "version": "5.10.2", "scope": "test"}}
  ],
  "verification_commands": [
    "mvn -q test"
  ],
  "tasks": [
    {{
      "target_path": "src/main/java/com/example/Application.java",
      "target_role": "application",
      "source_files": ["app/main.py"],
      "description": "生成 Java 应用入口，映射 Python 应用启动逻辑。",
      "dependencies": ["maven"],
      "planned_exports": ["Application"],
      "planned_imports": ["java.util.List"]
    }}
  ]
}}

字段约束：
- tasks[].target_path 必须出现在 java_file_tree 中。
- pom.xml 必须作为一个 task，description 中说明要写入完整 Maven 依赖和 Java 版本。
- README.md 必须作为一个 task，说明目标 Java 项目如何运行和测试。
- 源码文件放到 src/main/java/，测试文件放到 src/test/java/。
- 测试文件从 Python test 文件映射到 JUnit。
- 静态资源和模板可以复制/适配，source_files 必须指向原始资源文件。
- 源项目配置文件如果影响运行语义，需要放入 src/main/resources/，并创建对应 task。
- dependencies 写源文件或目标模块依赖线索即可，不要求完整包管理图。
- 每个 Java 源码/测试文件 task 必须规划 planned_exports 和 planned_imports。
- planned_exports 写该文件对外提供的 class/interface/enum 名称，例如 TaskService、TaskStatus、ProjectRepository。
- planned_imports 写该文件预计 import 的 JDK、第三方或项目内类型，例如 java.time.LocalDate、com.example.model.Task。
- planned_imports 中不要出现不存在或未在 maven_dependencies 中声明的第三方包。
- 对算法型项目，优先规划少量核心类和测试类，避免从 benchmark、release 脚本、历史 changelog 生成目标文件。
- 对 pom.xml、README.md、yaml/json/xml/css/html 这类非 Java 文件，planned_exports/planned_imports 可以为空数组。
- 输出 JSON 中不要包含方法体代码。

## DYNAMIC_PROJECT_SEMANTICS
```markdown
{project_semantics}
```

## SOURCE_FILE_TREE
```text
{file_tree}
```

## PYTHON_MODULE_FRAMEWORKS
```text
{module_frameworks}
```

"""


def build_python_to_java_project_plan_prompt(
    analysis: RepoAnalysis,
    project_semantics: str,
    deterministic_plan: ProjectPlan,
) -> str:
    return PYTHON_TO_JAVA_PROJECT_PLAN_TEMPLATE.format(
        project_semantics=project_semantics.strip() or "未生成动态语义分析报告。",
        file_tree=format_file_tree_for_prompt(analysis.file_tree),
        module_frameworks=format_python_module_frameworks_for_prompt(analysis),
    )


def parse_python_to_java_project_plan(text: str, fallback: ProjectPlan) -> tuple[ProjectPlan, dict[str, Any]]:
    try:
        data = json.loads(strip_markdown_fence(text).strip())
    except Exception:
        return fallback, {"parse_error": True, "raw_response": text}

    tasks = []
    for item in data.get("tasks", []):
        target_path = item.get("target_path")
        if not target_path or not _valid_target_path(target_path):
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
            architecture=f"Java Maven target architecture. {architecture}",
            tasks=tasks,
            verification_commands=verification_commands,
        ),
        data,
    )


def _ensure_project_planning_tasks(tasks: list[TranslationTask], data: dict[str, Any]) -> None:
    by_path = {task.target_path: task for task in tasks}
    dependencies = _sanitize_maven_dependencies(data.get("maven_dependencies", []))
    dependency_text = json.dumps(dependencies, ensure_ascii=False)
    pom_description = "Write Maven pom.xml for the translated Java project. Dependencies: " + dependency_text
    if "pom.xml" in by_path:
        by_path["pom.xml"].target_role = "build"
        by_path["pom.xml"].description = pom_description
        by_path["pom.xml"].dependencies = ["maven", *[item.get("artifactId", "") for item in dependencies if isinstance(item, dict)]]
        by_path["pom.xml"].planned_exports = []
        by_path["pom.xml"].planned_imports = []
    else:
        tasks.insert(
            0,
            TranslationTask(
                target_path="pom.xml",
                target_role="build",
                source_files=[],
                description=pom_description,
                dependencies=["maven"],
                planned_exports=[],
                planned_imports=[],
            ),
        )

    if "README.md" in by_path:
        by_path["README.md"].target_role = "documentation"
        by_path["README.md"].planned_exports = []
        by_path["README.md"].planned_imports = []
        if "Maven" not in by_path["README.md"].description:
            by_path["README.md"].description = (
                by_path["README.md"].description.rstrip(".")
                + ". Document Maven commands, Java version, and test validation."
            )
    else:
        tasks.append(
            TranslationTask(
                target_path="README.md",
                target_role="documentation",
                source_files=[],
                description="Document how to build, run, and test the translated Java Maven project.",
                planned_exports=[],
                planned_imports=[],
            )
        )


def _valid_target_path(path: str) -> bool:
    if not path or path.endswith(".py"):
        return False
    if path == "pom.xml" or path.endswith(".md"):
        return True
    if path.startswith("src/main/java/") and path.endswith(".java"):
        return True
    if path.startswith("src/test/java/") and path.endswith(".java"):
        return True
    if path.startswith("src/main/resources/"):
        return True
    return False


def _sanitize_maven_dependencies(dependencies: Any) -> list[dict[str, Any]]:
    if not isinstance(dependencies, list):
        dependencies = []
    sanitized: list[dict[str, Any]] = []
    blocked_artifacts = {
        "simmetrics-core",
        "commons-text",
        "commons-lang3",
        "javafx-base",
        "guava",
    }
    for item in dependencies:
        if not isinstance(item, dict):
            continue
        group_id = str(item.get("groupId", ""))
        artifact_id = str(item.get("artifactId", ""))
        scope = str(item.get("scope", ""))
        if artifact_id in blocked_artifacts:
            continue
        if group_id.startswith("org.junit") or scope == "test":
            sanitized.append(item)
    if not any(item.get("artifactId") == "junit-jupiter" for item in sanitized):
        sanitized.insert(
            0,
            {
                "groupId": "org.junit.jupiter",
                "artifactId": "junit-jupiter",
                "version": "5.10.2",
                "scope": "test",
            },
        )
    return sanitized
