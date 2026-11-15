"""Generation orchestration.

A Generation runs as an asyncio task decoupled from the HTTP request: if the browser
disconnects, the answer is still produced and saved, and a reloaded page can re-attach
(GET /conversations/{id}/stream). Events are fanned out to every subscriber.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select, update

from app.config import Settings
from app.db import session_factory, utcnow
from app.engine.registry import to_spec
from app.engine.templates import get_template, strip_think
from app.engine.worker import PRIORITY_BACKGROUND, EngineWorker, Job, SessionHint
from app.memory.context import HistoryItem, plan_context
from app.memory.summarizer import chunk_for_summary, clean_title, summary_prompt, title_prompt
from app.memory.tokens import TokenCounter
from app.models import AppSettings, Conversation, LLMModel, Message, User

log = logging.getLogger(__name__)

RELAYED = {"queued", "loading_model", "started"}


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


def message_dict(m: Message) -> dict:
    return {
        "id": m.id, "seq": m.seq, "role": m.role, "content": m.content, "model_id": m.model_id,
        "status": m.status, "error": m.error, "prompt_tokens": m.prompt_tokens,
        "completion_tokens": m.completion_tokens, "tok_per_s": m.tok_per_s,
        "used_kv_cache": m.used_kv_cache, "created_at": m.created_at,
    }


@dataclass
class Generation:
    conversation_id: uuid.UUID
    user_id: int
    assistant_message_id: int
    user_message_id: int
    model_id: int
    prev_state: int | None
    content: str = ""
    phase: str = "queued"
    job: Job | None = None
    stopped: bool = False
    finished: bool = False
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    task: asyncio.Task | None = None

    def publish(self, event: str, data: dict) -> None:
        for q in list(self.subscribers):
            q.put_nowait((event, data))

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        q.put_nowait(("snapshot", {
            "assistant_message_id": self.assistant_message_id,
            "content": self.content,
            "phase": self.phase,
        }))
        if self.finished:
            q.put_nowait(("end", {}))
        self.subscribers.add(q)
        return q


class ChatService:
    def __init__(self, worker: EngineWorker, settings: Settings):
        self.worker = worker
        self.settings = settings
        self.active: dict[uuid.UUID, Generation] = {}
        self.title_tasks: dict[uuid.UUID, asyncio.Task] = {}

    # ------------------------------------------------------------------ helpers
    def counter_for(self, model: LLMModel) -> TokenCounter:
        tok = str(Path(self.settings.models_dir) / model.tokenizer_path) if model.tokenizer_path else None
        return TokenCounter(self.settings.chars_per_token, tok)

    def is_generating(self, conversation_id: uuid.UUID) -> bool:
        return conversation_id in self.active

    def start(self, gen: Generation) -> Generation:
        self.active[gen.conversation_id] = gen
        gen.task = asyncio.create_task(self._run(gen), name=f"gen-{gen.conversation_id}")
        return gen

    def stop(self, conversation_id: uuid.UUID) -> bool:
        gen = self.active.get(conversation_id)
        if not gen:
            return False
        gen.stopped = True
        if gen.job:
            self.worker.cancel(gen.job)
        return True

    async def stream(self, gen: Generation, first: list[tuple[str, dict]] | None = None):
        """Async generator of SSE frames for one subscriber."""
        q = gen.subscribe()
        try:
            for ev, data in first or []:
                yield sse(ev, data)
            while True:
                try:
                    ev, data = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                if ev == "end":
                    return
                yield sse(ev, data)
        finally:
            gen.subscribers.discard(q)

    async def _relay(self, gen: Generation, job: Job, collect: bool) -> tuple[str, dict, str | None]:
        """Run a worker job, relaying status events; returns (text, done_data, error)."""
        gen.job = job
        parts: list[str] = []
        try:
            async for ev, data in self.worker.stream(job):
                if ev in RELAYED:
                    if ev != "started" or collect:
                        gen.phase = ev
                        gen.publish(ev, data)
                elif ev == "token":
                    parts.append(data["text"])
                    if collect:
                        gen.content += data["text"]
                        gen.phase = "streaming"
                        gen.publish("token", {"t": data["text"]})
                elif ev == "error":
                    return "".join(parts), {}, data.get("message", "Generation failed")
                elif ev == "done":
                    return "".join(parts), data, None
        finally:
            gen.job = None
        return "".join(parts), {}, "Generation ended unexpectedly"

    # ------------------------------------------------------------------ main flow
    async def _run(self, gen: Generation) -> None:
        sm = session_factory()
        try:
            async with sm() as s:
                conv = await s.get(Conversation, gen.conversation_id)
                user = await s.get(User, gen.user_id)
                model = await s.get(LLMModel, gen.model_id)
                app_settings = await s.get(AppSettings, 1)
                assistant = await s.get(Message, gen.assistant_message_id)
                user_msg = await s.get(Message, gen.user_message_id)
                assert conv and user and model and assistant and user_msg

                spec = to_spec(model, self.settings)
                template = get_template(model.family)
                counter = self.counter_for(model)
                sys_parts = [
                    app_settings.global_system_prompt if app_settings else None,
                    user.custom_instructions,
                    conv.system_prompt,
                ]

                plan = None
                for _ in range(4):  # summarise in rounds if needed (tier 2)
                    rows = (await s.execute(
                        select(Message)
                        .where(Message.conversation_id == conv.id,
                               Message.seq > conv.summary_upto_seq,
                               Message.seq < assistant.seq)
                        .order_by(Message.seq)
                    )).scalars().all()
                    history = [
                        HistoryItem(m.seq, m.role, m.content) for m in rows
                        if m.role == "user" or (m.role == "assistant" and m.status in ("complete", "aborted") and m.content.strip())
                    ]
                    plan = plan_context(
                        system_without_summary=sys_parts,
                        summary=conv.summary,
                        history=history,
                        max_context=model.max_context_len,
                        generation_reserve=spec.generation_reserve,
                        counter=counter,
                        trigger_ratio=self.settings.summary_trigger_ratio,
                        target_ratio=self.settings.summary_target_ratio,
                        keep_recent=self.settings.keep_recent_messages,
                    )
                    if not plan.to_fold:
                        break
                    gen.phase = "summarizing"
                    gen.publish("summarizing", {"messages": len(plan.to_fold)})
                    summary = conv.summary
                    max_chunk = int(model.max_context_len * 0.5)
                    for chunk in chunk_for_summary(plan.to_fold, max_chunk, counter):
                        if gen.stopped:
                            break
                        prompt = summary_prompt(
                            model.family, summary, chunk,
                            max_chars=int(model.max_context_len * 0.25 * self.settings.chars_per_token),
                        )
                        text, _, err = await self._relay(gen, Job(kind="summary", model=spec, prompt=prompt), collect=False)
                        if err:
                            raise RuntimeError(f"Summarisation failed: {err}")
                        summary = strip_think(text).strip() or summary
                    if gen.stopped:
                        break
                    conv.summary = summary
                    conv.summary_upto_seq = plan.to_fold[-1].seq
                    await s.commit()
                    gen.prev_state = None  # history representation changed -> replay

                if gen.stopped or plan is None:
                    assistant.status = "aborted"
                    await s.commit()
                    gen.publish("done", {"message": message_dict(assistant), "stats": {"aborted": True}})
                    return

                full = template.render(plan.system, plan.messages)
                incremental = template.continuation(user_msg.content) if gen.prev_state else None
                hint = SessionHint(
                    conversation_id=str(conv.id),
                    prev_state=gen.prev_state,
                    next_state=assistant.id,
                    est_full_tokens=plan.est_tokens - spec.generation_reserve,
                    est_incremental_tokens=counter.count(incremental or ""),
                )
                job = Job(kind="chat", model=spec, prompt=full, incremental_prompt=incremental, session=hint)
                _, done, err = await self._relay(gen, job, collect=True)

                assistant.content = gen.content
                assistant.model_id = model.id
                assistant.prompt_tokens = hint.est_full_tokens
                if err:
                    assistant.status = "error"
                    assistant.error = err
                else:
                    assistant.status = "aborted" if done.get("aborted") else "complete"
                    assistant.completion_tokens = done.get("tokens")
                    assistant.tok_per_s = done.get("tok_per_s")
                    assistant.used_kv_cache = bool(done.get("used_kv_cache"))
                conv.updated_at = utcnow()
                conv.model_id = model.id
                await s.commit()

                if err:
                    gen.publish("error", {"message": err, "message_obj": message_dict(assistant)})
                else:
                    gen.publish("done", {"message": message_dict(assistant), "stats": done})

                needs_title = (
                    not conv.title_generated
                    and (app_settings is None or app_settings.auto_title)
                    and assistant.status == "complete"
                )
                if needs_title:
                    self.title_tasks[conv.id] = asyncio.create_task(
                        self._make_title(conv.id, spec, model.family, user_msg.content, assistant.content)
                    )
        except Exception as e:
            log.exception("generation failed")
            try:
                async with sm() as s:
                    m = await s.get(Message, gen.assistant_message_id)
                    if m:
                        m.status, m.error, m.content = "error", str(e), gen.content
                        await s.commit()
                        gen.publish("error", {"message": str(e), "message_obj": message_dict(m)})
            except Exception:
                log.exception("could not persist generation error")
        finally:
            gen.finished = True
            gen.publish("end", {})
            self.active.pop(gen.conversation_id, None)

    async def _make_title(self, conversation_id: uuid.UUID, spec, family: str, user_text: str, assistant_text: str) -> str | None:
        try:
            job = Job(kind="title", model=spec, prompt=title_prompt(family, user_text, assistant_text),
                      priority=PRIORITY_BACKGROUND, only_if_loaded=True)
            text, _ = await self.worker.run_to_text(job)
            async with session_factory()() as s:
                conv = await s.get(Conversation, conversation_id)
                if not conv:
                    return None
                conv.title = clean_title(text, conv.title)
                conv.title_generated = True
                await s.commit()
                return conv.title
        except Exception:
            log.exception("title generation failed")
            return None
        finally:
            self.title_tasks.pop(conversation_id, None)


async def mark_interrupted_messages() -> int:
    async with session_factory()() as s:
        res = await s.execute(
            update(Message)
            .where(Message.status == "streaming")
            .values(status="error", error="Interrupted (server restarted)")
        )
        await s.commit()
        return res.rowcount or 0
