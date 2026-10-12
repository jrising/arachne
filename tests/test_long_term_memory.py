# Verify that LongTermMemory.post_process_conversation(...):
# saves the conversation
# creates a conversation summary memory
# extracts candidate memories from the transcript
# stores them
# updates the user profile

from datetime import datetime

from memory.fixtures import (
    build_inmemory_test_system,
    conversation_transcript,
    memory_record,
    message,
)


def test_post_process_conversation_stores_memories_and_updates_profile():
    system = build_inmemory_test_system()
    ltm = system.long_term_memory

    user_id = "bob"
    transcript = conversation_transcript(
        conversation_id="conv-2",
        user_id=user_id,
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
        messages=[
            message(role="user", content="remember: I use Python"),
            message(role="user", content="preference: concise answers"),
            message(role="user", content="task: build a memory manager"),
        ],
    )

    result = ltm.post_process_conversation(transcript)

    assert result.stored_memory_ids
    assert result.updated_profile is True

    memories = ltm.list_user_memories(user_id)
    assert any(m.kind == "conversation_summary" for m in memories)
    assert any(m.kind == "fact" and m.content == "I use Python" for m in memories)
    assert any(m.kind == "preference" and m.content == "concise answers" for m in memories)
    assert any(m.kind == "task" and m.content == "build a memory manager" for m in memories)

    profile = ltm.get_user_profile(user_id)
    assert profile is not None
    assert "I use Python" in profile.facts
    assert "concise answers" in profile.preferences
    assert "build a memory manager" in profile.active_tasks


def test_remember_and_forget_memory():
    system = build_inmemory_test_system()
    ltm = system.long_term_memory

    user_id = "bob"

    memory_id = ltm.remember(
        memory_record(
            user_id=user_id,
            kind="fact",
            content="Uses SQLAlchemy",
            tags=["sqlalchemy"],
        )
    )

    before = ltm.list_user_memories(user_id)
    assert any(m.memory_id == memory_id for m in before)

    deleted = ltm.forget(user_id, memory_id=memory_id)
    assert deleted == 1

    after = ltm.list_user_memories(user_id)
    assert all(m.memory_id != memory_id for m in after)
