from __future__ import annotations

from typing import Any, Optional, Sequence

from .models import MemoryKind, MemoryRecord
from .protocols import MemoryIndex, MemoryStore


class NullMemoryIndex(MemoryIndex):
    """
    No-op index implementation.

    Useful for:
    - tests that focus on storage or post-processing
    - configurations where no search index is available yet
    - fallback operation
    """

    def index_memory(self, memory: MemoryRecord) -> None:
        pass

    def remove_memory(self, memory_id: str) -> None:
        pass

    def search(
        self,
        user_id: str,
        query: str,
        *,
        kinds: Optional[Sequence[MemoryKind]] = None,
        limit: int = 10,
    ) -> list[str]:
        return []

    def index_conversation_summary(
        self,
        user_id: str,
        conversation_id: str,
        summary: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        pass

    def search_with_scores(
        self,
        user_id: str,
        query: str,
        *,
        kinds: Optional[Sequence[MemoryKind]] = None,
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        return []

class SimpleTextMemoryIndex(MemoryIndex):
    """
    Very simple in-process keyword matcher over MemoryStore contents.

    This is mainly for tests and lightweight local development.
    It does not maintain a separate index; it searches directly over
    the canonical store at query time.
    """

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    def index_memory(self, memory: MemoryRecord) -> None:
        """
        No-op because this implementation searches directly from the store.
        """
        pass

    def remove_memory(self, memory_id: str) -> None:
        """
        No-op because this implementation searches directly from the store.
        """
        pass

    def search(
        self,
        user_id: str,
        query: str,
        *,
        kinds: Optional[Sequence[MemoryKind]] = None,
        limit: int = 10,
    ) -> list[str]:
        query_terms = self._tokenize(query)
        if not query_terms:
            return []

        candidates = self.store.list_memories(
            user_id=user_id,
            kind=None,
            active_only=True,
            limit=1000,
        )

        if kinds is not None:
            allowed_kinds = set(kinds)
            candidates = [c for c in candidates if c.kind in allowed_kinds]

        scored: list[tuple[float, str]] = []

        for memory in candidates:
            score = self._score_memory(memory, query_terms)
            if score > 0:
                scored.append((score, memory.memory_id))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [memory_id for _, memory_id in scored[:limit]]

    def index_conversation_summary(
        self,
        user_id: str,
        conversation_id: str,
        summary: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        No-op for this lightweight implementation.
        """
        pass

    def _tokenize(self, text: str) -> set[str]:
        return {term.strip().lower() for term in text.split() if term.strip()}

    def _score_memory(self, memory: MemoryRecord, query_terms: set[str]) -> float:
        """
        Crude scoring based on term presence across fields, with light weighting.
        """
        score = 0.0

        kind_terms = self._tokenize(memory.kind)
        tag_terms = {tag.lower() for tag in memory.tags}
        summary_terms = self._tokenize(memory.summary or "")
        content_terms = self._tokenize(memory.content)
        subject_terms = self._tokenize(memory.subject or "")
        project_terms = self._tokenize(memory.project_id or "")
        task_terms = self._tokenize(memory.task_id or "")

        for term in query_terms:
            if term in kind_terms:
                score += 1.0
            if term in tag_terms:
                score += 2.0
            if term in subject_terms:
                score += 1.5
            if term in project_terms:
                score += 1.5
            if term in task_terms:
                score += 1.5
            if term in summary_terms:
                score += 2.5
            if term in content_terms:
                score += 1.5

        # Slight boost for more important / confident memories
        score += 0.2 * memory.importance
        score += 0.1 * memory.confidence

        return score

    def search(
            self,
            user_id: str,
            query: str,
            *,
            kinds: Optional[Sequence[MemoryKind]] = None,
            limit: int = 10,
    ) -> list[str]:
        return [
            memory_id
            for memory_id, _ in self.search_with_scores(
                    user_id=user_id,
                    query=query,
                    kinds=kinds,
                    limit=limit,
            )
        ]

    def search_with_scores(
            self,
            user_id: str,
            query: str,
            *,
            kinds: Optional[Sequence[MemoryKind]] = None,
            limit: int = 10,
    ) -> list[tuple[str, float]]:
        query_terms = self._tokenize(query)
        if not query_terms:
            return []

        candidates = self.store.list_memories(
            user_id=user_id,
            kind=None,
            active_only=True,
            limit=1000,
        )

        if kinds is not None:
            allowed_kinds = set(kinds)
            candidates = [c for c in candidates if c.kind in allowed_kinds]

        scored: list[tuple[float, str]] = []
        for memory in candidates:
            score = self._score_memory(memory, query_terms)
            if score > 0:
                scored.append((score, memory.memory_id))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [(memory_id, score) for score, memory_id in scored[:limit]]
