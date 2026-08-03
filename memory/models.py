from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional


MemoryKind = Literal[
    "conversation_summary",
    "episode",
    "fact",
    "preference",
    "task",
    "project",
    "artifact",
    "correction"
]

TaskStatus = Literal["open", "in_progress", "blocked", "done", "cancelled", "archived"]
Role = Literal["system", "user", "assistant", "tool"]

ConsolidationActionKind = Literal[
    "keep",
    "update_memory",
    "deactivate_memory",
    "merge_memories",
    "update_task",
    "create_memory",
]

@dataclass
class Message:
    role: Role
    content: str
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationTranscript:
    conversation_id: str
    user_id: str
    started_at: datetime
    ended_at: Optional[datetime]
    messages: list[Message]
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, message: Message) -> None:
        self.messages.append(message)


@dataclass
class MemoryRecord:
    memory_id: str
    user_id: str
    kind: MemoryKind
    content: str
    summary: Optional[str]
    created_at: datetime
    updated_at: Optional[datetime] = None

    conversation_id: Optional[str] = None
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    subject: Optional[str] = None

    importance: float = 0.5
    confidence: float = 0.7

    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    is_active: bool = True

    source: str = "conversation"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class UserProfile:
    user_id: str
    display_name: Optional[str] = None
    preferences: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)
    active_projects: list[str] = field(default_factory=list)
    active_tasks: list[str] = field(default_factory=list)
    updated_at: Optional[datetime] = None


@dataclass
class TaskRecord:
    task_id: str
    user_id: str
    title: str
    status: TaskStatus
    goal: Optional[str] = None
    plan: list[str] = field(default_factory=list)
    current_step: Optional[str] = None
    blockers: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievedMemoryBundle:
    user_id: str
    query: str
    profile: Optional[UserProfile]
    relevant_memories: list[MemoryRecord]
    active_tasks: list[TaskRecord]
    generated_summary_block: str


@dataclass
class ConversationState:
    conversation_id: str
    user_id: str
    running_summary: str = ""
    open_questions: list[str] = field(default_factory=list)
    current_goals: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    important_points: list[str] = field(default_factory=list)
    last_updated: Optional[datetime] = None


@dataclass
class PostProcessResult:
    conversation_id: str
    user_id: str
    stored_memory_ids: list[str] = field(default_factory=list)
    updated_task_ids: list[str] = field(default_factory=list)
    updated_profile: bool = False
    candidate_memories: list[MemoryRecord] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

@dataclass
class ConsolidationAction:
    action: ConsolidationActionKind
    memory_id: Optional[str] = None
    memory_ids: list[str] = field(default_factory=list)

    content: Optional[str] = None
    summary: Optional[str] = None
    kind: Optional[MemoryKind] = None
    tags: list[str] = field(default_factory=list)
    importance: Optional[float] = None
    confidence: Optional[float] = None
    is_active: Optional[bool] = None

    task_id: Optional[str] = None
    task_status: Optional[str] = None
    task_title: Optional[str] = None
    task_current_step: Optional[str] = None

    notes: Optional[str] = None

@dataclass
class ConsolidationResult:
    user_id: str
    processed_memory_ids: list[str] = field(default_factory=list)
    processed_task_ids: list[str] = field(default_factory=list)
    actions: list[ConsolidationAction] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
