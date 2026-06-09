from __future__ import annotations

import json

from src.common.models import RepoAnalysis
from src.prompts.java_project_semantic_analysis import format_file_tree_for_prompt


PYTHON_PROJECT_SEMANTIC_ANALYSIS_SYSTEM_PROMPT = """You are a senior software architect analyzing a Python repository.
Use only the provided file tree, build metadata, and Python module frameworks.
Do not invent code behavior that is not supported by the provided structure.
Return a concise Chinese Markdown report."""


PYTHON_PROJECT_SEMANTIC_ANALYSIS_TEMPLATE = """请基于下面的静态分析结果，输出这个 Python 项目的动态语义分析报告。

报告必须包含：
1. 项目一句话概述：这个项目大概率是做什么的。
2. 主要业务/技术模块。
3. 目录结构说明。
4. Python 版本与构建/依赖信息。
5. 关键模块、类、函数与职责。
6. 运行时框架/依赖线索。
7. 对后续 repo-level code translation 到 Java 的迁移建议。

注意：
- 输入只保留 File Tree 和 Python module framework，不包含函数体实现。
- 不要逐字复述全部文件。
- 对不确定的信息明确写“从结构推断”。

## FILE_TREE
```text
{file_tree}
```

## BUILD_INFO
```json
{build_info}
```

## PYTHON_MODULE_FRAMEWORKS
```text
{module_frameworks}
```
"""


def build_python_project_semantic_analysis_prompt(analysis: RepoAnalysis) -> str:
    return PYTHON_PROJECT_SEMANTIC_ANALYSIS_TEMPLATE.format(
        file_tree=format_file_tree_for_prompt(analysis.file_tree),
        build_info=json.dumps(analysis.build_info, ensure_ascii=False, indent=2),
        module_frameworks=format_python_module_frameworks_for_prompt(analysis),
    )


def format_python_module_frameworks_for_prompt(analysis: RepoAnalysis) -> str:
    blocks = []
    for file_info in analysis.files:
        ast_tree = file_info.ast_tree
        lines = [f"FILE: {file_info.path}", f"MODULE: {ast_tree.get('module', file_info.package)}"]
        imports = ast_tree.get("imports", [])
        if imports:
            lines.append("IMPORTS:")
            lines.extend(f"  - {_format_import(item)}" for item in imports)
        assignments = ast_tree.get("assignments", [])
        if assignments:
            lines.append("MODULE ASSIGNMENTS:")
            lines.extend(f"  - {_format_assignment(item)}" for item in assignments)
        classes = ast_tree.get("classes", [])
        if classes:
            lines.append("CLASSES:")
            for class_node in classes:
                lines.extend(_format_class(class_node, indent="  "))
        functions = ast_tree.get("functions", [])
        if functions:
            lines.append("TOP LEVEL FUNCTIONS:")
            lines.extend(f"  - {_format_function(item)}" for item in functions)
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(blocks)


def _format_import(item: dict) -> str:
    if item.get("node_type") == "ImportFrom":
        symbol = item.get("symbol", "")
        alias = f" as {item.get('alias')}" if item.get("alias") else ""
        return f"from {item.get('name', '')} import {symbol}{alias}"
    alias = f" as {item.get('alias')}" if item.get("alias") else ""
    return f"import {item.get('name', '')}{alias}"


def _format_assignment(item: dict) -> str:
    annotation = f": {item.get('annotation')}" if item.get("annotation") else ""
    return f"{item.get('name', '')}{annotation}"


def _format_class(class_node: dict, indent: str = "") -> list[str]:
    bases = class_node.get("bases", [])
    base_text = f"({', '.join(bases)})" if bases else ""
    lines = [f"{indent}- class {class_node.get('name', '')}{base_text}"]
    decorators = class_node.get("decorators", [])
    if decorators:
        lines.append(f"{indent}  decorators: {', '.join(decorators)}")
    fields = class_node.get("fields", [])
    lines.append(f"{indent}  fields:")
    if fields:
        lines.extend(f"{indent}    - {_format_assignment(item)}" for item in fields)
    else:
        lines.append(f"{indent}    - none")
    methods = class_node.get("methods", [])
    lines.append(f"{indent}  methods:")
    if methods:
        lines.extend(f"{indent}    - {_format_function(item)}" for item in methods)
    else:
        lines.append(f"{indent}    - none")
    return lines


def _format_function(function_node: dict) -> str:
    prefix = "async " if function_node.get("is_async") else ""
    params = ", ".join(_format_parameter(item) for item in function_node.get("parameters", []))
    returns = f" -> {function_node.get('returns')}" if function_node.get("returns") else ""
    decorators = function_node.get("decorators", [])
    decorator_text = f" [{', '.join(decorators)}]" if decorators else ""
    return f"{prefix}def {function_node.get('name', '')}({params}){returns}{decorator_text}"


def _format_parameter(parameter: dict) -> str:
    annotation = f": {parameter.get('annotation')}" if parameter.get("annotation") else ""
    default = " = ..." if parameter.get("has_default") else ""
    return f"{parameter.get('name', '')}{annotation}{default}"
