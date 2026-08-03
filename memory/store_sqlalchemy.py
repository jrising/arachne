from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    String,
    Text,
    create_engine,
    select,
    delete,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from .models import (
    ConversationTranscript,
    MemoryKind,
    MemoryRecord,
    Message,
    TaskRecord,
    TaskStatus,
    UserProfile,
)


class Base(DeclarativeBase):
    pass


class UserRow(Base):
    __tablename__ = "memory_users"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    profile: Mapped[Optional["UserProfileRow"]] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class UserProfileRow(Base):
    __tablename__ = "memory_user_profiles"

    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("memory_users.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    display_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    preferences: Mapped[list[str]] = mapped_column(JSON, default=list)
    facts: Mapped[list[str]] = mapped_column(JSON, default=list)
    active_projects: Mapped[list[str]] = mapped_column(JSON, default=list)
    active_tasks: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    user: Mapped[UserRow] = relationship(back_populates="profile")


class ConversationRow(Base):
    __tablename__ = "memory_conversations"

    conversation_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("memory_users.user_id", ondelete="CASCADE"),
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    messages: Mapped[list["MessageRow"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="MessageRow.position",
    )


class MessageRow(Base):
    __tablename__ = "memory_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("memory_conversations.conversation_id", ondelete="CASCADE"),
        index=True,
    )
    position: Mapped[int] = mapped_column(index=True)
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    conversation: Mapped[ConversationRow] = relationship(back_populates="messages")


class MemoryRow(Base):
    __tablename__ = "memory_records"

    memory_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("memory_users.user_id", ondelete="CASCADE"),
        index=True,
    )
    kind: Mapped[str] = mapped_column(String, index=True)
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    conversation_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    project_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    task_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    subject: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    importance: Mapped[float] = mapped_column(Float, default=0.5)
    confidence: Mapped[float] = mapped_column(Float, default=0.7)

    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    source: Mapped[str] = mapped_column(String, default="conversation")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class TaskRow(Base):
    __tablename__ = "memory_tasks"

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("memory_users.user_id", ondelete="CASCADE"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, index=True)
    goal: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plan: Mapped[list[str]] = mapped_column(JSON, default=list)
    current_step: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blockers: Mapped[list[str]] = mapped_column(JSON, default=list)
    artifacts: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

class SQLAlchemyMemoryStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
    ) -> None:
        self.session_factory = session_factory
        self._memory_counter = 0
        self._task_counter = 0

    @classmethod
    def from_url(cls, database_url: str) -> "SQLAlchemyMemoryStore":
        engine = create_engine(database_url, future=True)
        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
        return cls(session_factory)

    def create_all(self) -> None:
        with self.session_factory() as session:
            bind = session.get_bind()
            if bind is None:
                raise RuntimeError("No engine bound to session.")
            Base.metadata.create_all(bind)

    def create_user_if_missing(self, user_id: str) -> None:
        with self.session_factory() as session:
            row = session.get(UserRow, user_id)
            if row is None:
                session.add(UserRow(user_id=user_id))
                session.commit()

    def _next_memory_id(self) -> str:
        self._memory_counter += 1
        return f"mem-{int(datetime.utcnow().timestamp())}-{self._memory_counter}"

    def _next_task_id(self) -> str:
        self._task_counter += 1
        return f"task-{int(datetime.utcnow().timestamp())}-{self._task_counter}"

    def _memory_from_row(self, row: MemoryRow) -> MemoryRecord:
        return MemoryRecord(
            memory_id=row.memory_id,
            user_id=row.user_id,
            kind=row.kind,  # type: ignore[arg-type]
            content=row.content,
            summary=row.summary,
            created_at=row.created_at,
            updated_at=row.updated_at,
            conversation_id=row.conversation_id,
            project_id=row.project_id,
            task_id=row.task_id,
            subject=row.subject,
            importance=row.importance,
            confidence=row.confidence,
            valid_from=row.valid_from,
            valid_until=row.valid_until,
            is_active=row.is_active,
            source=row.source,
            tags=list(row.tags or []),
            metadata=dict(row.metadata_json or {}),
        )

    def _memory_to_row(self, memory: MemoryRecord) -> MemoryRow:
        return MemoryRow(
            memory_id=memory.memory_id or self._next_memory_id(),
            user_id=memory.user_id,
            kind=memory.kind,
            content=memory.content,
            summary=memory.summary,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
            conversation_id=memory.conversation_id,
            project_id=memory.project_id,
            task_id=memory.task_id,
            subject=memory.subject,
            importance=memory.importance,
            confidence=memory.confidence,
            valid_from=memory.valid_from,
            valid_until=memory.valid_until,
            is_active=memory.is_active,
            source=memory.source,
            tags=list(memory.tags),
            metadata_json=dict(memory.metadata),
        )

    def _task_from_row(self, row: TaskRow) -> TaskRecord:
        return TaskRecord(
            task_id=row.task_id,
            user_id=row.user_id,
            title=row.title,
            status=row.status,  # type: ignore[arg-type]
            goal=row.goal,
            plan=list(row.plan or []),
            current_step=row.current_step,
            blockers=list(row.blockers or []),
            artifacts=list(row.artifacts or []),
            created_at=row.created_at,
            updated_at=row.updated_at,
            metadata=dict(row.metadata_json or {}),
        )

    def _task_to_row(self, task: TaskRecord) -> TaskRow:
        return TaskRow(
            task_id=task.task_id or self._next_task_id(),
            user_id=task.user_id,
            title=task.title,
            status=task.status,
            goal=task.goal,
            plan=list(task.plan),
            current_step=task.current_step,
            blockers=list(task.blockers),
            artifacts=list(task.artifacts),
            created_at=task.created_at,
            updated_at=task.updated_at,
            metadata_json=dict(task.metadata),
        )

    def _profile_from_row(self, row: UserProfileRow) -> UserProfile:
        return UserProfile(
            user_id=row.user_id,
            display_name=row.display_name,
            preferences=list(row.preferences or []),
            facts=list(row.facts or []),
            active_projects=list(row.active_projects or []),
            active_tasks=list(row.active_tasks or []),
            updated_at=row.updated_at,
        )

    def _profile_to_row(self, profile: UserProfile) -> UserProfileRow:
        return UserProfileRow(
            user_id=profile.user_id,
            display_name=profile.display_name,
            preferences=list(profile.preferences),
            facts=list(profile.facts),
            active_projects=list(profile.active_projects),
            active_tasks=list(profile.active_tasks),
            updated_at=profile.updated_at,
        )

    def save_memory(self, memory: MemoryRecord) -> str:
        self.create_user_if_missing(memory.user_id)

        with self.session_factory() as session:
            memory_id = memory.memory_id or self._next_memory_id()
            existing = session.get(MemoryRow, memory_id)

            if existing is None:
                row = self._memory_to_row(
                    MemoryRecord(
                        memory_id=memory_id,
                        user_id=memory.user_id,
                        kind=memory.kind,
                        content=memory.content,
                        summary=memory.summary,
                        created_at=memory.created_at,
                        updated_at=memory.updated_at or memory.created_at,
                        conversation_id=memory.conversation_id,
                        project_id=memory.project_id,
                        task_id=memory.task_id,
                        subject=memory.subject,
                        importance=memory.importance,
                        confidence=memory.confidence,
                        valid_from=memory.valid_from,
                        valid_until=memory.valid_until,
                        is_active=memory.is_active,
                        source=memory.source,
                        tags=list(memory.tags),
                        metadata=dict(memory.metadata),
                    )
                )
                session.add(row)
            else:
                existing.user_id = memory.user_id
                existing.kind = memory.kind
                existing.content = memory.content
                existing.summary = memory.summary
                existing.updated_at = memory.updated_at or datetime.utcnow()
                existing.conversation_id = memory.conversation_id
                existing.project_id = memory.project_id
                existing.task_id = memory.task_id
                existing.subject = memory.subject
                existing.importance = memory.importance
                existing.confidence = memory.confidence
                existing.valid_from = memory.valid_from
                existing.valid_until = memory.valid_until
                existing.is_active = memory.is_active
                existing.source = memory.source
                existing.tags = list(memory.tags)
                existing.metadata_json = dict(memory.metadata)

            session.commit()
            return memory_id

    def update_memory(self, memory: MemoryRecord) -> None:
        if not memory.memory_id:
            raise ValueError("update_memory requires memory.memory_id")
        self.save_memory(
            MemoryRecord(
                memory_id=memory.memory_id,
                user_id=memory.user_id,
                kind=memory.kind,
                content=memory.content,
                summary=memory.summary,
                created_at=memory.created_at,
                updated_at=datetime.utcnow(),
                conversation_id=memory.conversation_id,
                project_id=memory.project_id,
                task_id=memory.task_id,
                subject=memory.subject,
                importance=memory.importance,
                confidence=memory.confidence,
                valid_from=memory.valid_from,
                valid_until=memory.valid_until,
                is_active=memory.is_active,
                source=memory.source,
                tags=list(memory.tags),
                metadata=dict(memory.metadata),
            )
        )

    def get_memory(self, user_id: str, memory_id: str) -> Optional[MemoryRecord]:
        with self.session_factory() as session:
            row = session.get(MemoryRow, memory_id)
            if row is None or row.user_id != user_id:
                return None
            return self._memory_from_row(row)

    def list_memories(
        self,
        user_id: str,
        *,
        kind: Optional[MemoryKind] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> list[MemoryRecord]:
        with self.session_factory() as session:
            stmt = select(MemoryRow).where(MemoryRow.user_id == user_id)

            if kind is not None:
                stmt = stmt.where(MemoryRow.kind == kind)
            if active_only:
                stmt = stmt.where(MemoryRow.is_active.is_(True))

            stmt = stmt.order_by(MemoryRow.importance.desc(), MemoryRow.created_at.desc()).limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [self._memory_from_row(row) for row in rows]

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
        with self.session_factory() as session:
            stmt = select(MemoryRow).where(MemoryRow.user_id == user_id)

            if kind is not None:
                stmt = stmt.where(MemoryRow.kind == kind)
            if conversation_id is not None:
                stmt = stmt.where(MemoryRow.conversation_id == conversation_id)
            if project_id is not None:
                stmt = stmt.where(MemoryRow.project_id == project_id)
            if task_id is not None:
                stmt = stmt.where(MemoryRow.task_id == task_id)
            if active_only:
                stmt = stmt.where(MemoryRow.is_active.is_(True))

            rows = session.execute(
                stmt.order_by(MemoryRow.importance.desc(), MemoryRow.created_at.desc()).limit(limit)
            ).scalars().all()

            memories = [self._memory_from_row(row) for row in rows]

            if tags:
                tagset = set(tags)
                memories = [m for m in memories if tagset.intersection(m.tags)]

            return memories[:limit]

    def save_conversation(self, transcript: ConversationTranscript) -> None:
        self.create_user_if_missing(transcript.user_id)

        with self.session_factory() as session:
            existing = session.get(ConversationRow, transcript.conversation_id)

            if existing is not None:
                session.execute(
                    delete(MessageRow).where(MessageRow.conversation_id == transcript.conversation_id)
                )
                session.delete(existing)
                session.flush()

            row = ConversationRow(
                conversation_id=transcript.conversation_id,
                user_id=transcript.user_id,
                started_at=transcript.started_at,
                ended_at=transcript.ended_at,
                metadata_json=dict(transcript.metadata),
            )
            session.add(row)
            session.flush()

            for i, message in enumerate(transcript.messages):
                session.add(
                    MessageRow(
                        conversation_id=transcript.conversation_id,
                        position=i,
                        role=message.role,
                        content=message.content,
                        created_at=message.created_at,
                        metadata_json=dict(message.metadata),
                    )
                )

            session.commit()

    def get_conversation(
        self,
        user_id: str,
        conversation_id: str,
    ) -> Optional[ConversationTranscript]:
        with self.session_factory() as session:
            row = session.get(ConversationRow, conversation_id)
            if row is None or row.user_id != user_id:
                return None

            messages = [
                Message(
                    role=msg.role,  # type: ignore[arg-type]
                    content=msg.content,
                    created_at=msg.created_at,
                    metadata=dict(msg.metadata_json or {}),
                )
                for msg in row.messages
            ]

            return ConversationTranscript(
                conversation_id=row.conversation_id,
                user_id=row.user_id,
                started_at=row.started_at,
                ended_at=row.ended_at,
                messages=messages,
                metadata=dict(row.metadata_json or {}),
            )

    def save_user_profile(self, profile: UserProfile) -> None:
        self.create_user_if_missing(profile.user_id)

        with self.session_factory() as session:
            row = session.get(UserProfileRow, profile.user_id)
            if row is None:
                row = self._profile_to_row(
                    UserProfile(
                        user_id=profile.user_id,
                        display_name=profile.display_name,
                        preferences=list(profile.preferences),
                        facts=list(profile.facts),
                        active_projects=list(profile.active_projects),
                        active_tasks=list(profile.active_tasks),
                        updated_at=profile.updated_at or datetime.utcnow(),
                    )
                )
                session.add(row)
            else:
                row.display_name = profile.display_name
                row.preferences = list(profile.preferences)
                row.facts = list(profile.facts)
                row.active_projects = list(profile.active_projects)
                row.active_tasks = list(profile.active_tasks)
                row.updated_at = profile.updated_at or datetime.utcnow()

            session.commit()

    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        with self.session_factory() as session:
            row = session.get(UserProfileRow, user_id)
            if row is None:
                return None
            return self._profile_from_row(row)

    def save_task(self, task: TaskRecord) -> str:
        self.create_user_if_missing(task.user_id)

        with self.session_factory() as session:
            task_id = task.task_id or self._next_task_id()
            existing = session.get(TaskRow, task_id)

            if existing is None:
                row = self._task_to_row(
                    TaskRecord(
                        task_id=task_id,
                        user_id=task.user_id,
                        title=task.title,
                        status=task.status,
                        goal=task.goal,
                        plan=list(task.plan),
                        current_step=task.current_step,
                        blockers=list(task.blockers),
                        artifacts=list(task.artifacts),
                        created_at=task.created_at,
                        updated_at=task.updated_at or datetime.utcnow(),
                        metadata=dict(task.metadata),
                    )
                )
                session.add(row)
            else:
                existing.user_id = task.user_id
                existing.title = task.title
                existing.status = task.status
                existing.goal = task.goal
                existing.plan = list(task.plan)
                existing.current_step = task.current_step
                existing.blockers = list(task.blockers)
                existing.artifacts = list(task.artifacts)
                existing.updated_at = task.updated_at or datetime.utcnow()
                existing.metadata_json = dict(task.metadata)

            session.commit()
            return task_id

    def update_task(self, task: TaskRecord) -> None:
        if not task.task_id:
            raise ValueError("update_task requires task.task_id")
        self.save_task(
            TaskRecord(
                task_id=task.task_id,
                user_id=task.user_id,
                title=task.title,
                status=task.status,
                goal=task.goal,
                plan=list(task.plan),
                current_step=task.current_step,
                blockers=list(task.blockers),
                artifacts=list(task.artifacts),
                created_at=task.created_at,
                updated_at=datetime.utcnow(),
                metadata=dict(task.metadata),
            )
        )

    def get_task(self, user_id: str, task_id: str) -> Optional[TaskRecord]:
        with self.session_factory() as session:
            row = session.get(TaskRow, task_id)
            if row is None or row.user_id != user_id:
                return None
            return self._task_from_row(row)

    def list_tasks(
        self,
        user_id: str,
        *,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        with self.session_factory() as session:
            stmt = select(TaskRow).where(TaskRow.user_id == user_id)
            if status is not None:
                stmt = stmt.where(TaskRow.status == status)

            stmt = stmt.order_by(TaskRow.updated_at.desc()).limit(limit)
            rows = session.execute(stmt).scalars().all()
            return [self._task_from_row(row) for row in rows]

    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        with self.session_factory() as session:
            row = session.get(MemoryRow, memory_id)
            if row is None or row.user_id != user_id:
                return False
            session.delete(row)
            session.commit()
            return True

