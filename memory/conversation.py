from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

from .models import (
    ConversationState,
    ConversationTranscript,
    Message,
    PostProcessResult,
    RetrievedMemoryBundle,
    Role,
)

if TYPE_CHECKING:
    from .long_term import LongTermMemory


class ConversationMemory:
    """
    Per-conversation working memory.

    Responsibilities:
    - maintain the live transcript
    - maintain/update conversation-local state
    - retrieve relevant long-term memory as the conversation evolves
    - produce a prompt-ready memory block for the next model call
    - finalize the conversation into durable memory
    """

    def __init__(
        self,
        user_id: str,
        conversation_id: str,
        long_term_memory: LongTermMemory,
        initial_retrieved_bundle: Optional[RetrievedMemoryBundle] = None,
    ) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.long_term_memory = long_term_memory

        now = datetime.utcnow()
        self.transcript = ConversationTranscript(
            conversation_id=conversation_id,
            user_id=user_id,
            started_at=now,
            ended_at=None,
            messages=[],
            metadata={},
        )

        self.state = ConversationState(
            conversation_id=conversation_id,
            user_id=user_id,
            running_summary="",
            open_questions=[],
            current_goals=[],
            constraints=[],
            important_points=[],
            last_updated=now,
        )

        self.initial_retrieved_bundle = initial_retrieved_bundle
        self._latest_retrieved_bundle = initial_retrieved_bundle
        self._latest_memory_block: str = (
            initial_retrieved_bundle.generated_summary_block
            if initial_retrieved_bundle is not None
            else ""
        )

    def add_message(
        self,
        role: Role,
        content: str,
        *,
        created_at: Optional[datetime] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Append a single message to the live transcript.
        """
        self.transcript.add_message(
            Message(
                role=role,
                content=content,
                created_at=created_at or datetime.utcnow(),
                metadata=metadata or {},
            )
        )

    def update_with_turn(
        self,
        *,
        assistant_response: Optional[str],
        user_response: str,
    ) -> str:
        """
        Update conversation memory with the latest assistant/user turn pair.

        Typical usage pattern:
        - model produced assistant_response
        - user replied with user_response
        - call this method
        - receive a prompt-ready memory block for the next model call
        """
        if assistant_response:
            self.add_message("assistant", assistant_response)

        self.add_message("user", user_response)

        self.state = self.long_term_memory.model.summarize_turn_delta(
            transcript=self.transcript,
            previous_state=self.state,
        )

        retrieval_query = self.long_term_memory.model.build_retrieval_query(
            recent_messages=self.transcript.messages[-6:],
            conversation_state=self.state,
        )

        bundle = self.long_term_memory.retrieve_for_conversation(
            user_id=self.user_id,
            query=retrieval_query,
            limit=8,
        )

        self._latest_retrieved_bundle = bundle
        self._latest_memory_block = self.long_term_memory.model.build_prompt_memory_block(
            profile=bundle.profile,
            memories=bundle.relevant_memories,
            tasks=bundle.active_tasks,
            conversation_state=self.state,
        )

        self.state.last_updated = datetime.utcnow()
        return self._latest_memory_block

    def refresh_prompt_block(self, *, query: Optional[str] = None, limit: int = 8) -> str:
        """
        Recompute the prompt-ready memory block without adding new messages.

        Useful if:
        - you added messages manually via add_message()
        - tool outputs changed the conversation state
        - you want a refresh before the next model call
        """

        retrieval_query = query
        if retrieval_query is None:
            retrieval_query = self.long_term_memory.model.build_retrieval_query(
                recent_messages=self.transcript.messages[-6:],
                conversation_state=self.state,
            )

        bundle = self.long_term_memory.retrieve_for_conversation(
            user_id=self.user_id,
            query=retrieval_query,
            limit=limit,
        )

        self._latest_retrieved_bundle = bundle
        self._latest_memory_block = self.long_term_memory.model.build_prompt_memory_block(
            profile=bundle.profile,
            memories=bundle.relevant_memories,
            tasks=bundle.active_tasks,
            conversation_state=self.state,
        )

        self.state.last_updated = datetime.utcnow()
        return self._latest_memory_block

    def set_state(
        self,
        *,
        running_summary: Optional[str] = None,
        open_questions: Optional[list[str]] = None,
        current_goals: Optional[list[str]] = None,
        constraints: Optional[list[str]] = None,
        important_points: Optional[list[str]] = None,
    ) -> None:
        """
        Optional manual override/update for conversation state.

        Useful if external code performs tool orchestration and wants to
        inject structured state.
        """
        if running_summary is not None:
            self.state.running_summary = running_summary
        if open_questions is not None:
            self.state.open_questions = list(open_questions)
        if current_goals is not None:
            self.state.current_goals = list(current_goals)
        if constraints is not None:
            self.state.constraints = list(constraints)
        if important_points is not None:
            self.state.important_points = list(important_points)

        self.state.last_updated = datetime.utcnow()

    def get_prompt_block(self) -> str:
        """
        Return the most recent prompt-ready memory block.
        """
        return self._latest_memory_block

    def get_latest_retrieved_bundle(self) -> Optional[RetrievedMemoryBundle]:
        """
        Return the most recent retrieval bundle used to build the prompt block.
        """
        return self._latest_retrieved_bundle

    def summarize(self) -> str:
        """
        Return an effective summary of the conversation so far.
        """
        return self.long_term_memory.model.summarize_conversation(
            transcript=self.transcript,
            existing_summary=self.state.running_summary or None,
        )

    def get_state(self) -> ConversationState:
        return self.state

    def get_transcript(self) -> ConversationTranscript:
        return self.transcript

    def set_metadata(self, **metadata: Any) -> None:
        """
        Attach metadata to the conversation transcript.
        """
        self.transcript.metadata.update(metadata)

    def mark_complete(self, *, ended_at: Optional[datetime] = None) -> None:
        """
        Mark the conversation as ended.
        """
        self.transcript.ended_at = ended_at or datetime.utcnow()

    def finalize(self) -> PostProcessResult:
        """
        Mark the conversation complete and hand it off to long-term memory.
        """
        if self.transcript.ended_at is None:
            self.mark_complete()
        return self.long_term_memory.post_process_conversation(self.transcript)
