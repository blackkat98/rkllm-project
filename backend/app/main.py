import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.api import admin, auth, conversations, keys, models, openai_compat
from app.auth.security import hash_password
from app.config import Settings, get_settings
from app.db import init_db, session_factory
from app.engine.base import Backend
from app.engine.registry import scan_models, to_spec
from app.engine.worker import PRIORITY_BACKGROUND, EngineWorker, Job
from app.models import AppSettings, LLMModel, User
from app.services.chat import ChatService, mark_interrupted_messages

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
log = logging.getLogger("app")


def make_backend(settings: Settings) -> Backend:
    if settings.rkllm_engine == "mock":
        from app.engine.mock import MockBackend

        log.warning("Using MOCK engine (no NPU)")
        return MockBackend(settings.mock_token_delay, settings.mock_load_seconds)
    from app.engine.rkllm_binding import RKLLMBackend

    return RKLLMBackend(settings.rkllm_lib_path)


async def seed(settings: Settings) -> None:
    async with session_factory()() as s:
        if not await s.get(AppSettings, 1):
            s.add(AppSettings(id=1, open_signup=False, auto_title=True))
        users = (await s.execute(select(func.count(User.id)))).scalar_one()
        if users == 0:
            if settings.admin_password in ("changeme", ""):
                log.warning("Seeding admin with the default password - change ADMIN_PASSWORD!")
            s.add(User(
                username=settings.admin_username, email=settings.admin_email.lower(),
                display_name="Administrator", password_hash=hash_password(settings.admin_password),
                role="admin", settings={},
            ))
            log.info("Seeded admin user '%s'", settings.admin_username)
        await s.commit()


def raise_nofile_limit() -> None:
    try:  # the bundle did this too; the runtime opens many fds
        import resource  # Linux only

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(102400, hard), hard))
    except (ImportError, ValueError, OSError):
        pass


def create_app(settings: Settings | None = None, backend: Backend | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        raise_nofile_limit()
        engine = init_db(settings.database_url)
        if settings.database_url.startswith("sqlite"):  # tests / quick local runs
            from app.db import Base

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        await seed(settings)
        n = await mark_interrupted_messages()
        if n:
            log.info("Marked %d interrupted messages", n)
        async with session_factory()() as s:
            await scan_models(s, settings)

        worker = EngineWorker(
            backend or make_backend(settings),
            cpu_mask=settings.rkllm_cpu_mask,
            cpu_num=settings.rkllm_cpu_num,
            max_model_ram_mb=settings.max_model_ram_mb,
            idle_unload_minutes=settings.idle_unload_minutes,
            kv_fast_path=settings.kv_fast_path,
        )

        async def on_model_loaded(model_id: int, ram_mb: int | None, over: bool) -> None:
            async with session_factory()() as s:
                m = await s.get(LLMModel, model_id)
                if not m:
                    return
                m.measured_ram_mb = ram_mb
                if over:
                    m.status = "over_ram"
                    m.status_detail = f"Measured ~{ram_mb} MB RAM on load (limit {settings.max_model_ram_mb} MB)"
                    m.enabled = False
                    m.keep_loaded = False
                await s.commit()

        worker.on_model_loaded = on_model_loaded
        worker.start()
        app.state.worker = worker
        app.state.chat = ChatService(worker, settings)

        async with session_factory()() as s:
            keep = (await s.execute(
                select(LLMModel).where(LLMModel.keep_loaded.is_(True), LLMModel.enabled.is_(True), LLMModel.status == "ok")
            )).scalars().first()
            if keep:
                worker.submit(Job(kind="preload", model=to_spec(keep, settings), priority=PRIORITY_BACKGROUND))
        yield
        worker.stop()
        await engine.dispose()

    app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
            allow_methods=["*"], allow_headers=["*"],
        )
    for r in (auth.router, admin.router, models.router, conversations.router, keys.router, openai_compat.router):
        app.include_router(r)

    @app.get("/api/health")
    async def health():
        w = getattr(app.state, "worker", None)
        return {"ok": True, "engine": settings.rkllm_engine, "worker": w.status() if w else None}

    return app


app = create_app()
