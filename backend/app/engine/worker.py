"""Single NPU worker.

The RK3588 NPU can only run one generation at a time and an 8 GB board can only hold one
model, so one dedicated thread owns the backend. Async request handlers submit Jobs and
consume their events through an asyncio.Queue.

Tier-3 memory (KV-cache fast path) lives here: the worker remembers which conversation's
history is currently in the NPU KV cache ("hot" session). If the next chat job continues
exactly that conversation, only the new user turn is sent with keep_history=1; otherwise
the cache is cleared and the full prompt (tier 1/2) is replayed.
"""

import asyncio
import itertools
import logging
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

from app.engine.base import Backend, LoadParams

log = logging.getLogger(__name__)

PRIORITY_INTERACTIVE = 0
PRIORITY_BACKGROUND = 1


@dataclass
class ModelSpec:
    id: int
    path: str
    display_name: str
    family: str
    max_context_len: int
    max_new_tokens: int
    sampling: dict = field(default_factory=dict)
    keep_loaded: bool = False
    est_ram_mb: int | None = None  # pre-load estimate, used by the free-RAM check

    def load_params(self, cpu_mask: int, cpu_num: int) -> LoadParams:
        return LoadParams.from_sampling(
            self.path, self.max_context_len, self.max_new_tokens, self.sampling,
            cpu_mask=cpu_mask, cpu_num=cpu_num,
        )

    @property
    def generation_reserve(self) -> int:
        return min(self.max_new_tokens, self.max_context_len // 4)


@dataclass
class SessionHint:
    conversation_id: str
    prev_state: int | None  # id of the assistant message the KV cache must end with
    next_state: int  # id of the assistant message being generated now
    est_full_tokens: int  # estimated tokens of the full prompt
    est_incremental_tokens: int  # estimated tokens of the continuation prompt


@dataclass
class _Hot:
    model_id: int
    conversation_id: str
    state: int
    tokens: int  # estimated tokens currently held in the KV cache


_ids = itertools.count(1)


@dataclass
class Job:
    kind: str  # chat | summary | title | openai | preload
    model: ModelSpec
    prompt: str = ""
    incremental_prompt: str | None = None
    session: SessionHint | None = None
    priority: int = PRIORITY_INTERACTIVE
    only_if_loaded: bool = False  # background jobs must not trigger a model swap
    id: int = field(default_factory=lambda: next(_ids))
    cancelled: bool = False
    _loop: asyncio.AbstractEventLoop | None = None
    _events: asyncio.Queue | None = None
    _last_ahead: int | None = None

    def emit(self, type_: str, **data) -> None:
        if self._loop and self._events is not None:
            self._loop.call_soon_threadsafe(self._events.put_nowait, (type_, data))


TERMINAL = {"done", "error"}

ModelLoadedHook = Callable[[int, int | None, bool], Awaitable[None]]


def _meminfo_available_mb() -> int | None:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


def _rss_mb() -> int | None:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


class EngineWorker:
    def __init__(
        self,
        backend: Backend,
        *,
        cpu_mask: int = 0,
        cpu_num: int = 4,
        max_model_ram_mb: int = 6000,
        min_free_ram_mb: int = 512,
        idle_unload_minutes: int = 0,
        kv_fast_path: bool = True,
    ):
        self.backend = backend
        self.cpu_mask = cpu_mask
        self.cpu_num = cpu_num
        self.max_model_ram_mb = max_model_ram_mb
        self.min_free_ram_mb = min_free_ram_mb
        self.idle_unload_minutes = idle_unload_minutes
        self.kv_fast_path = kv_fast_path

        self._pending: list[Job] = []
        self._cond = threading.Condition()
        self._current: Job | None = None
        self._loaded: ModelSpec | None = None
        self._hot: _Hot | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_activity = time.monotonic()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.on_model_loaded: ModelLoadedHook | None = None

    # ------------------------------------------------------------------ lifecycle
    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._loop = loop or asyncio.get_running_loop()
        self._running = True
        self._thread = threading.Thread(target=self._run, name="npu-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._running = False
            for job in self._pending:
                job.emit("error", message="Server shutting down")
            self._pending.clear()
            self._cond.notify_all()
        if self._current:
            self.backend.abort()
        if self._thread:
            self._thread.join(timeout=10)
        try:
            self.backend.unload()
        except Exception:
            log.exception("unload failed")

    # ------------------------------------------------------------------ public async API
    def submit(self, job: Job) -> asyncio.Queue:
        job._loop = asyncio.get_running_loop()
        job._events = asyncio.Queue()
        with self._cond:
            self._pending.append(job)
            self._pending.sort(key=lambda j: (j.priority, j.id))
            self._notify_positions()
            self._cond.notify_all()
        return job._events

    async def stream(self, job: Job) -> AsyncIterator[tuple[str, dict]]:
        """Submit and yield (event, data) until a terminal event. Cancels the job if the
        consumer stops iterating early."""
        events = self.submit(job)
        finished = False
        try:
            while True:
                type_, data = await events.get()
                yield type_, data
                if type_ in TERMINAL:
                    finished = True
                    return
        finally:
            if not finished:
                self.cancel(job)

    async def run_to_text(self, job: Job) -> tuple[str, dict]:
        """Convenience for background jobs: returns (text, done_data); raises on error."""
        parts: list[str] = []
        async for type_, data in self.stream(job):
            if type_ == "token":
                parts.append(data["text"])
            elif type_ == "error":
                raise RuntimeError(data.get("message", "generation failed"))
            elif type_ == "done":
                return "".join(parts), data
        return "".join(parts), {}

    def cancel(self, job: Job) -> None:
        with self._cond:
            job.cancelled = True
            if job in self._pending:
                self._pending.remove(job)
                job.emit("done", aborted=True, tokens=0, seconds=0.0, tok_per_s=None, used_kv_cache=False)
                self._notify_positions()
                return
        if self._current is job:
            self.backend.abort()

    def unload_now(self) -> bool:
        """Admin action: unload the model if the NPU is idle."""
        with self._cond:
            if self._current or self._pending:
                return False
            self._pending.append(Job(kind="unload", model=None, priority=PRIORITY_BACKGROUND))  # type: ignore[arg-type]
            self._cond.notify_all()
        return True

    def status(self) -> dict:
        cur = self._current
        return {
            "loaded_model_id": self._loaded.id if self._loaded else None,
            "loaded_model_name": self._loaded.display_name if self._loaded else None,
            "busy": cur is not None,
            "current_kind": cur.kind if cur else None,
            "queue_length": len(self._pending),
            "hot_conversation_id": self._hot.conversation_id if self._hot else None,
        }

    @property
    def loaded_model_id(self) -> int | None:
        return self._loaded.id if self._loaded else None

    # ------------------------------------------------------------------ thread
    def _notify_positions(self) -> None:
        busy = 1 if self._current else 0
        for i, job in enumerate(self._pending):
            ahead = i + busy
            if job._last_ahead != ahead:
                job._last_ahead = ahead
                job.emit("queued", ahead=ahead)

    def _next_job(self) -> Job | None:
        with self._cond:
            while self._running and not self._pending:
                timeout = None
                if self.idle_unload_minutes > 0 and self._loaded and not self._loaded.keep_loaded:
                    remaining = self.idle_unload_minutes * 60 - (time.monotonic() - self._last_activity)
                    if remaining <= 0:
                        self._unload()
                        continue
                    timeout = remaining
                self._cond.wait(timeout=timeout)
            if not self._running:
                return None
            job = self._pending.pop(0)
            self._current = job
            self._notify_positions()
            return job

    def _run(self) -> None:
        while True:
            job = self._next_job()
            if job is None:
                return
            try:
                self._process(job)
            except Exception as e:  # keep the worker alive no matter what
                log.exception("job %s failed", job.id)
                self._hot = None
                job.emit("error", message=f"Engine error: {e}")
            finally:
                with self._cond:
                    self._current = None
                    self._last_activity = time.monotonic()
                    self._notify_positions()

    def _unload(self) -> None:
        if self._loaded:
            log.info("unloading %s", self._loaded.display_name)
        self.backend.unload()
        self._loaded = None
        self._hot = None

    def _ensure_model(self, job: Job) -> bool:
        spec = job.model
        if self._loaded and self._loaded.id == spec.id and self._loaded.sampling == spec.sampling \
                and self._loaded.max_context_len == spec.max_context_len \
                and self._loaded.max_new_tokens == spec.max_new_tokens and self.backend.loaded:
            return True
        job.emit("loading_model", model_id=spec.id, model=spec.display_name)
        # always free the previous model first: two models never fit in 8 GB
        self._unload()
        avail_before, rss_before = _meminfo_available_mb(), _rss_mb()
        # a 4B model needs ~5-6 GB: fail cleanly instead of getting OOM-killed. Not sticky:
        # free memory depends on what else runs on the board, so the model stays enabled.
        if avail_before is not None and spec.est_ram_mb \
                and avail_before < spec.est_ram_mb + self.min_free_ram_mb:
            job.emit(
                "error",
                message=f"Not enough free RAM to load {spec.display_name}: ~{spec.est_ram_mb} MB needed "
                f"(+{self.min_free_ram_mb} MB headroom), {avail_before} MB available. Free memory "
                "(stop other services or lower the context length) and try again.",
            )
            return False
        try:
            self.backend.load(spec.load_params(self.cpu_mask, self.cpu_num))
        except Exception as e:
            log.exception("load failed")
            job.emit("error", message=f"Failed to load model {spec.display_name}: {e}")
            return False
        ram_mb = None
        avail_after, rss_after = _meminfo_available_mb(), _rss_mb()
        deltas = []
        if avail_before is not None and avail_after is not None:
            deltas.append(avail_before - avail_after)  # catches DMA/NPU buffers outside RSS
        if rss_before is not None and rss_after is not None:
            deltas.append(rss_after - rss_before)
        if deltas:
            ram_mb = max(0, max(deltas))
        over = ram_mb is not None and ram_mb > self.max_model_ram_mb
        self._fire_loaded_hook(spec.id, ram_mb, over)
        if over:
            self.backend.unload()
            job.emit(
                "error",
                message=f"{spec.display_name} uses ~{ram_mb} MB RAM, above the {self.max_model_ram_mb} MB "
                "limit for this board. It has been disabled.",
            )
            return False
        self._loaded = spec
        self._hot = None
        return True

    def _fire_loaded_hook(self, model_id: int, ram_mb: int | None, over: bool) -> None:
        if self.on_model_loaded and self._loop:
            asyncio.run_coroutine_threadsafe(self.on_model_loaded(model_id, ram_mb, over), self._loop)

    def _process(self, job: Job) -> None:
        if job.kind == "unload":
            self._unload()
            return
        if job.cancelled:
            job.emit("done", aborted=True, tokens=0, seconds=0.0, tok_per_s=None, used_kv_cache=False)
            return
        if job.only_if_loaded and (not self._loaded or self._loaded.id != job.model.id):
            job.emit("error", message="skipped: model not loaded")
            return
        if not self._ensure_model(job):
            return
        if job.kind == "preload":
            job.emit("done", aborted=False, tokens=0, seconds=0.0, tok_per_s=None, used_kv_cache=False)
            return

        spec = job.model
        s = job.session
        use_incremental = False
        if self.kv_fast_path and s and job.incremental_prompt is not None and self._hot:
            h = self._hot
            fits = h.tokens + s.est_incremental_tokens + spec.generation_reserve <= int(spec.max_context_len * 0.9)
            use_incremental = (
                h.model_id == spec.id
                and h.conversation_id == s.conversation_id
                and s.prev_state is not None
                and h.state == s.prev_state
                and fits
            )

        keep_history = bool(self.kv_fast_path and s is not None)
        if use_incremental:
            prompt = job.incremental_prompt or ""
            base_tokens = self._hot.tokens + (s.est_incremental_tokens if s else 0)
        else:
            self.backend.clear_kv()
            prompt = job.prompt
            base_tokens = s.est_full_tokens if s else 0
        self._hot = None  # invalid until this run completes successfully

        job.emit("started", used_kv_cache=use_incremental)
        t0 = time.monotonic()
        first_token_at: list[float] = []

        def on_token(text: str) -> None:
            if not first_token_at:
                first_token_at.append(time.monotonic())
            job.emit("token", text=text)

        result = self.backend.generate(prompt, keep_history=keep_history, on_token=on_token, hint=job.kind)
        elapsed = time.monotonic() - t0
        gen_time = elapsed - ((first_token_at[0] - t0) if first_token_at else 0)
        tok_per_s = round(result.tokens / gen_time, 2) if result.tokens and gen_time > 0 else None

        if result.error:
            job.emit("error", message=result.error)
            return
        if keep_history and s and not result.aborted:
            self._hot = _Hot(spec.id, s.conversation_id, s.next_state, base_tokens + result.tokens)
        job.emit(
            "done",
            aborted=result.aborted,
            tokens=result.tokens,
            seconds=round(elapsed, 2),
            ttft=round(first_token_at[0] - t0, 2) if first_token_at else None,
            tok_per_s=tok_per_s,
            used_kv_cache=use_incremental,
        )
