I have started a plan to build an abstraction around model and tool selection in my AI system. Here is the basic structure:

# Planner: Initial Full Version Notes

## Purpose

`Planner` is a simplified, chat-first abstraction over multiple LLM services/models and tools.

Given a dialogue, it selects an **execution plan**—a model and, where useful, configured tools—to maximize expected *trustworthy user utility*, balancing:

- likelihood of a positive user outcome;
- independent quality/reliability expectations;
- dollar cost;
- latency;
- uncertainty and occasional exploration.

The public API remains synchronous and simple. Async work is internal and accessed through polling.

---

## 1. Public API

### Registration

Models and tools are registered once in a shared registry.

```python
Planner.register_model(
    adapter,
    model_id="gemini-2.5-flash",
    cost_per_million_tokens=2.5,
    quality_prior=0.70,
)
```

A registered model adapter is expected to provide:

```python
adapter.chat_response(messages, max_tokens=None) -&gt; str
adapter.stream_response(messages, max_tokens=None) -&gt; Iterator[str]
adapter.allowed(tokens) -&gt; bool
```

`allowed(tokens)` supports context-window, quota, provider-health, and other availability constraints.

Tools are registered with a human/model-readable description, callable, and optional configurable parameters:

```python
Planner.register_tool(
    name="scholar_search",
    description=(
        "Perform a Google Scholar search and retrieve relevant review PDFs "
        "for information needed to answer the prompt."
    ),
    fn=scholar_search,
    config={
        "defaults": {"max_results": 5, "reviews_only": True},
        "options": {
            "max_results": [3, 5, 10],
            "reviews_only": [True, False],
            "year_from": [None, 2015, 2020],
        },
    },
    quality_prior=0.85,
    cost_estimate=0.02,
)

Planner.register_tool(
    name="image_generation",
    description="Create an image based on a prompt.",
    fn=lambda prompt, config: create_image(prompt, **config),
    config=ToolConfig(defaults={"size": "1024x1024"}),
    quality_prior=0.80,
    cost_estimate=0.04,
)
```

Tool configuration is a first-class decision variable. For memory retrieval, this includes collections, filters, $k$, score threshold, reranking, token budget, and summarization strategy.

### Conversation-level interface

```python
planner = Planner(conversation_id="...")
```

```python
response = planner.chat_response(messages, max_tokens=None)
```

```python
stream = planner.stream_response(messages, max_tokens=None)
for chunk in stream:
    ...
```

```python
planner.vote_up(response_id)
planner.vote_down(response_id)
```

Responses:

```python
@dataclass
class Response:
    id: str
    text: str
    model: str | None

@dataclass
class StreamResponse:
    id: str
    chunks: Iterator[str]
    model: str | None
```

The response ID maps feedback to the actual selected execution plan, rather than relying on a mutable `last_responder`.

### Forward-compatible async API

All top-level calls remain blocking/synchronous. No `await`, `async with`, or async-infected application code is required.

```python
planner.poll() -&gt; list
planner.ongoing() -&gt; list
planner.async_status() -&gt; dict
```

- `poll()` returns newly completed user-deliverable async updates.
- `ongoing()` returns lightweight active-work records, e.g. ID, description, status, elapsed time.
- `async_status()` returns summary counts/status for UI display.
- In the first minimal implementation these can return `[]`, `[]`, and `{"count": 0, "operations": []}`.

Later, internal workers may perform tool calls, verification, long research, image generation, monitoring, etc. Completed results are persisted to conversation state and made available through `poll()`.

---

## 2. Execution Plans / Responders

The planner should select an entire **execution plan**, not merely a model.

Initially, a `Responder` can remain the practical unit of selection:

```python
responder.chat_response(messages, max_tokens=None) -&gt; str
responder.stream_response(messages, max_tokens=None) -&gt; Iterator[str]
responder.allowed(tokens) -&gt; bool
responder.cost(prompt_tokens, completion_tokens) -&gt; float
```

Over time, a responder represents a complete plan such as:

- `gpt-5-mini`, direct response;
- Gemini Flash plus personal-memory retrieval;
- OpenAI model plus web search and citation checking;
- code-focused model plus execution/testing;
- draft model plus independent reviewer;
- model plus a specific configured tool setting.

This makes model choice, tool choice, and tool parameters jointly selectable and learnable.

To avoid a combinatorial explosion, plans should initially come from a limited set of explicit templates/families rather than arbitrary model-tool combinations.

---

## 3. Selection and Utility

The initial selector can build on `BayesSelector`.

It estimates a responder’s expected value from:

- observed thumbs-up/down outcomes;
- model/tool quality priors;
- estimated token costs;
- observed latency;
- availability constraints;
- uncertainty / limited experience.

A useful conceptual score is:

\[
U(p \mid x)
=
w_s \hat S(p,x)
+
w_q \hat Q(p,x)
-
w_c \hat C(p,x)
-
w_l \hat L(p,x)
-
w_r \hat R(p,x)
+
w_e \hat E(p,x)
\]

Where:

- $p$: execution plan / responder;
- $x$: request context and inferred task type;
- $\hat S$: predicted user satisfaction;
- $\hat Q$: independent quality estimate;
- $\hat C$: expected cost;
- $\hat L$: expected latency;
- $\hat R$: reliability/failure risk;
- $\hat E$: value of exploration under uncertainty.

For the initial version, this can be approximated by the existing weighted sampling approach:

\[
\text{weight}
\propto
\frac{\text{smoothed success probability} \times \text{quality prior}}
{\text{expected direct cost} + \text{latency converted to equivalent cost}}
\]

Latency is a **soft utility penalty**, not normally a hard budget. A slower plan may be worthwhile when it meaningfully improves quality.

`budget.chat_tokens(messages)` estimates prompt-token use. Completion-token assumptions should be configurable and eventually learned from observed completions.

Selection remains probabilistic rather than always greedy, allowing safe exploration of under-tested responders. Exploration should be constrained for high-stakes task categories.

---

## 4. Feedback, Evaluation, and Anti-Goodhart Safeguards

Thumbs are the primary chat satisfaction signal:

- `vote_up(response_id)` increments success evidence for the selected plan.
- `vote_down(response_id)` increments failure evidence.
- Feedback is attributed to the response’s recorded plan, including relevant configuration.

But thumbs must not become the sole notion of quality. A low-cost, fluent, hallucination-prone system can otherwise win despite producing less trustworthy answers.

Maintain separate evidence for:

1. **User satisfaction**: thumbs, ratings, corrections, edits, follow-up behavior.
2. **Quality**: task-specific evaluators, tests, rubric-based judging, source checks.
3. **Reliability/risk**: factuality audits, unsupported-claim rates, calibration, failure history.
4. **Cost and latency**: observed measurements, not provider estimates alone.

Each model/tool/plan begins with priors. Priors may be informed by internal offline evaluation, benchmarks, and expert judgment, but must be calibrated against actual usage.

Build and version a modest internal evaluation suite representing real work: research, coding, numerical/technical analysis, project continuity/memory, planning, writing, and source-grounded factual tasks. Use objective tests where possible.

The planner should apply stronger quality/reliability expectations to high-stakes or freshness-sensitive requests, and prefer grounding/verification plans where appropriate.

---

## 5. Learning Tool Parameters

Tool configuration is not static metadata; it is part of the plan.

Examples:

- memory retrieval: collection choice, top-$k$, threshold, reranker, context-token allowance;
- web/search: number of queries/results, recency filter, source whitelist, extraction depth;
- code: runtime environment, test strategy, timeout;
- image generation: size, style, model, iteration count;
- model configuration: temperature, reasoning budget, output contract.

The planner learns which configurations perform best for task/context classes. Initially this can be done by registering a small number of discrete configuration variants as separate responders/plans. Later it can use contextual parameter optimization.

Avoid learning arbitrary high-dimensional settings from sparse thumb data; use bounded option sets, strong defaults, and offline evaluation.

---

## 6. Internal Awareness and Dynamic Message Construction

The canonical user/assistant transcript should remain intact and auditable. Before invoking a selected plan, the planner builds an **effective message stream** by adding internal context/messages appropriate to that plan.

This is how capabilities are “loaded” only when relevant.

Examples of injected system/developer-level instructions:

- tool-specific usage instructions and result formats;
- tool availability and constraints;
- retrieved memory or research artifacts;
- source-grounding/citation requirements;
- output contracts, e.g. concise answer first, three bullets, structured JSON, word limit;
- verification requirements;
- awareness of outstanding or completed asynchronous work;
- task-specific quality standards.

For example, selecting a scholar-search plan may inject instructions about using retrieved reviews, distinguishing sources from inference, and citing claims. Selecting a memory plan may inject retrieved records and instructions to treat them as potentially stale/private context.

The planner—not the user-visible transcript—owns these internal additions. All injected context should have provenance, scope, and relevance controls to avoid irrelevant retrieval, stale information, or prompt-injection contamination.

---

## 7. Streaming

`stream_response()` mirrors `chat_response()` but returns a normal blocking iterator.

The selector chooses the responder before streaming begins. It records latency when the stream completes or fails.

If a stream fails before visible output, the selector may retry another responder. Once text has been shown to the user, it should not silently switch models; surface or log the failure instead.

Feedback for a streamed response is associated with the response ID created before the first chunk is returned.

---

## 8. State and Persistence

Learning state must ultimately be durable and shared, rather than held only in one process’s memory.

Persist at least:

- registered model/tool/plan versions;
- successes/failures and quality/risk evidence;
- observed cost, token use, latency, and failures;
- response-to-plan attribution;
- configuration performance;
- conversation state and async operation records;
- evaluation outcomes and feedback events.

Use model/tool/configuration version identifiers. Provider model behavior changes, prompts evolve, and tools are revised; past evidence should not be blindly attributed to a materially changed plan.

The initial `BayesSelector` may retain in-memory dictionaries, but its state shape should be designed for later persistence to a database or key-value store.

---

## 9. Async Direction

Async is internal infrastructure, not required in ordinary calling code.

Eventually, a selected plan may:

- launch multiple independent tools concurrently;
- wait for essential results before responding;
- return a provisional response while continuing research/verification;
- persist completed artifacts to conversation state;
- expose completed user-visible updates through `poll()`.

Async results should update explicit conversation/workspace state, not silently rewrite old messages. If an update is user-visible, it should be a new assistant message clearly linked to the originating response.

The initial full Planner can support registration and tool-aware plan selection before implementing all background execution machinery.

---

## 10. Other items

# Optional richer signals later:
planner.feedback(
    response.id,
    kind="correction",
    value="The cited paper was not actually a review article.",
)

# Inspection/debugging tool
planner.explain(response.id)
# {
#   "model": "gemini-2.5-flash",
#   "tools": [{"name": "scholar_search", "config": {"max_results": 5}}],
#   "estimated_cost_usd": 0.031,
#   "estimated_latency_s": 4.2,
#   "reason": "fresh, source-sensitive research question"
# }

# Outcomes from poll()

updates = planner.poll()

for update in updates:
    print(update.id)
    print(update.text)
    print(update.reply_to_response_id)
    print(update.kind)       # "research_update", "correction", "image", ...
    print(update.artifacts)  # optional URLs/attachments/structured outputs

# Add a durable asynchronous work layer

Distinguish these concepts:

| Concept | Meaning |
|---|---|
| **Plan** | The intended workflow selected by the policy |
| **Operation** | An individual executable unit: tool call, model call, evaluator, job |
| **Artifact** | Durable output of an operation: retrieved records, source bundle, code result, model draft |
| **Dependency** | An operation/artifact another operation needs |
| **Continuation** | Work triggered once dependencies resolve |
| **Subscription / watch** | A rule that reacts to future events or artifact completion |
| **Conversation state** | The durable, versioned state the next turn—or a later async update—can use |

A tool call should not fundamentally return “text.” It should create an operation and eventually produce typed artifacts.

---

# Represent execution as a DAG, not a serial tool loop

The policy should construct a small **workflow DAG**.

For example, a fresh factual research question might become:

```text
                 ┌─────────────────┐
                 │ memory.retrieve │
                 └────────┬────────┘
                          │
User turn ───────┬────────┴────────┐
                 │                 │
           ┌─────▼─────┐     ┌─────▼─────┐
           │ web.search│     │ task.class │
           └─────┬─────┘     └───────────┘
                 │
           ┌─────▼──────────┐
           │ source.extract │
           └─────┬──────────┘
                 │
        ┌────────▼────────┐
        │ answer.synthesis │
        └────────┬────────┘
                 │
        ┌────────▼─────────┐
        │ claim verification│
        └────────┬─────────┘
                 │
              response
```

Independent operations begin immediately and concurrently. Dependent work begins when its required artifacts are ready.

This avoids an expensive pattern where a model sequentially decides:

1. retrieve memory;
2. wait;
3. web search;
4. wait;
5. inspect sources;
6. wait;
7. write answer.

Instead, the planner can know in advance that retrieval and search are likely necessary and launch them in parallel.

# Support three response strategies: wait, provisional, and deferred

For a chat interaction, the policy should be able to choose among three patterns.

## Wait for the complete answer

Use when the expected wait is short and results are essential.

```text
User asks → run required operations concurrently → synthesize → respond once
```

Appropriate for normal retrieval, short code execution, and fast web lookups.

## Give a provisional answer, then improve it

Use when the system can offer something genuinely helpful now but a slow operation is likely to add value.

```text
User asks
  → launch slow research / computation
  → return: “My initial view is X. I’m checking Y and Z.”
  → publish update if the results materially change or strengthen the answer
```

This needs strong product discipline: do not create noisy “I found something!” follow-ups. The initial response must be clearly labelled as preliminary if material facts remain unresolved.

## Acknowledge and defer

Use when doing the work before answering would exceed the latency budget and a partial answer would be misleading.

```text
“I’ll investigate this and report back.”
```

Then persist the work and deliver a later result.

This is especially appropriate for long-running computations, document ingestion, periodic searches, multi-model audits, or anything that should continue even if the browser/client disconnects.

---

# “Drop results in” should mean state updates first, visible messages second

Completed async work should not have to wait uselessly for the next user prompt.

But there are two distinct destinations:

1. **The system’s durable conversation/workspace state**
2. **The user-visible chat stream**

Every completed operation should be eligible to update the first. Only some should update the second.

## Durable state injection

When an operation completes, write a versioned state patch:

```python
@dataclass
class StatePatch:
    scope: Literal["turn", "conversation", "project", "user_memory"]
    target_id: str
    patch: list[JsonPatchOp]
    provenance: Provenance
    confidence: float
    write_policy: Literal["append", "replace", "propose_for_review"]
```

For example, a retrieval process might add:

```json
{
  "scope": "conversation",
  "patch": [
    {
      "op": "add",
      "path": "/working_artifacts/research/2026-08-12/sources",
      "value": {
        "artifact_id": "art_123",
        "summary": "Five primary sources on ...",
        "status": "ready"
      }
    }
  ]
}
```

The next model invocation automatically sees relevant ready artifacts through the context assembler.

This is what I would mean by “drop results into the conversation”: **put them into an explicit state/artifact layer associated with the conversation**, not silently splice arbitrary new text into the immutable transcript.

Why avoid transcript mutation?

- It destroys a clean audit trail.
- It can confuse models about who said what and when.
- It makes stale results look current.
- It creates prompt-injection and provenance problems.
- It can overwrite or conflict with newer user intent.

Instead, preserve an append-only event history and construct the model’s context from:

```text
- canonical user/assistant transcript
- current task state
- eligible completed artifacts
- active plans / outstanding operations
- selected durable memories
```

## User-visible asynchronous updates

A result can create a visible assistant follow-up only under an explicit **delivery policy**.

```python
@dataclass
class DeliveryPolicy:
    mode: Literal[
        "never",
        "on_material_result",
        "on_completion",
        "on_user_request",
        "digest"
    ]
    materiality_threshold: float
    quiet_hours: TimeWindow | None
    require_user_opt_in: bool
    max_updates_per_conversation: int
```

For example:

- **Never**: background retrieval that merely prepares later context.
- **On material result**: a fact-check contradicts a preliminary answer.
- **On completion**: user explicitly asked “research this and get back to me.”
- **Digest**: a recurring watch/search sends one consolidated update daily or weekly.
- **On user request**: work completes silently, but is ready the moment the user asks.

A visible update should be an ordinary new assistant message with an explicit relationship to the originating turn:

```python
@dataclass
class AsyncAssistantMessage:
    reply_to_turn_id: str
    operation_ids: list[str]
    artifact_ids: list[str]
    message: str
    reason_for_delivery: str
    provisional_answer_superseded: bool
```

For example:

&gt; **Update to my earlier answer:** I checked the primary sources, and one point needs correction: …  
&gt; The rest of the recommendation still stands.

That is much safer and more legible than silently rewriting the earlier response.

---

# Add an event bus and a state reducer

Introduce an append-only event log plus workers.

```text
Chat/API/UI
    │
    ▼
Task creation ──► Policy/planner ──► Workflow DAG
    │                                      │
    ▼                                      ▼
Event log ◄──────── operation workers / tool adapters
    │
    ├── State reducer ──► conversation/project/user state
    ├── Context indexer ─► artifacts available to future model calls
    ├── Continuation scheduler
    ├── Delivery service ─► chat websocket / notification / email
    └── Learning logger ─► policy-training dataset
```

## Additional notes:

 - Under some conditions, the plan should be revised, but the delay
   associated with that should be included in the eventual evaluation
   of the original plan.
   
 - The entire process should be auditable, temporarily keeping track
   of full tool results, but permanently keeping track of "source
   materials": the exact excerpts from tool results that matter to the
   final responses.
