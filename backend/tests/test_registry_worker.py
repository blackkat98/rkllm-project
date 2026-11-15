import asyncio

from app.engine.mock import MockBackend
from app.engine.registry import param_hint, pretty_name
from app.engine.worker import EngineWorker, Job, ModelSpec, SessionHint


def test_param_hint_from_filename():
    assert param_hint("gemma-3-1b-it-rk3588-w8a8-opt-1-hybrid-ratio-0.0.rkllm") == 1
    assert param_hint("Qwen2.5-1.5B-Instruct-rk3588.rkllm") == 1.5
    assert param_hint("DeepSeek-R1-Distill-Qwen-1.5B_W8A8_RK3588.rkllm") == 1.5
    assert param_hint("Llama-3.1-8B-Instruct.rkllm") == 8
    assert param_hint("no-size-here-rk3588-w8a8.rkllm") is None


def test_pretty_name():
    assert pretty_name("gemma-3-1b-it-rk3588-w8a8-opt-1-hybrid-ratio-0.0.rkllm") == "gemma 3 1b it"


async def test_scan_statuses(admin):
    models = {m["filename"]: m for m in (await admin.get("/api/admin/models")).json()}
    big = models["llama-3.1-8b-instruct-rk3588-w8a8.rkllm"]
    assert big["status"] == "too_large"
    assert any("8B" in w for w in big["warnings"])
    r = await admin.patch(f"/api/admin/models/{big['id']}", json={"enabled": True})
    assert r.status_code == 400
    gemma = models["gemma-3-1b-it-rk3588-w8a8-opt-1-hybrid-ratio-0.0.rkllm"]
    assert gemma["status"] == "ok" and gemma["family"] == "gemma" and gemma["enabled"] is False


def spec(i=1, **kw):
    return ModelSpec(id=i, path=f"/models/m{i}.rkllm", display_name=f"m{i}", family="chatml",
                     max_context_len=4096, max_new_tokens=512, **kw)


async def collect(worker, job):
    return [e async for e in worker.stream(job)]


async def test_worker_kv_fast_path_and_invalidation():
    backend = MockBackend(token_delay=0, load_seconds=0)
    w = EngineWorker(backend, kv_fast_path=True)
    w.start()
    try:
        s = spec()
        h1 = SessionHint("conv", None, 10, 50, 0)
        ev = await collect(w, Job(kind="chat", model=s, prompt="FULL1", session=h1))
        assert ev[-1][0] == "done" and ev[-1][1]["used_kv_cache"] is False
        assert any(e[0] == "loading_model" for e in ev)

        h2 = SessionHint("conv", 10, 11, 80, 10)
        ev = await collect(w, Job(kind="chat", model=s, prompt="FULL2", incremental_prompt="INC2", session=h2))
        assert ev[-1][1]["used_kv_cache"] is True
        assert backend.history[-1]["prompt"] == "INC2" and backend.history[-1]["keep_history"] is True

        # a different conversation invalidates the hot session
        ev = await collect(w, Job(kind="chat", model=s, prompt="OTHER", session=SessionHint("other", None, 20, 30, 0)))
        h3 = SessionHint("conv", 11, 12, 90, 10)
        ev = await collect(w, Job(kind="chat", model=s, prompt="FULL3", incremental_prompt="INC3", session=h3))
        assert ev[-1][1]["used_kv_cache"] is False
        assert backend.history[-1]["prompt"] == "FULL3"
    finally:
        w.stop()


async def test_worker_queue_positions_and_cancel():
    backend = MockBackend(token_delay=0.01, load_seconds=0)
    w = EngineWorker(backend)
    w.start()
    try:
        s = spec()
        q1 = w.submit(Job(kind="openai", model=s, prompt="a"))
        j2 = Job(kind="openai", model=s, prompt="b")
        q2 = w.submit(j2)
        first = await asyncio.wait_for(q2.get(), 2)
        assert first == ("queued", {"ahead": 1}) or first[0] == "queued"
        w.cancel(j2)
        while True:
            ev, data = await asyncio.wait_for(q2.get(), 2)
            if ev == "done":
                assert data["aborted"] is True
                break
        while (await asyncio.wait_for(q1.get(), 5))[0] != "done":
            pass
    finally:
        w.stop()


async def test_worker_ram_guard_disables_model():
    backend = MockBackend(token_delay=0, load_seconds=0)
    w = EngineWorker(backend, max_model_ram_mb=-1)  # any measurement exceeds the limit
    seen = []

    async def hook(model_id, ram_mb, over):
        seen.append((model_id, ram_mb, over))

    w.on_model_loaded = hook
    w.start()
    try:
        ev = await collect(w, Job(kind="openai", model=spec(7), prompt="x"))
        await asyncio.sleep(0.05)
        if seen and seen[0][1] is not None:  # /proc available (Linux)
            assert ev[-1][0] == "error" and "disabled" in ev[-1][1]["message"]
            assert seen[0][0] == 7 and seen[0][2] is True
            assert not backend.loaded
    finally:
        w.stop()
