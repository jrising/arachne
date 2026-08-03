from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from .models import (
    ConversationState,
    ConversationTranscript,
    MemoryRecord,
    Message,
    TaskRecord,
    UserProfile,
    ConsolidationAction,
    ConsolidationResult
)
from .protocols import MemoryModel


class MockMemoryModel(MemoryModel):
    """
    Deterministic stand-in for a real LLM-backed memory model.

    Intended for:
    - unit tests
    - local development
    - validating orchestration logic without API calls

    Conventions:
    - user lines starting with 'remember:' become fact memories
    - user lines starting with 'preference:' become preference memories
    - user lines starting with 'task:' become task memories
    - every conversation with at least one user message emits one episode memory
    """

    def summarize_conversation(
        self,
        transcript: ConversationTranscript,
        existing_summary: Optional[str] = None,
    ) -> str:
        user_messages = [m.content for m in transcript.messages if m.role == "user"]
        assistant_messages = [m.content for m in transcript.messages if m.role == "assistant"]

        if not transcript.messages:
            return existing_summary or ""

        last_user = user_messages[-1] if user_messages else ""
        last_assistant = assistant_messages[-1] if assistant_messages else ""

        pieces: list[str] = []
        if existing_summary:
            pieces.append(f"Existing summary: {existing_summary}")
        if last_user:
            pieces.append(f"Last user message: {last_user[:200]}")
        if last_assistant:
            pieces.append(f"Last assistant message: {last_assistant[:200]}")

        return " | ".join(pieces)

    def summarize_turn_delta(
        self,
        transcript: ConversationTranscript,
        previous_state: ConversationState,
    ) -> ConversationState:
        state = ConversationState(
            conversation_id=previous_state.conversation_id,
            user_id=previous_state.user_id,
            running_summary=previous_state.running_summary,
            open_questions=list(previous_state.open_questions),
            current_goals=list(previous_state.current_goals),
            constraints=list(previous_state.constraints),
            important_points=list(previous_state.important_points),
            last_updated=datetime.utcnow(),
        )

        if transcript.messages:
            last_message = transcript.messages[-1]
            if last_message.role == "user":
                content = last_message.content.strip()
                if content:
                    state.important_points.append(content[:200])
                    state.running_summary = (
                        (state.running_summary + " | ") if state.running_summary else ""
                    ) + f"User said: {content[:200]}"

                    lowered = content.lower()
                    if "goal:" in lowered:
                        state.current_goals.append(content)
                    if "constraint:" in lowered:
                        state.constraints.append(content)
                    if "?" in content:
                        state.open_questions.append(content)

        state.important_points = state.important_points[-10:]
        state.current_goals = state.current_goals[-5:]
        state.constraints = state.constraints[-5:]
        state.open_questions = state.open_questions[-5:]
        if len(state.running_summary) > 2000:
            state.running_summary = state.running_summary[-2000:]

        return state

    def build_retrieval_query(
        self,
        recent_messages: Sequence[Message],
        conversation_state: ConversationState,
    ) -> str:
        parts: list[str] = []

        for message in recent_messages[-3:]:
            if message.role == "user":
                parts.append(message.content)

        parts.extend(conversation_state.current_goals[-2:])
        parts.extend(conversation_state.constraints[-2:])

        return " ".join(parts).strip()[:500]

    def extract_candidate_memories(
        self,
        transcript: ConversationTranscript,
        conversation_summary: str,
    ) -> list[MemoryRecord]:
        now = transcript.ended_at or datetime.utcnow()
        candidates: list[MemoryRecord] = []

        for message in transcript.messages:
            if message.role != "user":
                continue

            for raw_line in message.content.splitlines():
                line = raw_line.strip()
                lowered = line.lower()

                if lowered.startswith("remember:"):
                    content = line.split(":", 1)[1].strip()
                    if content:
                        candidates.append(
                            MemoryRecord(
                                memory_id="",
                                user_id=transcript.user_id,
                                kind="fact",
                                content=content,
                                summary=content[:200],
                                created_at=now,
                                conversation_id=transcript.conversation_id,
                                source="mock_extractor",
                                importance=0.8,
                                confidence=0.95,
                                tags=["remember"],
                            )
                        )

                elif lowered.startswith("preference:"):
                    content = line.split(":", 1)[1].strip()
                    if content:
                        candidates.append(
                            MemoryRecord(
                                memory_id="",
                                user_id=transcript.user_id,
                                kind="preference",
                                content=content,
                                summary=content[:200],
                                created_at=now,
                                conversation_id=transcript.conversation_id,
                                source="mock_extractor",
                                importance=0.7,
                                confidence=0.9,
                                tags=["preference"],
                            )
                        )

                elif lowered.startswith("task:"):
                    content = line.split(":", 1)[1].strip()
                    if content:
                        candidates.append(
                            MemoryRecord(
                                memory_id="",
                                user_id=transcript.user_id,
                                kind="task",
                                content=content,
                                summary=content[:200],
                                created_at=now,
                                conversation_id=transcript.conversation_id,
                                source="mock_extractor",
                                importance=0.75,
                                confidence=0.85,
                                tags=["task"],
                            )
                        )

        user_messages = [m.content for m in transcript.messages if m.role == "user"]
        if user_messages:
            candidates.append(
                MemoryRecord(
                    memory_id="",
                    user_id=transcript.user_id,
                    kind="episode",
                    content=conversation_summary,
                    summary=conversation_summary[:200],
                    created_at=now,
                    conversation_id=transcript.conversation_id,
                    source="mock_extractor",
                    importance=0.4,
                    confidence=0.8,
                    tags=["episode"],
                )
            )

        return candidates

    def merge_profile(
        self,
        existing_profile: Optional[UserProfile],
        candidate_memories: Sequence[MemoryRecord],
    ) -> UserProfile:
        if existing_profile is None:
            user_id = candidate_memories[0].user_id if candidate_memories else "unknown"
            profile = UserProfile(user_id=user_id)
        else:
            profile = UserProfile(
                user_id=existing_profile.user_id,
                display_name=existing_profile.display_name,
                preferences=list(existing_profile.preferences),
                facts=list(existing_profile.facts),
                active_projects=list(existing_profile.active_projects),
                active_tasks=list(existing_profile.active_tasks),
                updated_at=datetime.utcnow(),
            )

        pref_set = set(profile.preferences)
        fact_set = set(profile.facts)
        task_set = set(profile.active_tasks)

        for memory in candidate_memories:
            if memory.kind == "preference":
                pref_set.add(memory.content)
            elif memory.kind == "fact":
                fact_set.add(memory.content)
            elif memory.kind == "task":
                task_set.add(memory.content)

        profile.preferences = sorted(pref_set)
        profile.facts = sorted(fact_set)
        profile.active_tasks = sorted(task_set)
        profile.updated_at = datetime.utcnow()

        return profile

    def build_prompt_memory_block(
        self,
        profile: Optional[UserProfile],
        memories: Sequence[MemoryRecord],
        tasks: Sequence[TaskRecord],
        conversation_state: ConversationState,
    ) -> str:
        lines: list[str] = ["Relevant memory:"]

        if profile is not None:
            if profile.facts:
                lines.append("Facts:")
                for fact in profile.facts[:5]:
                    lines.append(f"- {fact}")
            if profile.preferences:
                lines.append("Preferences:")
                for pref in profile.preferences[:5]:
                    lines.append(f"- {pref}")

        if tasks:
            lines.append("Active tasks:")
            for task in tasks[:5]:
                lines.append(f"- [{task.status}] {task.title}")

        if conversation_state.current_goals:
            lines.append("Current goals:")
            for goal in conversation_state.current_goals[-3:]:
                lines.append(f"- {goal}")

        if conversation_state.constraints:
            lines.append("Constraints:")
            for constraint in conversation_state.constraints[-3:]:
                lines.append(f"- {constraint}")

        if memories:
            lines.append("Relevant prior memories:")
            for memory in memories[:5]:
                snippet = memory.summary or memory.content[:160]
                lines.append(f"- ({memory.kind}) {snippet}")

        return "\n".join(lines)
    
    def consolidate_memories(
        self,
        *,
        user_id: str,
        profile: Optional[UserProfile],
        memories: Sequence[MemoryRecord],
        tasks: Sequence[TaskRecord],
    ) -> ConsolidationResult:
        actions: list[ConsolidationAction] = []

        for memory in memories:
            text = memory.content.strip()
            if len(text) < 8:
                actions.append(
                    ConsolidationAction(
                        action="deactivate_memory",
                        memory_id=memory.memory_id,
                        notes="Very short memory content",
                    )
                )
            else:
                actions.append(
                    ConsolidationAction(
                        action="keep",
                        memory_id=memory.memory_id,
                    )
                )

        now = datetime.utcnow()
        for task in tasks:
            age_days = (now - task.updated_at).days
            if task.status == "open" and age_days > 90:
                actions.append(
                    ConsolidationAction(
                        action="update_task",
                        task_id=task.task_id,
                        task_status="archived",
                        notes="Stale open task archived by mock consolidator",
                    )
                )

        return ConsolidationResult(
            user_id=user_id,
            processed_memory_ids=[m.memory_id for m in memories],
            processed_task_ids=[t.task_id for t in tasks],
            actions=actions,
            notes=[],
        )
