from dataclasses import dataclass
from typing import Any

from chatwrap import gemini
import utils
import memory
import memory.default, memory.integration_short_term

def retrieve_memory_context(
        messages: list[dict],
        context: PlannerContext,
        config: dict[str, Any],
) -> str:
    """Build the history_text supplied to create_chat()."""
    strategy = config.get("strategy", "short_term_only")

    dialogue = [
        message for message in messages
        if message.get("role") in ("user", "assistant")
    ]
    prompt = dialogue[-1]["content"] if dialogue else ""
    past_messages = dialogue[:-1]
    
    ltm = memory.default.create_long_term()
    stm = memory.integration_short_term.build_memory_block(
        ltm,
        user_id=context.user_id_for_memory,
        input_text=prompt,
        past_messages=past_messages,
    )

    if strategy == "short_term_only":
        return stm

    if strategy == "history_list":
        history = context.history_list_raw_data
        if not history:
            return stm

        history = history.replace("\n\n", "\n").replace("\n\n", "\n")
        return (
            stm
            + "\n\nBelow are selected log entries of past conversations.\n"
            + history
        )

    if strategy == "gemini_helper":
        results = utils.get_logs_raw(prompt)

        previous_response = ""
        if past_messages:
            previous_response = (
                "\n===\nHere is the previous response from Arachne:\n===\n"
                + past_messages[-1]["content"]
            )

        logs_summary = "\n===\n".join(
            result["path"][9:19]
            + " "
            + result["path"][20:28].replace("-", ":")
            + ": "
            + result["content"]
            for result in results
        )

        prompt = (
            "The following query has been submitted to a super-intelligent "
            "AI assistant named Arachne, which you support as a memory system:\n===\n"
            + prompt
            + previous_response
            + "\n===\nHere are outputs from an automated memory system:\n===\n"
            + stm
            + "\n===\nAnd the following past discussion synopses have been "
              "retrieved, which may relate to this query:\n===\n"
            + logs_summary
            + "\n===\nPlease excerpt relevant memory items and summarize any "
              "history entries that are relevant to the query."
        )
        return gemini.single_prompt(prompt)

    raise ValueError(f"Unknown memory strategy: {strategy}")

tool_info = dict(
    name="retrieve_memory_context",
    description="Retrieve short- and long-term conversational memory.",
    fn=retrieve_memory_context,
    config={
        "defaults": {},
        "options": {
            "strategy": ["history_list", "gemini_helper", "short_term_only"],
        },
    },
    quality_prior=0.90,
    cost_estimate=0.01)
