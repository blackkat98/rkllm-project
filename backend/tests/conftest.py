import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="rkllm-tests-"))
MODELS = _tmp / "models"
MODELS.mkdir()
# small fake model files; the size cap is lowered so "too large" can be tested cheaply
(MODELS / "qwen2.5-1.5b-instruct-rk3588-w8a8.rkllm").write_bytes(b"\0" * 2048)
(MODELS / "gemma-3-1b-it-rk3588-w8a8-opt-1-hybrid-ratio-0.0.rkllm").write_bytes(b"\0" * 1024)
with open(MODELS / "llama-3.1-8b-instruct-rk3588-w8a8.rkllm", "wb") as f:
    f.truncate(3 * 1024 * 1024)  # 3 MB > 0.002 GB cap

os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{(_tmp / 'test.db').as_posix()}",
        "RKLLM_ENGINE": "mock",
        "MODELS_DIR": str(MODELS),
        "MAX_MODEL_FILE_GB": "0.002",
        "JWT_SECRET": "test-secret-0123456789abcdef0123456789",
        "ADMIN_USERNAME": "admin",
        "ADMIN_EMAIL": "admin@example.com",
        "ADMIN_PASSWORD": "admin-password",
        "MOCK_TOKEN_DELAY": "0",
        "MOCK_LOAD_SECONDS": "0",
        "LOGIN_MAX_ATTEMPTS": "1000",
    }
)

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.main import create_app  # noqa: E402


@pytest.fixture(scope="session")
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=30)


@pytest.fixture
async def make_client(app):
    clients = []

    async def factory(username: str | None = None, password: str | None = None) -> httpx.AsyncClient:
        c = _client(app)
        clients.append(c)
        if username:
            r = await c.post("/api/auth/login", json={"username": username, "password": password})
            assert r.status_code == 200, r.text
        return c

    yield factory
    for c in clients:
        await c.aclose()


@pytest.fixture
async def admin(make_client):
    return await make_client("admin", "admin-password")


def parse_sse(text: str) -> list[tuple[str, dict]]:
    import json

    events = []
    for block in text.split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev:
            events.append((ev, data))
    return events


@pytest.fixture
def sse():
    return parse_sse


@pytest.fixture
async def enabled_model(admin):
    """Enable the qwen fake model and make it the default."""
    models = (await admin.get("/api/admin/models")).json()
    qwen = next(m for m in models if m["filename"].startswith("qwen"))
    r = await admin.patch(f"/api/admin/models/{qwen['id']}", json={"enabled": True})
    assert r.status_code == 200, r.text
    r = await admin.patch("/api/admin/settings", json={"default_model_id": qwen["id"]})
    assert r.status_code == 200, r.text
    return qwen
