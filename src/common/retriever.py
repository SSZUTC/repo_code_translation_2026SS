from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from src.common.models import RetrievedFile
from src.common.io_utils import iter_text_files, read_text


TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


class FileRetriever:
    ignored_dirs = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "site-packages",
        "target",
    }

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.files = [path for path in iter_text_files(self.root) if not self._is_ignored(path)]
        self.documents = [(path, read_text(path, max_chars=30000)) for path in self.files]
        self.term_counts = [Counter(tokenize(content + " " + path.as_posix())) for path, content in self.documents]
        self.document_frequency = Counter()
        for counts in self.term_counts:
            self.document_frequency.update(counts.keys())

    def retrieve(self, query: str, top_k: int = 6) -> list[RetrievedFile]:
        query_terms = Counter(tokenize(query))
        if not query_terms:
            return []
        scored = []
        total_docs = max(len(self.documents), 1)
        for (path, content), counts in zip(self.documents, self.term_counts):
            score = 0.0
            for term, query_count in query_terms.items():
                if term not in counts:
                    continue
                idf = math.log((1 + total_docs) / (1 + self.document_frequency[term])) + 1
                score += query_count * counts[term] * idf
            if score > 0:
                scored.append((score, path, content))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            RetrievedFile(path=path.relative_to(self.root).as_posix(), score=score, content=content)
            for score, path, content in scored[:top_k]
        ]

    def _is_ignored(self, path: Path) -> bool:
        return any(part in self.ignored_dirs for part in path.parts)
