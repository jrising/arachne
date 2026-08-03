from __future__ import annotations

from typing import Any, Optional, Protocol, Sequence

from .models import (
    ConversationState,
    ConversationTranscript,
    MemoryKind,
    MemoryRecord,
    Message,
    PostProcessResult,
    RetrievedMemoryBundle,
    TaskRecord,
    TaskStatus,
    UserProfile,
)

class MemoryStore(Protocol):
    """
    Canonical persistent store interface.

    Implementations:
    - InMemoryStore
    - SQLAlchemyMemoryStore
    """

    def create_user_if_missing(self, user_id: str) -> None:
        ...

    def save_memory(self, memory: MemoryRecord) -> str:
        ...

    def update_memory(self, memory: MemoryRecord) -> None:
        ...

    def get_memory(self, user_id: str, memory_id: str) -> Optional[MemoryRecord]:
        ...

    def list_memories(
        self,
        user_id: str,
        *,
        kind: Optional[MemoryKind] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        ...

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
        ...

    def save_conversation(self, transcript: ConversationTranscript) -> None:
        ...

    def get_conversation(
        self,
        user_id: str,
        conversation_id: str,
    ) -> Optional[ConversationTranscript]:
        ...

    def save_user_profile(self, profile: UserProfile) -> None:
        ...

    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        ...

    def save_task(self, task: TaskRecord) -> str:
        ...

    def update_task(self, task: TaskRecord) -> None:
        ...

    def get_task(self, user_id: str, task_id: str) -> Optional[TaskRecord]:
        ...

    def list_tasks(
        self,
        user_id: str,
        *,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        ...

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        ...


class MemoryIndex(Protocol):
    """
    Search/index interface for durable memory retrieval.

    Implementations:
    - NullMemoryIndex
    - SimpleTextMemoryIndex
    - WhooshMemoryIndex
    - future embedding/vector index
    """

    def index_memory(self, memory: MemoryRecord) -> None:
        ...

    def remove_memory(self, memory_id: str) -> None:
        ...

    def search(
        self,
        user_id: str,
        query: str,
        *,
        kinds: Optional[Sequence[MemoryKind]] = None,
        limit: int = 10,
    ) -> list[str]:
        """
        Return ranked memory_ids.
        """
        ...

    def index_conversation_summary(
        self,
        user_id: str,
        conversation_id: str,
        summary: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        ...

    def search_with_scores(
        self,
        user_id: str,
        query: str,
        *,
        kinds: Optional[Sequence[MemoryKind]] = None,
        limit: int = 10,
    ) -> list[tuple[str, float]]:
        ...
    
class MemoryModel(Protocol):
    """
    LLM-backed or deterministic model layer used by memory orchestration.

    Implementations:
    - MockMemoryModel
    - OpenAIMemoryModel
    """

    def summarize_conversation(
        self,
        transcript: ConversationTranscript,
        existing_summary: Optional[str] = None,
    ) -> str:
        ...

    def summarize_turn_delta(
        self,
        transcript: ConversationTranscript,
        previous_state: ConversationState,
    ) -> ConversationState:
        ...

    def build_retrieval_query(
        self,
        recent_messages: Sequence[Message],
        conversation_state: ConversationState,
    ) -> str:
        ...

    def extract_candidate_memories(
        self,
        transcript: ConversationTranscript,
        conversation_summary: str,
    ) -> list[MemoryRecord]:
        ...

    def merge_profile(
        self,
        existing_profile: Optional[UserProfile],
        candidate_memories: Sequence[MemoryRecord],
    ) -> UserProfile:
        ...

    def build_prompt_memory_block(
        self,
        profile: Optional[UserProfile],
        memories: Sequence[MemoryRecord],
        tasks: Sequence[TaskRecord],
        conversation_state: ConversationState,
    ) -> str:
        ...

    def consolidate_memories(
        self,
        *,
        user_id: str,
        profile: Optional[UserProfile],
        memories: Sequence[MemoryRecord],
        tasks: Sequence[TaskRecord],
    ) -> ConsolidationResult:
        ...
    
class LongTermMemoryProtocol(Protocol):
    """
    Optional protocol for the persistent orchestrator, mainly useful
    for type-checking ConversationMemory against a narrower interface.
    """

    store: MemoryStore
    model: MemoryModel
    index: Optional[MemoryIndex]

    def initialize_user(self, user_id: str) -> None:
        ...

    def retrieve_for_conversation(
        self,
        user_id: str,
        *,
        query: str,
        limit: int = 8,
        kinds: Optional[Sequence[MemoryKind]] = None,
    ) -> RetrievedMemoryBundle:
        ...

    def retrieve_by_keywords(
        self,
        user_id: str,
        *,
        query: str,
        limit: int = 10,
        kinds: Optional[Sequence[MemoryKind]] = None,
    ) -> list[MemoryRecord]:
        ...

    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        ...

    def list_user_memories(
        self,
        user_id: str,
        *,
        kind: Optional[MemoryKind] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        ...

    def remember(self, memory: MemoryRecord) -> str:
        ...

    def forget(
        self,
        user_id: str,
        *,
        memory_id: Optional[str] = None,
        query: Optional[str] = None,
    ) -> int:
        ...

    def post_process_conversation(
        self,
        transcript: ConversationTranscript,
    ) -> PostProcessResult:
        ...


class ConversationMemoryProtocol(Protocol):
    """
    Optional protocol for the within-conversation object.
    """

    user_id: str
    conversation_id: str
    transcript: ConversationTranscript
    state: ConversationState

    def add_message(
        self,
        role: str,
        content: str,
        *,
        created_at: Optional[Any] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        ...

    def update_with_turn(
        self,
        *,
        assistant_response: Optional[str],
        user_response: str,
    ) -> str:
        ...

    def get_prompt_block(self) -> str:
        ...

    def summarize(self) -> str:
        ...

    def get_state(self) -> ConversationState:
        ...

    def get_transcript(self) -> ConversationTranscript:
        ...

    def mark_complete(self, *, ended_at: Optional[Any] = None) -> None:
        ...

    def finalize(self) -> PostProcessResult:
        ...
