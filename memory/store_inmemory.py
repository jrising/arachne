from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from typing import Optional, Sequence

from .models import (
    ConversationTranscript,
    MemoryKind,
    MemoryRecord,
    TaskRecord,
    TaskStatus,
    UserProfile,
)


class InMemoryStore:
    """
    In-memory implementation of the MemoryStore protocol.

    Intended primarily for tests, but also useful for rapid prototyping.
    """

    def __init__(self) -> None:
        self.users: set[str] = set()
        self.memories: dict[str, dict[str, MemoryRecord]] = defaultdict(dict)
        self.conversations: dict[str, dict[str, ConversationTranscript]] = defaultdict(dict)
        self.profiles: dict[str, UserProfile] = {}
        self.tasks: dict[str, dict[str, TaskRecord]] = defaultdict(dict)

        self._memory_counter = 0
        self._task_counter = 0

    def create_user_if_missing(self, user_id: str) -> None:
        self.users.add(user_id)

    def _next_memory_id(self) -> str:
        self._memory_counter += 1
        return f"mem-{self._memory_counter}"

    def _next_task_id(self) -> str:
        self._task_counter += 1
        return f"task-{self._task_counter}"

    def save_memory(self, memory: MemoryRecord) -> str:
        memory = deepcopy(memory)
        self.create_user_if_missing(memory.user_id)

        if not memory.memory_id:
            memory.memory_id = self._next_memory_id()

        if memory.updated_at is None:
            memory.updated_at = memory.created_at

        self.memories[memory.user_id][memory.memory_id] = memory
        return memory.memory_id

    def update_memory(self, memory: MemoryRecord) -> None:
        self.create_user_if_missing(memory.user_id)
        memory = deepcopy(memory)
        memory.updated_at = datetime.utcnow()
        self.memories[memory.user_id][memory.memory_id] = memory

    def get_memory(self, user_id: str, memory_id: str) -> Optional[MemoryRecord]:
        memory = self.memories[user_id].get(memory_id)
        return deepcopy(memory) if memory is not None else None

    def list_memories(
        self,
        user_id: str,
        *,
        kind: Optional[MemoryKind] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        items = list(self.memories[user_id].values())

        if kind is not None:
            items = [m for m in items if m.kind == kind]
        if active_only:
            items = [m for m in items if m.is_active]

        items.sort(
            key=lambda m: (
                m.importance,
                m.updated_at or m.created_at,
                m.created_at,
            ),
            reverse=True,
        )
        return [deepcopy(x) for x in items[:limit]]

    def find_memories_by_filters(
        self,
        user_id: str,
        *,
        kind: Optional[MemoryKind] = None,
        conversation_id: Optional[str] = None,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        items = list(self.memories[user_id].values())

        if kind is not None:
            items = [m for m in items if m.kind == kind]
        if conversation_id is not None:
            items = [m for m in items if m.conversation_id == conversation_id]
        if project_id is not None:
            items = [m for m in items if m.project_id == project_id]
        if task_id is not None:
            items = [m for m in items if m.task_id == task_id]
        if tags:
            tagset = set(tags)
            items = [m for m in items if tagset.intersection(m.tags)]
        if active_only:
            items = [m for m in items if m.is_active]

        items.sort(
            key=lambda m: (
                m.importance,
                m.updated_at or m.created_at,
                m.created_at,
            ),
            reverse=True,
        )
        return [deepcopy(x) for x in items[:limit]]

    def save_conversation(self, transcript: ConversationTranscript) -> None:
        self.create_user_if_missing(transcript.user_id)
        self.conversations[transcript.user_id][transcript.conversation_id] = deepcopy(transcript)

    def get_conversation(
        self,
        user_id: str,
        conversation_id: str,
    ) -> Optional[ConversationTranscript]:
        convo = self.conversations[user_id].get(conversation_id)
        return deepcopy(convo) if convo is not None else None

    def save_user_profile(self, profile: UserProfile) -> None:
        self.create_user_if_missing(profile.user_id)
        profile = deepcopy(profile)
        profile.updated_at = profile.updated_at or datetime.utcnow()
        self.profiles[profile.user_id] = profile

    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        profile = self.profiles.get(user_id)
        return deepcopy(profile) if profile is not None else None

    def save_task(self, task: TaskRecord) -> str:
        self.create_user_if_missing(task.user_id)
        task = deepcopy(task)

        if not task.task_id:
            task.task_id = self._next_task_id()

        task.updated_at = task.updated_at or datetime.utcnow()
        self.tasks[task.user_id][task.task_id] = task
        return task.task_id

    def update_task(self, task: TaskRecord) -> None:
        self.create_user_if_missing(task.user_id)
        task = deepcopy(task)
        task.updated_at = datetime.utcnow()
        self.tasks[task.user_id][task.task_id] = task

    def get_task(self, user_id: str, task_id: str) -> Optional[TaskRecord]:
        task = self.tasks[user_id].get(task_id)
        return deepcopy(task) if task is not None else None

    def list_tasks(
        self,
        user_id: str,
        *,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        items = list(self.tasks[user_id].values())

        if status is not None:
            items = [t for t in items if t.status == status]

        items.sort(key=lambda t: t.updated_at, reverse=True)
        return [deepcopy(x) for x in items[:limit]]

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        if memory_id in self.memories[user_id]:
            del self.memories[user_id][memory_id]
            return True
        return False
