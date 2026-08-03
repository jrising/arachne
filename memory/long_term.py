from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from .conversation import ConversationMemory
from .models import (
    ConversationState,
    ConversationTranscript,
    MemoryKind,
    MemoryRecord,
    PostProcessResult,
    RetrievedMemoryBundle,
    TaskRecord,
    UserProfile,
)
from .protocols import MemoryIndex, MemoryModel, MemoryStore


class LongTermMemory:
    """
    Persistent memory orchestrator.

    Responsibilities:
    - initialize and isolate per-user durable memory
    - retrieve relevant durable memory for live conversations
    - explicitly remember / forget memory items
    - post-process completed conversations into durable memory
    - expose convenience entrypoints for starting conversations
    """

    def __init__(
        self,
        store: MemoryStore,
        model: MemoryModel,
        index: Optional[MemoryIndex] = None,
    ) -> None:
        self.store = store
        self.model = model
        self.index = index

    def initialize_user(self, user_id: str) -> None:
        """
        Ensure user storage and baseline profile exist.
        """
        self.store.create_user_if_missing(user_id)
        profile = self.store.get_user_profile(user_id)
        if profile is None:
            self.store.save_user_profile(UserProfile(user_id=user_id, updated_at=datetime.utcnow()))

    def retrieve_for_conversation(
        self,
        user_id: str,
        *,
        query: str,
        limit: int = 8,
        kinds: Optional[Sequence[MemoryKind]] = None,
    ) -> RetrievedMemoryBundle:
        """
        Retrieve relevant durable memory for a live conversation.

        Combines:
        - user profile
        - active and in-progress tasks
        - retrieved memory records from the search index (if available)
        - fallback structured memory listing

        Returns a prompt-ready bundle.
        """
        self.initialize_user(user_id)

        profile = self.store.get_user_profile(user_id)

        active_tasks = self.store.list_tasks(user_id, status="open", limit=50)
        in_progress_tasks = self.store.list_tasks(user_id, status="in_progress", limit=50)
        blocked_tasks = self.store.list_tasks(user_id, status="blocked", limit=50)

        all_tasks = self._merge_tasks(active_tasks, in_progress_tasks)
        all_tasks = self._merge_tasks(all_tasks, blocked_tasks)
        all_tasks = self._filter_relevant_tasks(all_tasks)

        candidate_map: dict[str, MemoryRecord] = {}
        query_scores: dict[str, float] = {}

        # 1. query evidence from the index
        if self.index is not None and query.strip():
            for memory_id, score in self.index.search_with_scores(
                user_id=user_id,
                query=query,
                kinds=kinds,
                limit=max(limit * 3, 20),
            ):
                memory = self.store.get_memory(user_id, memory_id)
                if memory is not None:
                    candidate_map[memory_id] = memory
                    query_scores[memory_id] = score

        # 2. prior candidates from durable store
        for memory in self.store.list_memories(
            user_id=user_id,
            kind=None,
            active_only=True,
            limit=200,
        ):
            if kinds is not None and memory.kind not in kinds:
                continue
            if memory.memory_id not in candidate_map:
                candidate_map[memory.memory_id] = memory

        ranked = sorted(
            candidate_map.values(),
            key=lambda m: self._memory_relevance_score(
                m,
                query_score=query_scores.get(m.memory_id, 0.0),
            ),
            reverse=True,
        )

        relevant_memories = ranked[:limit]
        seen_ids: set[str] = set()

        # 1. Search via index if available
        if self.index is not None and query.strip():
            memory_ids = self.index.search(
                user_id=user_id,
                query=query,
                kinds=kinds,
                limit=limit,
            )
            for memory_id in memory_ids:
                memory = self.store.get_memory(user_id, memory_id)
                if memory is not None and memory.memory_id not in seen_ids:
                    relevant_memories.append(memory)
                    seen_ids.add(memory.memory_id)

        # 2. Fallback / augmentation from store
        fallback_memories = self.store.list_memories(
            user_id=user_id,
            kind=None,
            active_only=True,
            limit=max(limit * 2, 20),
        )
        for memory in fallback_memories:
            if kinds is not None and memory.kind not in kinds:
                continue
            if memory.memory_id not in seen_ids:
                relevant_memories.append(memory)
                seen_ids.add(memory.memory_id)
            if len(relevant_memories) >= limit:
                break

        conversation_state = ConversationState(
            conversation_id="",
            user_id=user_id,
        )

        generated_summary_block = self.model.build_prompt_memory_block(
            profile=profile,
            memories=relevant_memories[:limit],
            tasks=all_tasks[:10],
            conversation_state=conversation_state,
        )

        return RetrievedMemoryBundle(
            user_id=user_id,
            query=query,
            profile=profile,
            relevant_memories=relevant_memories[:limit],
            active_tasks=all_tasks[:10],
            generated_summary_block=generated_summary_block,
        )

    def _filter_relevant_tasks(self, tasks: Sequence[TaskRecord]) -> list[TaskRecord]:
        now = datetime.utcnow()
        filtered: list[TaskRecord] = []

        for task in tasks:
            if task.status == "archived":
                continue
            age_days = (now - task.updated_at).days

            if task.status == "in_progress":
                filtered.append(task)
            elif task.status == "open" and age_days <= 45:
                filtered.append(task)
            elif task.status == "blocked" and age_days <= 30:
                filtered.append(task)

        filtered.sort(key=lambda t: t.updated_at, reverse=True)
        return filtered[:10]    

    def retrieve_by_keywords(
        self,
        user_id: str,
        *,
        query: str,
        limit: int = 10,
        kinds: Optional[Sequence[MemoryKind]] = None,
    ) -> list[MemoryRecord]:
        """
        Low-level keyword/text retrieval over durable memory.
        """
        self.initialize_user(user_id)

        if self.index is None:
            memories = self.store.list_memories(
                user_id=user_id,
                kind=None,
                active_only=True,
                limit=limit,
            )
            if kinds is not None:
                allowed = set(kinds)
                memories = [m for m in memories if m.kind in allowed]
            return memories[:limit]

        memory_ids = self.index.search(
            user_id=user_id,
            query=query,
            kinds=kinds,
            limit=limit,
        )

        results: list[MemoryRecord] = []
        for memory_id in memory_ids:
            memory = self.store.get_memory(user_id, memory_id)
            if memory is not None:
                results.append(memory)

        return results

    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        self.initialize_user(user_id)
        return self.store.get_user_profile(user_id)

    def list_user_memories(
        self,
        user_id: str,
        *,
        kind: Optional[MemoryKind] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        self.initialize_user(user_id)
        return self.store.list_memories(
            user_id=user_id,
            kind=kind,
            active_only=active_only,
            limit=limit,
        )

    def remember(self, memory: MemoryRecord) -> str:
        """
        Explicitly save a memory record and index it if applicable.
        """
        self.initialize_user(memory.user_id)
        memory_id = self.store.save_memory(memory)

        if self.index is not None:
            saved = self.store.get_memory(memory.user_id, memory_id)
            if saved is not None:
                self.index.index_memory(saved)

        return memory_id

    def forget(
        self,
        user_id: str,
        *,
        memory_id: Optional[str] = None,
        query: Optional[str] = None,
    ) -> int:
        """
        Forget one or more memories.

        If memory_id is given, deletes that one memory.
        If query is given, retrieves matching memories and deletes them.
        Returns the number of deleted memories.
        """
        self.initialize_user(user_id)

        deleted = 0

        if memory_id is not None:
            ok = self.store.delete_memory(user_id, memory_id)
            if ok:
                deleted += 1
                if self.index is not None:
                    self.index.remove_memory(memory_id)
            return deleted

        if query is not None:
            matches = self.retrieve_by_keywords(user_id, query=query, limit=50)
            for match in matches:
                ok = self.store.delete_memory(user_id, match.memory_id)
                if ok:
                    deleted += 1
                    if self.index is not None:
                        self.index.remove_memory(match.memory_id)

        return deleted

    def post_process_conversation(
        self,
        transcript: ConversationTranscript,
    ) -> PostProcessResult:
        """
        Process a completed conversation:
        - save transcript
        - create and store conversation summary
        - extract candidate memories
        - store and index candidates
        - update user profile
        """
        self.initialize_user(transcript.user_id)
        self.store.save_conversation(transcript)

        summary = self.model.summarize_conversation(transcript)

        summary_memory = MemoryRecord(
            memory_id="",
            user_id=transcript.user_id,
            kind="conversation_summary",
            content=summary,
            summary=summary[:400],
            created_at=transcript.ended_at or datetime.utcnow(),
            conversation_id=transcript.conversation_id,
            source="conversation_summary",
            importance=0.6,
            confidence=0.9,
            metadata={"conversation_id": transcript.conversation_id},
        )

        stored_ids: list[str] = []
        updated_task_ids: list[str] = []

        summary_id = self.store.save_memory(summary_memory)
        stored_ids.append(summary_id)

        if self.index is not None:
            saved_summary = self.store.get_memory(transcript.user_id, summary_id)
            if saved_summary is not None:
                self.index.index_memory(saved_summary)
            self.index.index_conversation_summary(
                user_id=transcript.user_id,
                conversation_id=transcript.conversation_id,
                summary=summary,
                metadata={"memory_id": summary_id},
            )

        candidate_memories = self.model.extract_candidate_memories(
            transcript=transcript,
            conversation_summary=summary,
        )

        normalized_candidates: list[MemoryRecord] = []

        for candidate in candidate_memories:
            normalized = self._normalize_candidate_memory(
                candidate=candidate,
                transcript=transcript,
            )

            memory_id = self.store.save_memory(normalized)
            stored_ids.append(memory_id)

            saved = self.store.get_memory(transcript.user_id, memory_id)
            if saved is not None:
                normalized_candidates.append(saved)
                if self.index is not None:
                    self.index.index_memory(saved)

                if saved.kind == "task":
                    task_id = self._materialize_task_from_memory(saved)
                    if task_id:
                        updated_task_ids.append(task_id)

        existing_profile = self.store.get_user_profile(transcript.user_id)
        updated_profile = self.model.merge_profile(
            existing_profile=existing_profile,
            candidate_memories=normalized_candidates,
        )
        updated_profile.user_id = transcript.user_id
        updated_profile.updated_at = datetime.utcnow()
        self.store.save_user_profile(updated_profile)

        return PostProcessResult(
            conversation_id=transcript.conversation_id,
            user_id=transcript.user_id,
            stored_memory_ids=stored_ids,
            updated_task_ids=updated_task_ids,
            updated_profile=True,
            candidate_memories=normalized_candidates,
            notes=[],
        )

    def consolidate_user_memory(self, user_id: str) -> list[str]:
        """
        Placeholder maintenance operation.

        Future uses:
        - merge duplicate facts/preferences
        - archive stale conversation summaries
        - decay importance of old episodic memories
        - resolve contradictions
        """
        self.initialize_user(user_id)
        return []

    def start_conversation(
        self,
        user_id: str,
        conversation_id: str,
        *,
        initial_query: str = "",
    ) -> ConversationMemory:
        """
        Convenience constructor for a ConversationMemory instance.
        """
        bundle = self.retrieve_for_conversation(
            user_id=user_id,
            query=initial_query,
        )
        return ConversationMemory(
            user_id=user_id,
            conversation_id=conversation_id,
            long_term_memory=self,
            initial_retrieved_bundle=bundle,
        )

    def _merge_tasks(
        self,
        first: Sequence[TaskRecord],
        second: Sequence[TaskRecord],
    ) -> list[TaskRecord]:
        merged: list[TaskRecord] = []
        seen: set[str] = set()

        for task in list(first) + list(second):
            if task.task_id in seen:
                continue
            merged.append(task)
            seen.add(task.task_id)

        return merged

    def _normalize_candidate_memory(
        self,
        *,
        candidate: MemoryRecord,
        transcript: ConversationTranscript,
    ) -> MemoryRecord:
        """
        Ensure extracted candidate memory is fully scoped and has sane defaults.
        """
        created_at = candidate.created_at or transcript.ended_at or datetime.utcnow()

        return MemoryRecord(
            memory_id=candidate.memory_id or "",
            user_id=transcript.user_id,
            kind=candidate.kind,
            content=candidate.content,
            summary=candidate.summary or candidate.content[:200],
            created_at=created_at,
            updated_at=candidate.updated_at,
            conversation_id=candidate.conversation_id or transcript.conversation_id,
            project_id=candidate.project_id,
            task_id=candidate.task_id,
            subject=candidate.subject,
            importance=candidate.importance,
            confidence=candidate.confidence,
            valid_from=candidate.valid_from,
            valid_until=candidate.valid_until,
            is_active=candidate.is_active,
            source=candidate.source or "conversation",
            tags=list(candidate.tags),
            metadata=dict(candidate.metadata),
        )

    def _materialize_task_from_memory(self, memory: MemoryRecord) -> Optional[str]:
        """
        Convert a task-like memory into a TaskRecord if appropriate.

        Current prototype behavior:
        - every memory of kind "task" becomes an open task unless an exact-title
          task already exists for the user.
        """
        if memory.kind != "task":
            return None

        existing_tasks = self.store.list_tasks(memory.user_id, limit=200)
        for task in existing_tasks:
            if task.title.strip().lower() == memory.content.strip().lower():
                return task.task_id

        task = TaskRecord(
            task_id="",
            user_id=memory.user_id,
            title=memory.content[:200],
            status="open",
            goal=memory.content,
            plan=[],
            current_step=None,
            blockers=[],
            artifacts=[],
            created_at=memory.created_at,
            updated_at=datetime.utcnow(),
            metadata={
                "source_memory_id": memory.memory_id,
                "source_conversation_id": memory.conversation_id,
            },
        )
        return self.store.save_task(task)

    def consolidate_user_memory_incremental(
            self,
            user_id: str,
            *,
            memory_batch_size: int = 30,
            task_batch_size: int = 10,
    ) -> list[str]:
        self.initialize_user(user_id)
        notes: list[str] = []

        profile = self.store.get_user_profile(user_id)

        all_memories = self.store.list_memories(
            user_id=user_id,
            kind=None,
            active_only=True,
            limit=500,
        )

        # Prefer likely-noisy or low-value candidates first
        def memory_priority(m: MemoryRecord) -> tuple[float, float, datetime]:
            return (
                m.confidence,
                m.importance,
                m.updated_at or m.created_at,
            )

        candidate_memories = sorted(all_memories, key=memory_priority)[:memory_batch_size]

        all_tasks = self.store.list_tasks(user_id=user_id, status=None, limit=200)
        now = datetime.utcnow()

        def task_priority(t: TaskRecord) -> tuple[int, int]:
            age_days = (now - t.updated_at).days
            stale_open = 0 if t.status in {"open", "blocked"} else 1
            return (stale_open, -age_days)

        candidate_tasks = sorted(all_tasks, key=task_priority)[:task_batch_size]

        if not candidate_memories and not candidate_tasks:
            return ["No memories or tasks available for consolidation."]

        result = self.model.consolidate_memories(
            user_id=user_id,
            profile=profile,
            memories=candidate_memories,
            tasks=candidate_tasks,
        )

        for action in result.actions:
            if action.action == "keep":
                continue

            elif action.action == "deactivate_memory" and action.memory_id:
                memory = self.store.get_memory(user_id, action.memory_id)
                if memory is not None:
                    memory.is_active = False
                    memory.updated_at = datetime.utcnow()
                    self.store.update_memory(memory)
                    if self.index is not None:
                        self.index.remove_memory(memory.memory_id)
                        notes.append(f"Deactivated memory {memory.memory_id}")

            elif action.action == "update_memory" and action.memory_id:
                memory = self.store.get_memory(user_id, action.memory_id)
                if memory is not None:
                    if action.content is not None:
                        memory.content = action.content
                    if action.summary is not None:
                        memory.summary = action.summary
                    if action.kind is not None:
                        memory.kind = action.kind
                    if action.tags:
                        memory.tags = list(action.tags)
                    if action.importance is not None:
                        memory.importance = max(0.0, min(1.0, float(action.importance)))
                    if action.confidence is not None:
                        memory.confidence = max(0.0, min(1.0, float(action.confidence)))
                    if action.is_active is not None:
                        memory.is_active = action.is_active
                        memory.updated_at = datetime.utcnow()
                        self.store.update_memory(memory)
                    if self.index is not None:
                        if memory.is_active:
                            self.index.index_memory(memory)
                        else:
                            self.index.remove_memory(memory.memory_id)
                            notes.append(f"Updated memory {memory.memory_id}")

            elif action.action == "merge_memories" and action.memory_ids:
                existing = [
                    self.store.get_memory(user_id, memory_id)
                    for memory_id in action.memory_ids
                ]
                existing = [m for m in existing if m is not None]

                if existing:
                    merged = MemoryRecord(
                        memory_id="",
                        user_id=user_id,
                        kind=action.kind or existing[0].kind,
                        content=action.content or existing[0].content,
                        summary=action.summary or (action.content[:200] if action.content else existing[0].summary),
                        created_at=min(m.created_at for m in existing),
                        updated_at=datetime.utcnow(),
                        conversation_id=existing[0].conversation_id,
                        project_id=existing[0].project_id,
                        task_id=existing[0].task_id,
                        subject=existing[0].subject,
                        importance=max(
                            [m.importance for m in existing] + ([float(action.importance)] if action.importance is not None else [])
                        ),
                        confidence=max(
                            [m.confidence for m in existing] + ([float(action.confidence)] if action.confidence is not None else [])
                        ),
                        is_active=True,
                        source="consolidation_merge",
                        tags=list(action.tags) if action.tags else sorted({tag for m in existing for tag in m.tags}),
                        metadata={"merged_from": [m.memory_id for m in existing]},
                    )
                    new_id = self.store.save_memory(merged)
                    if self.index is not None:
                        saved = self.store.get_memory(user_id, new_id)
                        if saved is not None:
                            self.index.index_memory(saved)

                    for memory in existing:
                        memory.is_active = False
                        memory.updated_at = datetime.utcnow()
                        self.store.update_memory(memory)
                        if self.index is not None:
                            self.index.remove_memory(memory.memory_id)

                    notes.append(
                        f"Merged memories {', '.join(m.memory_id for m in existing)} into {new_id}"
                    )

            elif action.action == "create_memory":
                if action.content:
                    new_memory = MemoryRecord(
                        memory_id="",
                        user_id=user_id,
                        kind=action.kind or "fact",
                        content=action.content,
                        summary=action.summary or action.content[:200],
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                        importance=max(0.0, min(1.0, float(action.importance))) if action.importance is not None else 0.6,
                        confidence=max(0.0, min(1.0, float(action.confidence))) if action.confidence is not None else 0.7,
                        is_active=action.is_active if action.is_active is not None else True,
                        source="consolidation_create",
                        tags=list(action.tags),
                        metadata={},
                    )
                    new_id = self.store.save_memory(new_memory)
                    if self.index is not None:
                        saved = self.store.get_memory(user_id, new_id)
                        if saved is not None and saved.is_active:
                            self.index.index_memory(saved)
                            notes.append(f"Created memory {new_id}")

            elif action.action == "update_task" and action.task_id:
                task = self.store.get_task(user_id, action.task_id)
                if task is not None:
                    if action.task_title is not None:
                        task.title = action.task_title
                    if action.task_status is not None:
                        task.status = action.task_status  # type: ignore[assignment]
                    if action.task_current_step is not None:
                        task.current_step = action.task_current_step
                        task.updated_at = datetime.utcnow()
                        self.store.update_task(task)
                        notes.append(f"Updated task {task.task_id} -> {task.status}")

        notes.extend(result.notes)
        return notes

    def _memory_relevance_score(self, memory: MemoryRecord, *, query_score: float) -> float:
        prior = self._memory_prior_score(memory)
        recency = self._memory_recency_score(memory)
        query_component = self._normalize_query_score(query_score)

        return (
            0.50 * prior +
            0.35 * query_component +
            0.10 * recency +
            0.05 * self._kind_bonus(memory.kind)
        )

    def _memory_prior_score(self, memory: MemoryRecord) -> float:
        return (
            0.55 * max(0.0, min(1.0, memory.importance)) +
            0.35 * max(0.0, min(1.0, memory.confidence)) +
            0.10 * self._kind_bonus(memory.kind)
        )

    def _memory_recency_score(self, memory: MemoryRecord) -> float:
        age_days = max((datetime.utcnow() - memory.created_at).days, 0)

        if memory.kind in {"fact", "preference", "project", "correction"}:
            # stable memories should not decay much
            return 0.8

        if memory.kind in {"task", "episode", "conversation_summary"}:
            return max(0.0, 1.0 - (age_days / 365.0))

        return max(0.0, 1.0 - (age_days / 730.0))

    def _normalize_query_score(self, score: float) -> float:
        if score <= 0:
            return 0.0
        # simple saturation so huge Whoosh scores don't dominate everything
        return score / (score + 5.0)

    def _kind_bonus(self, kind: MemoryKind) -> float:
        bonuses = {
            "fact": 0.20,
            "preference": 0.20,
            "project": 0.18,
            "correction": 0.22,
            "task": 0.10,
            "episode": 0.05,
            "conversation_summary": 0.03,
            "artifact": 0.05,
        }
        return bonuses.get(kind, 0.0)
