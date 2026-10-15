import random, uuid
from dataclasses import dataclass
from typing import Any, Callable
from chatwrap import selector, openaigpt
from utils import fillin_training_end

@dataclass
class PlannerContext:
    user_id_for_memory: str
    history_list_raw_data: str = ""

@dataclass
class Response:
    id: str
    text: str
    model: str | None = None

@dataclass
class StreamResponse:
    id: str
    chunks: object          # Iterator[str]
    model: str | None = None

    def __iter__(self):
        return iter(self.chunks)

@dataclass
class Tool:
    name: str
    description: str
    fn: Callable
    config: dict[str, Any]
    quality_prior: float | None = None
    cost_estimate: float | None = None
    
class Planner:
    tools: dict[str, Tool] = {}

    @classmethod
    def register_tool(
        cls,
        name: str,
        description: str,
        fn: Callable,
        config: dict[str, Any],
        quality_prior: float | None = None,
        cost_estimate: float | None = None,
    ):
        cls.tools[name] = Tool(
            name=name,
            description=description,
            fn=fn,
            config=config,
            quality_prior=quality_prior,
            cost_estimate=cost_estimate,
        )
    
    def __init__(self, conversation_id):
        self.conversation_id = conversation_id
        self.selector = selector.BayesSelector([openaigpt])
        self.response_responders = {}

    def stream_response(self, messages, max_tokens=None, context=None):
        messages = fillin_training_end(messages, '')
        messages_to_send = [dict(message) for message in messages]

        memory_tool = self.tools.get("retrieve_memory_context")
        if memory_tool and context is not None:
            strategy = random.choice(memory_tool.config["options"]["strategy"])

            history_text = memory_tool.fn(
                messages=messages,
                context=context,
                config={
                    **memory_tool.config.get("defaults", {}),
                    "strategy": strategy,
                })

            if history_text:
                # Keep memory model-visible, but separate from core instructions.
                messages_to_send.insert(1, {
                    "role": "system",
                    "content": (
                        "The following is retrieved conversational memory. "
                        "Use it only when relevant.\n\n"
                        + history_text
                    ),
                })

        chunks = self.selector.stream_response(messages_to_send, max_tokens=max_tokens)

        response_id = str(uuid.uuid4())
        responder = self.selector.last_responder
        self.response_responders[response_id] = responder

        return StreamResponse(response_id, chunks, str(responder))

    def vote_up(self, response_id):
        responder = self.response_responders.get(response_id)
        if responder is not None:
            self.selector.successes[responder] += 1

    def vote_down(self, response_id):
        responder = self.response_responders.get(response_id)
        if responder is not None:
            self.selector.failures[responder] += 1

    # Forward-compatible async API: no background tasks in v1.
    def poll(self):
        return []

    def ongoing(self):
        return []

    def async_status(self):
        return {
            "count": 0,
            "operations": [],
        }
