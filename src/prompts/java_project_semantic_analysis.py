from __future__ import annotations

import json

from src.common.models import RepoAnalysis


JAVA_PROJECT_SEMANTIC_ANALYSIS_SYSTEM_PROMPT = """You are a senior software architect analyzing a Java repository.
Use only the provided file tree, build metadata, and Java class frameworks.
Do not invent code behavior that is not supported by the provided structure.
Return a concise Chinese Markdown report."""


JAVA_PROJECT_SEMANTIC_ANALYSIS_TEMPLATE = """请基于下面的静态分析结果，输出这个 Java 项目的动态语义分析报告。

报告必须包含：
1. 项目一句话概述：这个项目大概率是做什么的。
2. 主要业务/技术模块。
3. 目录结构说明。
4. Java 版本与构建工具信息。
5. 关键类与职责。
6. 运行时框架/依赖线索。
7. 对后续 repo-level code translation 的迁移建议。

注意：
- 输入只保留 File Tree 和 Java class framework，不包含方法体实现。
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

## JAVA_CLASS_FRAMEWORKS
```text
{class_frameworks}
```
"""


def build_java_project_semantic_analysis_prompt(analysis: RepoAnalysis) -> str:
    return JAVA_PROJECT_SEMANTIC_ANALYSIS_TEMPLATE.format(
        file_tree=format_file_tree_for_prompt(analysis.file_tree),
        build_info=json.dumps(analysis.build_info, ensure_ascii=False, indent=2),
        class_frameworks=format_java_class_frameworks_for_prompt(analysis),
    )


def format_file_tree_for_prompt(file_tree: dict) -> str:
    root = file_tree.get("root", ".")
    tree = file_tree.get("tree", {})
    lines = [str(root)]
    lines.extend(_format_tree_entries(tree))
    file_count = file_tree.get("file_count")
    if file_count is not None:
        lines.append(f"\n{file_count} files")
    return "\n".join(lines)


def format_java_class_frameworks_for_prompt(analysis: RepoAnalysis) -> str:
    return _format_class_frameworks(_class_frameworks(analysis))


def _format_tree_entries(tree: dict, prefix: str = "") -> list[str]:
    lines = []
    entries = sorted(tree.items(), key=lambda item: (not isinstance(item[1], dict), item[0].lower()))
    for index, (name, value) in enumerate(entries):
        is_last = index == len(entries) - 1
        connector = "`-- " if is_last else "|-- "
        if isinstance(value, dict):
            lines.append(f"{prefix}{connector}{name}/")
            child_prefix = prefix + ("    " if is_last else "|   ")
            lines.extend(_format_tree_entries(value, child_prefix))
        else:
            lines.append(f"{prefix}{connector}{name} [{value}]")
    return lines


def _class_frameworks(analysis: RepoAnalysis) -> list[dict]:
    frameworks = []
    for file_info in analysis.files:
        ast_tree = file_info.ast_tree
        types = []
        for type_node in ast_tree.get("types", []):
            types.append(
                {
                    "kind": type_node.get("kind"),
                    "declaration": _type_declaration(type_node),
                    "annotations": type_node.get("annotations", []),
                    "fields": [
                        {
                            "name": field.get("name"),
                            "type": field.get("type"),
                            "modifiers": field.get("modifiers", []),
                            "annotations": field.get("annotations", []),
                        }
                        for field in type_node.get("fields", [])
                    ],
                    "constructors": [
                        {
                            "name": constructor.get("name"),
                            "parameters": constructor.get("parameters", []),
                            "modifiers": constructor.get("modifiers", []),
                        }
                        for constructor in type_node.get("constructors", [])
                    ],
                    "method_signatures": [
                        {
                            "name": method.get("name"),
                            "return_type": method.get("return_type"),
                            "parameters": method.get("parameters", []),
                            "modifiers": method.get("modifiers", []),
                            "annotations": method.get("annotations", []),
                        }
                        for method in type_node.get("methods", [])
                    ],
                }
            )
        frameworks.append(
            {
                "path": file_info.path,
                "package": file_info.package,
                "imports": file_info.imports,
                "types": types,
            }
        )
    return frameworks


def _format_class_frameworks(frameworks: list[dict]) -> str:
    blocks = []
    for framework in frameworks:
        lines = [f"FILE: {framework.get('path', '')}"]
        package_name = framework.get("package")
        if package_name:
            lines.append(f"PACKAGE: {package_name}")
        imports = framework.get("imports", [])
        if imports:
            lines.append("IMPORTS:")
            lines.extend(f"  - {item}" for item in imports)
        for type_node in framework.get("types", []):
            lines.extend(_format_type_framework(type_node))
        blocks.append("\n".join(lines))
    return "\n\n---\n\n".join(blocks)


def _format_type_framework(type_node: dict) -> list[str]:
    lines = [
        "TYPE:",
        f"  declaration: {type_node.get('declaration', '')}",
    ]
    annotations = type_node.get("annotations", [])
    if annotations:
        lines.append(f"  annotations: {', '.join(annotations)}")

    fields = type_node.get("fields", [])
    lines.append("  fields:")
    if fields:
        lines.extend(f"    - {_format_field(field)}" for field in fields)
    else:
        lines.append("    - none")

    constructors = type_node.get("constructors", [])
    lines.append("  constructors:")
    if constructors:
        lines.extend(f"    - {_format_constructor(constructor)}" for constructor in constructors)
    else:
        lines.append("    - none")

    methods = type_node.get("method_signatures", [])
    lines.append("  methods:")
    if methods:
        lines.extend(f"    - {_format_method(method)}" for method in methods)
    else:
        lines.append("    - none")
    return lines


def _format_field(field: dict) -> str:
    prefix = _format_modifiers(field.get("modifiers", []))
    annotations = _format_annotations(field.get("annotations", []))
    signature = f"{field.get('type', '')} {field.get('name', '')}".strip()
    return " ".join(item for item in [annotations, prefix, signature] if item)


def _format_constructor(constructor: dict) -> str:
    prefix = _format_modifiers(constructor.get("modifiers", []))
    params = _format_parameters(constructor.get("parameters", []))
    signature = f"{constructor.get('name', '')}({params})"
    return " ".join(item for item in [prefix, signature] if item)


def _format_method(method: dict) -> str:
    annotations = _format_annotations(method.get("annotations", []))
    prefix = _format_modifiers(method.get("modifiers", []))
    params = _format_parameters(method.get("parameters", []))
    return_type = method.get("return_type") or "void"
    signature = f"{return_type} {method.get('name', '')}({params})"
    return " ".join(item for item in [annotations, prefix, signature] if item)


def _format_parameters(parameters: list[dict]) -> str:
    return ", ".join(
        " ".join(item for item in [parameter.get("type", ""), parameter.get("name", "")] if item)
        for parameter in parameters
    )


def _format_modifiers(modifiers: list[str]) -> str:
    return " ".join(modifiers)


def _format_annotations(annotations: list[str]) -> str:
    return " ".join(f"@{annotation}" for annotation in annotations)


def _type_declaration(type_node: dict) -> str:
    modifiers = " ".join(type_node.get("modifiers", []))
    kind = type_node.get("kind", "type")
    name = type_node.get("name", "")
    extends = type_node.get("extends", [])
    implements = type_node.get("implements", [])
    parts = [item for item in [modifiers, kind, name] if item]
    if extends:
        parts.extend(["extends", ", ".join(extends)])
    if implements:
        parts.extend(["implements", ", ".join(implements)])
    return " ".join(parts)
