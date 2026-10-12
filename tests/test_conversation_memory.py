# Verify that ConversationMemory.update_with_turn(...):
# appends assistant/user messages correctly
# updates conversation state
# calls retrieval through LongTermMemory
# returns a nonempty prompt block containing relevant memory

from datetime import datetime

from memory.fixtures import build_inmemory_test_system, memory_record


def test_conversation_memory_updates_and_returns_prompt_block():
    system = build_inmemory_test_system()
    ltm = system.long_term_memory

    user_id = "alice"
    ltm.initialize_user(user_id)

    ltm.remember(
        memory_record(
            user_id=user_id,
            kind="fact",
            content="Uses Python for AI systems",
            tags=["python", "ai"],
            importance=0.9,
        )
    )

    convo = ltm.start_conversation(
        user_id=user_id,
        conversation_id="conv-1",
        initial_query="Help me design a Python memory system",
    )

    block = convo.update_with_turn(
        assistant_response="What kind of memory do you want?",
        user_response="I want long-term memory for my Python assistant.",
    )

    assert "Relevant memory:" in block
    assert "Uses Python for AI systems" in block

    state = convo.get_state()
    assert state.running_summary
    assert any("Python assistant" in p or "Python" in p for p in state.important_points)


def test_conversation_memory_finalize_persists_conversation():
    system = build_inmemory_test_system()
    ltm = system.long_term_memory

    user_id = "alice"
    convo = ltm.start_conversation(
        user_id=user_id,
        conversation_id="conv-finalize-1",
        initial_query="Test finalize flow",
    )

    convo.update_with_turn(
        assistant_response="Tell me something to remember.",
        user_response="remember: I use Python",
    )

    result = convo.finalize()

    assert result.conversation_id == "conv-finalize-1"
    assert result.user_id == user_id
    assert result.stored_memory_ids

    saved = ltm.store.get_conversation(user_id, "conv-finalize-1")
    assert saved is not None
    assert len(saved.messages) == 2
    assert saved.ended_at is not None
