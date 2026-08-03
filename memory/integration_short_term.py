from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Sequence

from .conversation import ConversationMemory
from .long_term import LongTermMemory
from .models import Message

def build_memory_block(
    long_term_memory: LongTermMemory,
    *,
    user_id: str,
    input_text: str,
    past_messages: Sequence[dict[str, Any]],
    conversation_id: Optional[str] = None,
) -> str:
    """
    Build a prompt-ready memory block for the next user input, using
    past messages plus the current input text.
    """
    if conversation_id is None:
        conversation_id = f"live-{user_id}"

    convo = long_term_memory.start_conversation(
        user_id=user_id,
        conversation_id=conversation_id
    )

    # Replay prior messages into ConversationMemory
    for msg in past_messages:
        role = msg.get("role")
        content = msg.get("content")
        if not role or not content:
            continue

        if role in ("system", "user", "assistant", "tool"):
            convo.add_message(role, content)
        else:
            # skip or normalize unknown roles
            continue
        
    # Add current user input as the newest message
    convo.add_message("user", input_text)


    # Refresh prompt block based on full current state
    return convo.refresh_prompt_block(query=input_text)
