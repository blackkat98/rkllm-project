"""Prompts for tier-2 rolling summaries and auto titles."""

from app.engine.templates import Msg, get_template, strip_think
from app.memory.context import HistoryItem
from app.memory.tokens import TokenCounter

SUMMARY_INSTRUCTIONS = (
    "You maintain a running memory of a chat between a user and an AI assistant. "
    "Merge the existing summary with the new messages into one concise summary (at most 200 words). "
    "Keep facts about the user, decisions, names, numbers, code identifiers and open questions. "
    "Write in the same language the user writes in. Output only the summary."
)

TITLE_INSTRUCTIONS = (
    "Write a short title (2 to 6 words) for this conversation, in the user's language. "
    "Output only the title, no quotes, no punctuation at the end."
)


def chunk_for_summary(items: list[HistoryItem], max_tokens: int, counter: TokenCounter) -> list[list[HistoryItem]]:
    chunks: list[list[HistoryItem]] = [[]]
    used = 0
    for it in items:
        n = counter.count_message(it.content)
        if chunks[-1] and used + n > max_tokens:
            chunks.append([])
            used = 0
        chunks[-1].append(it)
        used += n
    return [c for c in chunks if c]


def summary_prompt(family: str, previous_summary: str | None, items: list[HistoryItem], max_chars: int) -> str:
    lines = []
    for it in items:
        content = strip_think(it.content) if it.role == "assistant" else it.content
        if len(content) > max_chars:
            content = content[: max_chars // 2] + " … " + content[-max_chars // 2 :]
        lines.append(f"{it.role.upper()}: {content}")
    body = (
        f"Existing summary:\n{previous_summary or '(none)'}\n\n"
        f"New messages:\n" + "\n".join(lines) + "\n\nUpdated summary:"
    )
    return get_template(family).render(SUMMARY_INSTRUCTIONS, [Msg("user", body)])


def title_prompt(family: str, user_text: str, assistant_text: str) -> str:
    body = (
        f"USER: {user_text[:600]}\nASSISTANT: {strip_think(assistant_text)[:600]}\n\n"
        "Title:"
    )
    return get_template(family).render(TITLE_INSTRUCTIONS, [Msg("user", body)])


def clean_title(raw: str, fallback: str) -> str:
    t = strip_think(raw).strip().splitlines()[0] if strip_think(raw).strip() else ""
    t = t.strip().strip('"\'“”‘’*#').removeprefix("Title:").strip().rstrip(".")
    return (t or fallback)[:80]


def fallback_title(user_text: str) -> str:
    words = user_text.strip().split()
    t = " ".join(words[:8])
    return (t[:60] + "…") if len(t) > 60 else (t or "New chat")
