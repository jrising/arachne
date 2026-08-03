from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Sequence

from whoosh import index
from whoosh.fields import ID, KEYWORD, STORED, TEXT, Schema
from whoosh.qparser import MultifieldParser, OrGroup
from whoosh.query import Term, And, Or

from .models import MemoryKind, MemoryRecord
from .protocols import MemoryIndex
from .abbreviate import extract_keywords


class WhooshMemoryIndex(MemoryIndex):
    """
    Whoosh-backed index for memory retrieval.

    Indexes:
    - durable MemoryRecord objects
    - conversation summaries as searchable documents

    Notes:
    - user_id is always indexed and filtered on retrieval
    - `search()` returns memory_ids only
    - conversation summaries may be indexed without corresponding memory records
      (unless you separately save them as MemoryRecord entries)
    """

    INDEX_VERSION = "1"

    def __init__(self, index_dir: str | Path) -> None:
        self.index_dir = Path(index_dir)
        self.index_dir.mkdir(parents=True, exist_ok=True)

        if index.exists_in(self.index_dir):
            self.ix = index.open_dir(self.index_dir)
        else:
            self.ix = index.create_in(self.index_dir, self._build_schema())

    def _build_schema(self) -> Schema:
        return Schema(
            # primary identifiers
            doc_id=ID(stored=True, unique=True),
            doc_type=ID(stored=True),  # "memory" or "conversation_summary"
            user_id=ID(stored=True),
            memory_id=ID(stored=True),
            conversation_id=ID(stored=True),

            # searchable/filterable fields
            kind=ID(stored=True),
            tags=KEYWORD(stored=True, commas=True, lowercase=True),
            source=ID(stored=True),

            # textual content
            title=TEXT(stored=False),
            summary=TEXT(stored=True),
            content=TEXT(stored=False),

            # optional metadata
            metadata_json=STORED,
            version=ID(stored=True),
        )

    def _memory_doc_id(self, memory_id: str) -> str:
        return f"memory:{memory_id}"

    def _conversation_doc_id(self, user_id: str, conversation_id: str) -> str:
        return f"conversation_summary:{user_id}:{conversation_id}"

    def index_memory(self, memory: MemoryRecord) -> None:
        """
        Add or replace a durable memory record in the index.
        """
        doc_id = self._memory_doc_id(memory.memory_id)

        with self.ix.writer() as writer:
            writer.update_document(
                doc_id=doc_id,
                doc_type="memory",
                user_id=memory.user_id,
                memory_id=memory.memory_id,
                conversation_id=memory.conversation_id or "",
                kind=memory.kind,
                tags=",".join(memory.tags),
                source=memory.source,
                title=self._make_title(memory),
                summary=memory.summary or memory.content[:500],
                content=memory.content,
                metadata_json=dict(memory.metadata),
                version=self.INDEX_VERSION,
            )

    def remove_memory(self, memory_id: str) -> None:
        """
        Remove a memory document from the index.
        """
        doc_id = self._memory_doc_id(memory_id)
        with self.ix.writer() as writer:
            writer.delete_by_term("doc_id", doc_id)

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

    def index_conversation_summary(
        self,
        user_id: str,
        conversation_id: str,
        summary: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Index a conversation summary as a searchable document.

        This does not make it retrievable via `search()` unless you also save
        a corresponding MemoryRecord and index that record, because `search()`
        intentionally returns only memory_ids.

        Still useful if you later want separate conversation-search APIs.
        """
        doc_id = self._conversation_doc_id(user_id, conversation_id)

        with self.ix.writer() as writer:
            writer.update_document(
                doc_id=doc_id,
                doc_type="conversation_summary",
                user_id=user_id,
                memory_id="",
                conversation_id=conversation_id,
                kind="conversation_summary",
                tags="conversation,summary",
                source="conversation_summary",
                title=f"Conversation {conversation_id}",
                summary=summary[:2000],
                content=summary,
                metadata_json=dict(metadata or {}),
                version=self.INDEX_VERSION,
            )

    def search_conversation_summaries(
        self,
        user_id: str,
        query: str,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Optional helper for searching historical conversation summaries directly.
        Returns lightweight hit dicts instead of memory_ids.
        """
        if not query.strip():
            return []

        parser = MultifieldParser(
            ["title", "summary", "content"],
            schema=self.ix.schema,
            group=OrGroup.factory(0.9),
        )
        parsed_query = parser.parse(query)

        results: list[dict[str, Any]] = []

        with self.ix.searcher() as searcher:
            raw_results = searcher.search(parsed_query, limit=limit * 5)

            for hit in raw_results:
                if hit.get("doc_type") != "conversation_summary":
                    continue
                if hit.get("user_id") != user_id:
                    continue

                results.append(
                    {
                        "conversation_id": hit.get("conversation_id"),
                        "summary": hit.get("summary"),
                        "metadata": hit.get("metadata_json") or {},
                    }
                )

                if len(results) >= limit:
                    break

        return results

    def rebuild_from_memories(
        self,
        memories: Sequence[MemoryRecord],
    ) -> None:
        """
        Rebuild the index from a sequence of memory records.

        Warning:
        - this clears the existing index directory contents logically by
          recreating the index in place.
        - call only in maintenance/admin contexts.
        """
        self.ix = index.create_in(self.index_dir, self._build_schema())

        with self.ix.writer() as writer:
            for memory in memories:
                writer.add_document(
                    doc_id=self._memory_doc_id(memory.memory_id),
                    doc_type="memory",
                    user_id=memory.user_id,
                    memory_id=memory.memory_id,
                    conversation_id=memory.conversation_id or "",
                    kind=memory.kind,
                    tags=",".join(memory.tags),
                    source=memory.source,
                    title=self._make_title(memory),
                    summary=memory.summary or memory.content[:500],
                    content=memory.content,
                    metadata_json=dict(memory.metadata),
                    version=self.INDEX_VERSION,
                )

    def _make_title(self, memory: MemoryRecord) -> str:
        """
        Generate a short title-like text to improve keyword matching.
        """
        pieces: list[str] = [memory.kind]

        if memory.subject:
            pieces.append(memory.subject)
        if memory.project_id:
            pieces.append(memory.project_id)
        if memory.task_id:
            pieces.append(memory.task_id)
        if memory.tags:
            pieces.extend(memory.tags[:5])

        content_head = memory.content.strip().splitlines()[0][:120] if memory.content.strip() else ""
        if content_head:
            pieces.append(content_head)

        return " | ".join(pieces)

    def search_with_scores(
        self,
        user_id: str,
        query: str,
        *,
        kinds: Optional[Sequence[MemoryKind]] = None,
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        if not query.strip():
            return []

        parser = MultifieldParser(
            ["title", "summary", "content", "tags"],
            schema=self.ix.schema,
            group=OrGroup.factory(0.9),
        )

        clean_query = extract_keywords(query, max_keywords=20)
        if not clean_query.strip():
            clean_query = query
            
        parsed_query = parser.parse(clean_query)

        # 2. Build strict index-level filters
        filter_queries = [
            Term("doc_type", "memory"),
            Term("user_id", user_id)
        ]
        if kinds is not None:
            # Match any of the allowed kinds
            filter_queries.append(Or([Term("kind", k) for k in kinds]))

        # 3. Combine text search with strict filters using an AND clause
        # This prevents Whoosh from scoring documents that fail these criteria
        final_query = And([parsed_query] + filter_queries)

        results: list[tuple[str, float]] = []
        seen: set[str] = set()

        with self.ix.searcher() as searcher:
            raw_results = searcher.search(final_query, limit=limit)
            allowed_kinds = set(kinds) if kinds is not None else None

            for hit in raw_results:
                memory_id = hit.get("memory_id")
                if not memory_id or memory_id in seen:
                    continue

                results.append((memory_id, float(hit.score)))
                seen.add(memory_id)

        return results
