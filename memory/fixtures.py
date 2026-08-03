from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .index_null import NullMemoryIndex, SimpleTextMemoryIndex
from .index_whoosh import WhooshMemoryIndex
from .long_term import LongTermMemory
from .model_mock import MockMemoryModel
from .models import (
    ConversationTranscript,
    MemoryKind,
    MemoryRecord,
    Message,
    TaskRecord,
    TaskStatus,
    UserProfile,
)
from .store_inmemory import InMemoryStore
from .store_sqlalchemy import Base, SQLAlchemyMemoryStore

@dataclass
class TestMemorySystem:
    long_term_memory: LongTermMemory
    store: object
    model: MockMemoryModel
    index: object

@dataclass
class ManagedTestMemorySystem(TestMemorySystem):
    temp_dir: Optional[TemporaryDirectory] = None

    def close(self) -> None:
        if self.temp_dir is not None:
            self.temp_dir.cleanup()
            self.temp_dir = None

def message(
    *,
    role: str = "user",
    content: str = "hello",
    created_at: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> Message:
    return Message(
        role=role,  # type: ignore[arg-type]
        content=content,
        created_at=created_at or datetime.utcnow(),
        metadata=metadata or {},
    )


def conversation_transcript(
    *,
    conversation_id: str = "conv-1",
    user_id: str = "user-1",
    messages: Optional[list[Message]] = None,
    started_at: Optional[datetime] = None,
    ended_at: Optional[datetime] = None,
    metadata: Optional[dict] = None,
) -> ConversationTranscript:
    started = started_at or datetime.utcnow()
    return ConversationTranscript(
        conversation_id=conversation_id,
        user_id=user_id,
        started_at=started,
        ended_at=ended_at,
        messages=messages or [],
        metadata=metadata or {},
    )


def memory_record(
    *,
    user_id: str = "user-1",
    kind: MemoryKind = "fact",
    content: str = "Uses Python",
    summary: Optional[str] = None,
    memory_id: str = "",
    conversation_id: Optional[str] = None,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    subject: Optional[str] = None,
    importance: float = 0.5,
    confidence: float = 0.8,
    source: str = "test",
    tags: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
    created_at: Optional[datetime] = None,
) -> MemoryRecord:
    text_summary = summary if summary is not None else content[:200]
    return MemoryRecord(
        memory_id=memory_id,
        user_id=user_id,
        kind=kind,
        content=content,
        summary=text_summary,
        created_at=created_at or datetime.utcnow(),
        updated_at=None,
        conversation_id=conversation_id,
        project_id=project_id,
        task_id=task_id,
        subject=subject,
        importance=importance,
        confidence=confidence,
        valid_from=None,
        valid_until=None,
        is_active=True,
        source=source,
        tags=tags or [],
        metadata=metadata or {},
    )


def task_record(
    *,
    user_id: str = "user-1",
    task_id: str = "",
    title: str = "Test task",
    status: TaskStatus = "open",
    goal: Optional[str] = None,
    plan: Optional[list[str]] = None,
    current_step: Optional[str] = None,
    blockers: Optional[list[str]] = None,
    artifacts: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
    created_at: Optional[datetime] = None,
    updated_at: Optional[datetime] = None,
) -> TaskRecord:
    now = datetime.utcnow()
    return TaskRecord(
        task_id=task_id,
        user_id=user_id,
        title=title,
        status=status,
        goal=goal,
        plan=plan or [],
        current_step=current_step,
        blockers=blockers or [],
        artifacts=artifacts or [],
        created_at=created_at or now,
        updated_at=updated_at or now,
        metadata=metadata or {},
    )


def user_profile(
    *,
    user_id: str = "user-1",
    display_name: Optional[str] = None,
    preferences: Optional[list[str]] = None,
    facts: Optional[list[str]] = None,
    active_projects: Optional[list[str]] = None,
    active_tasks: Optional[list[str]] = None,
    updated_at: Optional[datetime] = None,
) -> UserProfile:
    return UserProfile(
        user_id=user_id,
        display_name=display_name,
        preferences=preferences or [],
        facts=facts or [],
        active_projects=active_projects or [],
        active_tasks=active_tasks or [],
        updated_at=updated_at or datetime.utcnow(),
    )


def build_inmemory_test_system() -> TestMemorySystem:
    store = InMemoryStore()
    model = MockMemoryModel()
    index = SimpleTextMemoryIndex(store)
    ltm = LongTermMemory(store=store, model=model, index=index)
    return TestMemorySystem(
        long_term_memory=ltm,
        store=store,
        model=model,
        index=index,
    )


def build_inmemory_null_index_system() -> TestMemorySystem:
    store = InMemoryStore()
    model = MockMemoryModel()
    index = NullMemoryIndex()
    ltm = LongTermMemory(store=store, model=model, index=index)
    return TestMemorySystem(
        long_term_memory=ltm,
        store=store,
        model=model,
        index=index,
    )


def build_sqlite_test_system(
    sqlite_url: str = "sqlite+pysqlite:///:memory:",
) -> TestMemorySystem:
    engine = create_engine(sqlite_url, future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True, expire_on_commit=False, class_=Session)

    store = SQLAlchemyMemoryStore(session_factory=session_factory)
    model = MockMemoryModel()
    index = NullMemoryIndex()
    ltm = LongTermMemory(store=store, model=model, index=index)

    return TestMemorySystem(
        long_term_memory=ltm,
        store=store,
        model=model,
        index=index,
    )


def build_sqlite_whoosh_test_system() -> ManagedTestMemorySystem:
    temp_dir = TemporaryDirectory()
    root = Path(temp_dir.name)

    sqlite_path = root / "memory.sqlite"
    whoosh_path = root / "whoosh"

    engine = create_engine(f"sqlite+pysqlite:///{sqlite_path}", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True, expire_on_commit=False, class_=Session)

    store = SQLAlchemyMemoryStore(session_factory=session_factory)
    model = MockMemoryModel()
    index = WhooshMemoryIndex(whoosh_path)
    ltm = LongTermMemory(store=store, model=model, index=index)

    return ManagedTestMemorySystem(
        long_term_memory=ltm,
        store=store,
        model=model,
        index=index,
        temp_dir=temp_dir,
    )


def seed_user_basics(ltm: LongTermMemory, user_id: str) -> None:
    ltm.initialize_user(user_id)

    ltm.remember(
        memory_record(
            user_id=user_id,
            kind="fact",
            content="Uses Python for AI workflows",
            tags=["python", "ai"],
            importance=0.9,
        )
    )
    ltm.remember(
        memory_record(
            user_id=user_id,
            kind="preference",
            content="Prefers practical, direct technical answers",
            tags=["preference", "style"],
            importance=0.8,
        )
    )
    ltm.remember(
        memory_record(
            user_id=user_id,
            kind="project",
            content="Working on a long-term memory system for an OpenAI-based assistant",
            tags=["project", "memory", "openai"],
            importance=0.85,
        )
    )


def seed_python_project_memories(ltm: LongTermMemory, user_id: str) -> None:
    ltm.initialize_user(user_id)

    memories = [
        memory_record(
            user_id=user_id,
            kind="fact",
            content="Uses SQLAlchemy for persistent data storage",
            tags=["python", "sqlalchemy"],
            importance=0.8,
        ),
        memory_record(
            user_id=user_id,
            kind="fact",
            content="Uses Whoosh for keyword retrieval over conversation summaries",
            tags=["python", "whoosh", "search"],
            importance=0.75,
        ),
        memory_record(
            user_id=user_id,
            kind="project",
            content="Designing ConversationMemory and LongTermMemory abstractions",
            tags=["architecture", "memory"],
            importance=0.9,
        ),
        memory_record(
            user_id=user_id,
            kind="preference",
            content="Wants systems to be testable with isolated fixtures and multiple users",
            tags=["testing", "architecture"],
            importance=0.85,
        ),
    ]

    for mem in memories:
        ltm.remember(mem)


def seed_active_task(
    ltm: LongTermMemory,
    user_id: str,
    *,
    title: str = "Implement memory system",
    status: TaskStatus = "in_progress",
    goal: Optional[str] = "Build persistent agent memory",
    current_step: Optional[str] = "Define storage and indexing interfaces",
) -> str:
    ltm.initialize_user(user_id)
    return ltm.store.save_task(
        task_record(
            user_id=user_id,
            title=title,
            status=status,
            goal=goal,
            current_step=current_step,
            plan=[
                "Define models",
                "Define protocols",
                "Implement stores",
                "Implement index",
                "Write tests",
            ],
        )
    )


def seed_two_user_scenario(ltm: LongTermMemory) -> tuple[str, str]:
    user_a = "alice"
    user_b = "bob"

    seed_user_basics(ltm, user_a)
    seed_user_basics(ltm, user_b)

    ltm.remember(
        memory_record(
            user_id=user_a,
            kind="fact",
            content="Alice is focused on Python agent architecture",
            tags=["alice", "python"],
            importance=0.9,
        )
    )
    ltm.remember(
        memory_record(
            user_id=user_b,
            kind="fact",
            content="Bob is focused on gardening and tomatoes",
            tags=["bob", "gardening"],
            importance=0.9,
        )
    )

    return user_a, user_b
