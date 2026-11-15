"""Builds the prompt for a conversation within the model's context window.

Tier 1 - replay: the whole saved history is re-rendered with the model's template.
Tier 2 - rolling summary: when the prompt would exceed `trigger_ratio` of the context,
          the oldest unsummarised turns (except the latest `keep_recent`) are selected for
          folding into conversation.summary, until the rest fits under `target_ratio`.
If a few huge recent messages still overflow, their middles are elided as a last resort.
"""

from dataclasses import dataclass, field

from app.engine.templates import Msg, strip_think
from app.memory.tokens import TokenCounter


@dataclass
class HistoryItem:
    seq: int
    role: str
    content: str


@dataclass
class ContextPlan:
    system: str | None
    messages: list[Msg]
    to_fold: list[HistoryItem] = field(default_factory=list)  # needs summarisation first
    est_tokens: int = 0
    truncated: bool = False


def compose_system(
    global_prompt: str | None,
    custom_instructions: str | None,
    conversation_prompt: str | None,
    summary: str | None,
) -> str | None:
    parts = []
    if global_prompt:
        parts.append(global_prompt.strip())
    if custom_instructions:
        parts.append("User's custom instructions:\n" + custom_instructions.strip())
    if conversation_prompt:
        parts.append(conversation_prompt.strip())
    if summary:
        parts.append("Summary of the earlier part of this conversation:\n" + summary.strip())
    return "\n\n".join(parts) or None


def _elide(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    half = max(50, max_chars // 2 - 20)
    return text[:half] + "\n…[truncated]…\n" + text[-half:]


def plan_context(
    *,
    system_without_summary: list[str | None],
    summary: str | None,
    history: list[HistoryItem],
    max_context: int,
    generation_reserve: int,
    counter: TokenCounter,
    trigger_ratio: float = 0.70,
    target_ratio: float = 0.45,
    keep_recent: int = 6,
    allow_fold: bool = True,
) -> ContextPlan:
    """history: unsummarised messages (seq > summary_upto_seq), oldest first, ending with the
    newest user message."""
    g, ci, cp = system_without_summary
    items = [HistoryItem(h.seq, h.role, strip_think(h.content) if h.role == "assistant" else h.content) for h in history]

    def total(sys_text: str | None, msgs: list[HistoryItem]) -> int:
        return counter.count(sys_text or "") + sum(counter.count_message(m.content) for m in msgs) + generation_reserve

    system = compose_system(g, ci, cp, summary)
    est = total(system, items)

    to_fold: list[HistoryItem] = []
    if allow_fold and est > max_context * trigger_ratio and len(items) > keep_recent:
        target = max_context * target_ratio
        foldable = items[:-keep_recent]
        rest = items[-keep_recent:]
        # fold oldest first; always fold whole user/assistant pairs where possible
        while foldable and total(system, foldable + rest) > target:
            to_fold.append(foldable.pop(0))
            if foldable and foldable[0].role == "assistant":
                to_fold.append(foldable.pop(0))
        if to_fold:
            return ContextPlan(system=system, messages=[], to_fold=to_fold, est_tokens=est)

    # final guard: drop the oldest messages, then elide the newest one if it alone overflows
    truncated = False
    while total(system, items) > max_context and len(items) > 1:
        items.pop(0)
        truncated = True
    if items and total(system, items) > max_context:
        room = max_context - generation_reserve - counter.count(system or "") - 16
        items[-1].content = _elide(items[-1].content, max(400, int(room * counter.chars_per_token * 0.9)))
        truncated = True

    return ContextPlan(
        system=system,
        messages=[Msg(i.role, i.content) for i in items],
        est_tokens=total(system, items),
        truncated=truncated,
    )
