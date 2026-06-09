from __future__ import annotations

from src.common.models import RetrievedFile


def render_context_blocks(title: str, files: list[RetrievedFile], include_score: bool = True) -> str:
    blocks = []
    for item in files:
        score = f" (score={item.score:.2f})" if include_score else ""
        blocks.append(f"### {title}: {item.path}{score}\n```text\n{item.content}\n```")
    return "\n\n".join(blocks)


def strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text.rstrip() + "\n"
    parts = stripped.split("```")
    if len(parts) < 3:
        return text.rstrip() + "\n"
    content = parts[1]
    first_newline = content.find("\n")
    if first_newline >= 0:
        content = content[first_newline + 1 :]
    return content.rstrip() + "\n"
