## Verify that memory for one user is not retrieved for another user.
from memory.fixtures import build_inmemory_test_system, memory_record


def test_multi_user_memory_is_isolated():
    system = build_inmemory_test_system()
    ltm = system.long_term_memory

    ltm.remember(
        memory_record(
            user_id="alice",
            kind="fact",
            content="Alice uses Python for AI",
            tags=["python"],
            importance=0.9,
        )
    )

    ltm.remember(
        memory_record(
            user_id="charlie",
            kind="fact",
            content="Charlie grows tomatoes",
            tags=["gardening"],
            importance=0.9,
        )
    )

    alice_results = ltm.retrieve_by_keywords("alice", query="Python", limit=10)
    charlie_results = ltm.retrieve_by_keywords("charlie", query="Python", limit=10)

    assert any("Python" in m.content for m in alice_results)
    assert all("Charlie grows tomatoes" not in m.content for m in alice_results)

    assert charlie_results == [] or all("Python" not in m.content for m in charlie_results)


def test_multi_user_listing_is_isolated():
    system = build_inmemory_test_system()
    ltm = system.long_term_memory

    ltm.remember(
        memory_record(
            user_id="alice",
            kind="fact",
            content="Alice likes pandas",
        )
    )
    ltm.remember(
        memory_record(
            user_id="bob",
            kind="fact",
            content="Bob likes tomatoes",
        )
    )

    alice_memories = ltm.list_user_memories("alice")
    bob_memories = ltm.list_user_memories("bob")

    assert any("Alice likes pandas" == m.content for m in alice_memories)
    assert all(m.content != "Bob likes tomatoes" for m in alice_memories)

    assert any("Bob likes tomatoes" == m.content for m in bob_memories)
    assert all(m.content != "Alice likes pandas" for m in bob_memories)
