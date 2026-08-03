from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Protocol, Sequence

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

@dataclass
class OpenAIMemoryModelConfig:
    summary_max_chars: int = 4000
    retrieval_query_max_chars: int = 500
    prompt_memory_limit: int = 8
    
class OpenAIMemoryModel(MemoryModel):
    """
    Real memory model implementation using a text-generation backend.

    Strategy:
    - use LLM for conversation summary
    - use LLM for extracting candidate memories
    - use heuristic logic for turn-state updates
    - use heuristic logic for retrieval query generation
    - use deterministic prompt block construction
    """

    def __init__(
        self,
        backend,
        *,
        config: Optional[OpenAIMemoryModelConfig] = None
    ) -> None:
        self.backend = backend
        self.config = config or OpenAIMemoryModelConfig()

    def summarize_conversation(
        self,
        transcript: ConversationTranscript,
        existing_summary: Optional[str] = None,
    ) -> str:
        convo_text = self._transcript_to_text(transcript, max_chars=12000)

        prompt = f"""
You are extracting a compact, useful memory summary of a conversation.

Write a concise summary that preserves:
- the user's goals
- stable preferences or facts stated
- important constraints
- decisions made
- open questions
- next steps if any

Do not include fluff or greetings.
Prefer plain factual bullet points or short paragraphs.

Existing summary:
{existing_summary or "(none)"}

Conversation:
{convo_text}

Return only the summary text.
""".strip()

        response = self.backend.single_prompt(prompt).strip()
        return response[: self.config.summary_max_chars]
    
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

        if not transcript.messages:
            return state

        last_message = transcript.messages[-1]
        if last_message.role != "user":
            return state

        content = last_message.content.strip()
        if not content:
            return state

        state.important_points.append(content[:300])

        if state.running_summary:
            state.running_summary += " | "
        state.running_summary += f"User: {content[:300]}"

        lowered = content.lower()
        if "goal:" in lowered or "i want" in lowered or "i need" in lowered:
            state.current_goals.append(content[:300])
        if "constraint:" in lowered or "must" in lowered or "should not" in lowered:
            state.constraints.append(content[:300])
        if "?" in content:
            state.open_questions.append(content[:300])

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

        for message in recent_messages[-4:]:
            if message.role == "user":
                parts.append(message.content.strip())

        parts.extend(conversation_state.current_goals[-2:])
        parts.extend(conversation_state.constraints[-2:])

        query = " ".join(p for p in parts if p).strip()
        return query[: self.config.retrieval_query_max_chars]

    def extract_candidate_memories(
        self,
        transcript: ConversationTranscript,
        conversation_summary: str,
    ) -> list[MemoryRecord]:
        convo_text = self._transcript_to_text(transcript, max_chars=12000)

        prompt = f"""
You are a memory extraction system.

From the conversation below, extract only durable, useful long-term memories.

Include only items that belong in one of these categories:
- fact: stable fact about the user
- preference: stable user preference
- task: explicit ongoing task or commitment
- project: longer-running project
- episode: important summary of this conversation, if worth remembering
- correction: an important correction where the assistant was wrong and the user or tool clarified the right answer

Do NOT extract:
- transient chit-chat
- assistant claims about itself
- low-confidence guesses
- redundant restatements

Return JSON ONLY as a list of objects with keys:
- kind
- content
- summary
- importance
- confidence
- tags

Rules:
- kind must be one of: fact, preference, task, project, episode, correction
- importance must be a float from 0 to 1
- confidence must be a float from 0 to 1
- tags must be a list of short strings

Conversation summary:
{conversation_summary}

Conversation:
{convo_text}
""".strip()

        response = self.backend.single_prompt(prompt)
        items = self._parse_json_list(response)

        now = transcript.ended_at or datetime.utcnow()
        memories: list[MemoryRecord] = []

        for item in items:
            kind = str(item.get("kind", "")).strip()
            if kind not in {"fact", "preference", "task", "project", "episode", "correction"}:
                continue

            content = str(item.get("content", "")).strip()
            if not content:
                continue

            summary = str(item.get("summary", "")).strip() or content[:200]

            importance = self._coerce_float(item.get("importance"), default=0.5)
            confidence = self._coerce_float(item.get("confidence"), default=0.7)
            tags = self._coerce_str_list(item.get("tags"))

            memories.append(
                MemoryRecord(
                    memory_id="",
                    user_id=transcript.user_id,
                    kind=kind,  # type: ignore[arg-type]
                    content=content,
                    summary=summary[:200],
                    created_at=now,
                    conversation_id=transcript.conversation_id,
                    source="openai_extractor",
                    importance=importance,
                    confidence=confidence,
                    tags=tags,
                )
            )

        return memories

    def merge_profile(
        self,
        existing_profile: Optional[UserProfile],
        candidate_memories: Sequence[MemoryRecord],
    ) -> UserProfile:
        existing = existing_profile or UserProfile(user_id=candidate_memories[0].user_id if candidate_memories else "unknown")

        payload = {
            "existing_profile": {
                "user_id": existing.user_id,
                "display_name": existing.display_name,
                "preferences": existing.preferences,
                "facts": existing.facts,
                "active_projects": existing.active_projects,
                "active_tasks": existing.active_tasks,
            },
            "candidate_memories": [
                {
                    "kind": m.kind,
                    "content": m.content,
                    "summary": m.summary,
                    "importance": m.importance,
                    "confidence": m.confidence,
                    "tags": m.tags,
                }
                for m in candidate_memories
            ],
        }

        prompt = f"""
You are updating a compact user profile from candidate long-term memories.

Return JSON ONLY with keys:
- display_name
- preferences
- facts
- active_projects
- active_tasks

Rules:
- keep only stable useful items
- deduplicate
- do not invent facts not supported by the candidate memories or existing profile
- each list should contain short strings

Input JSON:
{json.dumps(payload, ensure_ascii=False, indent=2)}
""".strip()

        response = self.backend.single_prompt(prompt)
        obj = self._parse_json_object(response)

        return UserProfile(
            user_id=existing.user_id,
            display_name=self._coerce_optional_str(obj.get("display_name")) if obj else existing.display_name,
            preferences=self._coerce_str_list(obj.get("preferences")) if obj else list(existing.preferences),
            facts=self._coerce_str_list(obj.get("facts")) if obj else list(existing.facts),
            active_projects=self._coerce_str_list(obj.get("active_projects")) if obj else list(existing.active_projects),
            active_tasks=self._coerce_str_list(obj.get("active_tasks")) if obj else list(existing.active_tasks),
            updated_at=datetime.utcnow(),
        )

    def build_prompt_memory_block(
        self,
        profile: Optional[UserProfile],
        memories: Sequence[MemoryRecord],
        tasks: Sequence[TaskRecord],
        conversation_state: ConversationState,
    ) -> str:
        lines: list[str] = []

        if profile or memories or tasks or conversation_state.running_summary:
            lines.append("Relevant memory for this conversation:")

        if profile is not None:
            if profile.facts:
                lines.append("Known facts about the user:")
                for fact in profile.facts[:8]:
                    lines.append(f"- {fact}")

            if profile.preferences:
                lines.append("User preferences:")
                for pref in profile.preferences[:8]:
                    lines.append(f"- {pref}")

            if profile.active_projects:
                lines.append("Active projects:")
                for project in profile.active_projects[:8]:
                    lines.append(f"- {project}")

        if tasks:
            lines.append("Active tasks:")
            for task in tasks[:8]:
                task_line = f"- [{task.status}] {task.title}"
                if task.current_step:
                    task_line += f" | next step: {task.current_step}"
                lines.append(task_line)

        if conversation_state.current_goals:
            lines.append("Current conversation goals:")
            for goal in conversation_state.current_goals[-5:]:
                lines.append(f"- {goal}")

        if conversation_state.constraints:
            lines.append("Current constraints:")
            for constraint in conversation_state.constraints[-5:]:
                lines.append(f"- {constraint}")

        if conversation_state.open_questions:
            lines.append("Open questions in this conversation:")
            for question in conversation_state.open_questions[-5:]:
                lines.append(f"- {question}")

        if memories:
            corrections = [m for m in memories if m.kind == "correction"]
            others = [m for m in memories if m.kind != "correction"]

            if corrections:
                lines.append("Important prior corrections:")
                for memory in corrections[:5]:
                    snippet = memory.summary or memory.content[:200]
                    lines.append(f"- {snippet}")

            if others:
                lines.append("Relevant prior memories:")
                for memory in others[:8]:
                    snippet = memory.summary or memory.content[:200]
                    lines.append(f"- ({memory.kind}) {snippet}")

        if not lines:
            return ""

        return "\n".join(lines)

    def _transcript_to_text(
        self,
        transcript: ConversationTranscript,
        *,
        max_chars: int = 12000,
    ) -> str:
        lines: list[str] = []

        for message in transcript.messages:
            role = message.role.upper()
            content = message.content.strip()
            if not content:
                continue
            lines.append(f"{role}: {content}")

        text = "\n".join(lines)
        return text[:max_chars]

    def _parse_json_list(self, text: str) -> list[dict[str, Any]]:
        obj = self._parse_json_any(text)
        if isinstance(obj, list):
            return [item for item in obj if isinstance(item, dict)]
        return []

    def _parse_json_object(self, text: str) -> dict[str, Any]:
        obj = self._parse_json_any(text)
        if isinstance(obj, dict):
            return obj
        return {}

    def _parse_json_any(self, text: str) -> Any:
        text = text.strip()

        # Try direct parse first
        try:
            return json.loads(text)
        except Exception:
            pass

        # Try extracting fenced code block
        if "```" in text:
            chunks = text.split("```")
            for chunk in chunks:
                chunk = chunk.strip()
                if chunk.startswith("json"):
                    chunk = chunk[4:].strip()
                try:
                    return json.loads(chunk)
                except Exception:
                    continue

        # Try first bracketed JSON region
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                candidate = text[start : end + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    continue

        return []

    def _coerce_float(self, value: Any, *, default: float) -> float:
        try:
            x = float(value)
        except Exception:
            return default
        return max(0.0, min(1.0, x))

    def _coerce_str_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _coerce_optional_str(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    def consolidate_memories(
        self,
        *,
        user_id: str,
        profile: Optional[UserProfile],
        memories: Sequence[MemoryRecord],
        tasks: Sequence[TaskRecord],
    ) -> ConsolidationResult:
        payload = {
            "user_id": user_id,
            "profile": {
                "display_name": profile.display_name if profile else None,
                "preferences": profile.preferences if profile else [],
                "facts": profile.facts if profile else [],
                "active_projects": profile.active_projects if profile else [],
                "active_tasks": profile.active_tasks if profile else [],
            },
            "memories": [
                {
                    "memory_id": m.memory_id,
                    "kind": m.kind,
                    "content": m.content,
                    "summary": m.summary,
                    "importance": m.importance,
                    "confidence": m.confidence,
                    "created_at": m.created_at.isoformat(),
                    "updated_at": m.updated_at.isoformat() if m.updated_at else None,
                    "tags": m.tags,
                    "is_active": m.is_active,
                }
                for m in memories
            ],
            "tasks": [
                {
                    "task_id": t.task_id,
                    "title": t.title,
                    "status": t.status,
                    "goal": t.goal,
                    "current_step": t.current_step,
                    "updated_at": t.updated_at.isoformat(),
                }
                for t in tasks
            ],
        }

        prompt = f"""
    You are cleaning and consolidating a long-term memory store for an AI assistant.

    Your job:
    - remove junk or incoherent memories
    - merge duplicate or overlapping memories
    - rewrite cut-off or poorly phrased memories only when the intended meaning is clear from the item itself
    - preserve stable useful facts, preferences, projects, and corrections
    - archive stale tasks that are old and likely no longer active
    - do not invent new facts

    Return JSON ONLY with this structure:
    {{
      "actions": [
        {{
          "action": "keep" | "update_memory" | "deactivate_memory" | "merge_memories" | "update_task" | "create_memory",
          "memory_id": "...",
          "memory_ids": ["...", "..."],
          "content": "...",
          "summary": "...",
          "kind": "fact|preference|task|project|episode|conversation_summary|artifact|correction",
          "tags": ["..."],
          "importance": 0.0,
          "confidence": 0.0,
          "is_active": true,
          "task_id": "...",
          "task_status": "open|in_progress|blocked|done|cancelled|archived",
          "task_title": "...",
          "task_current_step": "...",
          "notes": "..."
        }}
      ],
      "notes": ["..."]
    }}

    Guidelines:
    - Use "deactivate_memory" for low-value trash, incoherent fragments, or obsolete junk.
    - Use "merge_memories" when multiple memories say nearly the same thing.
    - Use "update_memory" when a memory can be repaired or refined without changing its meaning.
    - Use "create_memory" sparingly, only when combining several entries into a clearly better consolidated memory.
    - Use "update_task" to archive or adjust stale tasks.
    - Prefer preserving high-importance, high-confidence stable memories.

    Input JSON:
    {json.dumps(payload, ensure_ascii=False, indent=2)}
    """.strip()

        response = self.backend.single_prompt(prompt)
        obj = self._parse_json_object(response)

        actions: list[ConsolidationAction] = []
        raw_actions = obj.get("actions", []) if isinstance(obj, dict) else []

        for item in raw_actions:
            action_kind = item.get("action")
            if not action_kind:
                continue

            action = ConsolidationAction(action=action_kind)

            # Set optional fields if they exist in the item
            if "memory_id" in item:
                action.memory_id = item["memory_id"]
            if "memory_ids" in item:
                action.memory_ids = item["memory_ids"]
            if "content" in item:
                action.content = item["content"]
            if "summary" in item:
                action.summary = item["summary"]
            if "kind" in item:
                action.kind = item["kind"]
            if "tags" in item:
                action.tags = item["tags"]
            if "importance" in item:
                action.importance = item["importance"]
            if "confidence" in item:
                action.confidence = item["confidence"]
            if "is_active" in item:
                action.is_active = item["is_active"]
            if "task_id" in item:
                action.task_id = item["task_id"]
            if "task_status" in item:
                action.task_status = item["task_status"]
            if "task_title" in item:
                action.task_title = item["task_title"]
            if "task_current_step" in item:
                action.task_current_step = item["task_current_step"]
            if "notes" in item:
                action.notes = item["notes"]

            actions.append(action)

        processed_memory_ids = [m.memory_id for m in memories]
        processed_task_ids = [t.task_id for t in tasks]
        result_notes = obj.get("notes", []) if isinstance(obj, dict) else []

        return ConsolidationResult(
            user_id=user_id,
            processed_memory_ids=processed_memory_ids,
            processed_task_ids=processed_task_ids,
            actions=actions,
            notes=result_notes,
        )
