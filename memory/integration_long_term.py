from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from .models import ConversationTranscript, Message
from .long_term import LongTermMemory

def ingest_conversation(
    long_term_memory: LongTermMemory,
    *,
    user_id: str,
    conversation_id: str,
    messages: Sequence[dict[str, Any]],
    started_at: Optional[datetime] = None,
    ended_at: Optional[datetime] = None,
    metadata: Optional[dict[str, Any]] = None,
):
    transcript = ConversationTranscript(
        conversation_id=conversation_id,
        user_id=user_id,
        started_at=started_at or datetime.utcnow(),
        ended_at=ended_at or datetime.utcnow(),
        messages=[
            Message(
                role=msg["role"],
                content=msg["content"],
                created_at=msg.get("created_at", ended_at or datetime.utcnow()),
                metadata=msg.get("metadata", {}),
            )
            for msg in messages
            if "role" in msg and "content" in msg
        ],
        metadata=metadata or {},
    )

    return long_term_memory.post_process_conversation(transcript)
