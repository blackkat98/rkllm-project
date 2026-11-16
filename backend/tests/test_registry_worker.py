import asyncio

from app.engine.mock import MockBackend
from app.engine.registry import estimate_ram_mb_from, param_hint, pretty_name
from app.engine.worker import EngineWorker, Job, ModelSpec, SessionHint


def test_param_hint_from_filename():
    assert param_hint("gemma-3-1b-it-rk3588-w8a8-opt-1-hybrid-ratio-0.0.rkllm") == 1
    assert param_hint("Qwen2.5-1.5B-Instruct-rk3588.rkllm") == 1.5
    assert param_hint("DeepSeek-R1-Distill-Qwen-1.5B_W8A8_RK3588.rkllm") == 1.5
    assert param_hint("Llama-3.1-8B-Instruct.rkllm") == 8
    assert param_hint("Qwen3-4B-rk3588-w8a8.rkllm") == 4
    assert param_hint("Phi-3.5-mini-instruct-3.8B-rk3588-w8a8.rkllm") == 3.8
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
    qwen4 = models["qwen3-4b-rk3588-w8a8.rkllm"]
    assert qwen4["status"] == "ok" and qwen4["param_hint_b"] == 4
    assert not any("parameters (policy" in w for w in qwen4["warnings"])


async def test_model_policy(admin):
    p = (await admin.get("/api/admin/model-policy")).json()
    assert p["max_param_b"] == 4 and p["max_ram_mb"] == 6000 and p["min_free_ram_mb"] == 512


def test_estimate_ram_scales_with_model_size():
    small = estimate_ram_mb_from(int(1.8e9), 1.5, 4096)
    big = estimate_ram_mb_from(int(4.7e9), 4, 4096)
    kv_small = small - int(1.8e9 / 1024**2 * 1.08 + 150)
    kv_big = big - int(4.7e9 / 1024**2 * 1.08 + 150)
    assert kv_big > 2 * kv_small
    assert 5000 < big < 6000
    # no filename hint: parameters are inferred from the file size
    assert estimate_ram_mb_from(int(4.7e9), None, 4096) > estimate_ram_mb_from(int(1.8e9), None, 4096)


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


async def test_worker_free_ram_check_refuses_load(monkeypatch):
    import app.engine.worker as worker_mod

    monkeypatch.setattr(worker_mod, "_meminfo_available_mb", lambda: 1000)
    backend = MockBackend(token_delay=0, load_seconds=0)
    w = EngineWorker(backend, min_free_ram_mb=512)
    seen = []

    async def hook(model_id, ram_mb, over):
        seen.append((model_id, ram_mb, over))

    w.on_model_loaded = hook
    w.start()
    try:
        ev = await collect(w, Job(kind="openai", model=spec(9, est_ram_mb=5000), prompt="x"))
        await asyncio.sleep(0.05)
        assert ev[-1][0] == "error" and "Not enough free RAM" in ev[-1][1]["message"]
        assert not backend.loaded
        assert seen == []  # not flagged over_ram: the model stays enabled
        # a model that fits loads normally
        ev = await collect(w, Job(kind="openai", model=spec(10, est_ram_mb=300), prompt="x"))
        assert ev[-1][0] == "done"
    finally:
        w.stop()
