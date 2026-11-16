from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, or_, select, update

from app.api.state import WorkerDep
from app.auth.deps import AdminUser, SessionDep
from app.auth.security import hash_password
from app.config import get_settings
from app.engine.registry import estimate_ram_mb, scan_models, to_spec
from app.engine.worker import PRIORITY_BACKGROUND, Job, _meminfo_available_mb
from app.models import AppSettings, Conversation, LLMModel, Message, User
from app.schemas import (
    AdminUserCreate,
    AdminUserUpdate,
    AppSettingsOut,
    AppSettingsUpdate,
    ModelAdmin,
    ModelPolicy,
    ModelUpdate,
    UserOut,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ------------------------------------------------------------------ users
@router.get("/users", response_model=list[UserOut])
async def list_users(_: AdminUser, session: SessionDep):
    return (await session.execute(select(User).order_by(User.created_at))).scalars().all()


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: AdminUserCreate, _: AdminUser, session: SessionDep):
    exists = (
        await session.execute(
            select(User.id).where(
                or_(func.lower(User.username) == body.username.lower(), func.lower(User.email) == body.email.lower())
            )
        )
    ).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username or email already taken")
    user = User(
        username=body.username, email=body.email.lower(), display_name=body.display_name,
        password_hash=hash_password(body.password), role=body.role, settings={},
    )
    session.add(user)
    await session.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: AdminUserUpdate, admin: AdminUser, session: SessionDep):
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    data = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (data.get("role") == "user" or data.get("is_active") is False):
        raise HTTPException(400, "You cannot demote or disable yourself")
    if data.get("email"):
        user.email = data["email"].lower()
    if "display_name" in data:
        user.display_name = data["display_name"]
    if data.get("role"):
        user.role = data["role"]
    if data.get("is_active") is not None:
        user.is_active = data["is_active"]
        if not user.is_active:
            user.token_version += 1
    if data.get("password"):
        user.password_hash = hash_password(data["password"])
        user.token_version += 1
    await session.commit()
    return user


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, admin: AdminUser, session: SessionDep):
    if user_id == admin.id:
        raise HTTPException(400, "You cannot delete yourself")
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    await session.delete(user)
    await session.commit()


# ------------------------------------------------------------------ app settings
async def _settings_row(session) -> AppSettings:
    st = await session.get(AppSettings, 1)
    if not st:
        st = AppSettings(id=1)
        session.add(st)
        await session.flush()
    return st


@router.get("/settings", response_model=AppSettingsOut)
async def get_app_settings(_: AdminUser, session: SessionDep):
    st = await _settings_row(session)
    await session.commit()
    return st


@router.patch("/settings", response_model=AppSettingsOut)
async def update_app_settings(body: AppSettingsUpdate, _: AdminUser, session: SessionDep):
    st = await _settings_row(session)
    data = body.model_dump(exclude_unset=True)
    if "default_model_id" in data and data["default_model_id"] is not None:
        m = await session.get(LLMModel, data["default_model_id"])
        if not m or not m.enabled or m.status != "ok":
            raise HTTPException(400, "Default model must be an enabled model")
    for k, v in data.items():
        setattr(st, k, v)
    await session.commit()
    return st


# ------------------------------------------------------------------ models
def _model_admin(
    m: LLMModel, default_id: int | None, loaded_id: int | None, free_for_load_mb: int | None = None
) -> ModelAdmin:
    s = get_settings()
    out = ModelAdmin.model_validate(m)
    out.is_default = m.id == default_id
    out.loaded = m.id == loaded_id
    out.est_ram_mb = estimate_ram_mb(m)
    warnings = []
    if m.param_hint_b and m.param_hint_b > s.max_param_hint_b:
        warnings.append(
            f"Filename suggests ~{m.param_hint_b:g}B parameters (policy: ≤{s.max_param_hint_b:g}B). "
            "Size and RAM checks still apply."
        )
    if out.est_ram_mb > s.max_model_ram_mb and m.status == "ok":
        warnings.append(f"Estimated ~{out.est_ram_mb} MB RAM, close to/above the {s.max_model_ram_mb} MB limit.")
    if free_for_load_mb is not None and m.id != loaded_id and m.status == "ok" \
            and out.est_ram_mb + s.min_free_ram_mb > free_for_load_mb:
        warnings.append(
            f"Needs ~{out.est_ram_mb} MB (+{s.min_free_ram_mb} MB headroom) but only ~{free_for_load_mb} MB "
            "would be free: it may not fit with the current free memory."
        )
    if m.family == "chatml" and not any(x in m.filename.lower() for x in ("qwen", "chatml", "smol")):
        warnings.append("Template family was guessed (ChatML). Check it matches the model.")
    out.warnings = warnings
    return out


def _free_for_load_mb(rows: list[LLMModel], loaded_id: int | None) -> int | None:
    """RAM that would be available for a new model: MemAvailable plus what the resident
    model frees when it is unloaded first. None when /proc/meminfo is not readable."""
    avail = _meminfo_available_mb()
    if avail is None:
        return None
    loaded = next((r for r in rows if r.id == loaded_id), None)
    if loaded:
        avail += loaded.measured_ram_mb or estimate_ram_mb(loaded)
    return avail


@router.get("/model-policy", response_model=ModelPolicy)
async def model_policy(_: AdminUser):
    s = get_settings()
    return ModelPolicy(
        max_param_b=s.max_param_hint_b,
        max_file_gb=s.max_model_file_gb,
        max_ram_mb=s.max_model_ram_mb,
        min_free_ram_mb=s.min_free_ram_mb,
    )


@router.get("/models", response_model=list[ModelAdmin])
async def admin_list_models(_: AdminUser, session: SessionDep, worker: WorkerDep):
    st = await session.get(AppSettings, 1)
    rows = list((await session.execute(select(LLMModel).order_by(LLMModel.sort_order, LLMModel.display_name))).scalars())
    loaded_id = worker.loaded_model_id
    free = _free_for_load_mb(rows, loaded_id)
    return [_model_admin(m, st.default_model_id if st else None, loaded_id, free) for m in rows]


@router.post("/models/rescan")
async def rescan(_: AdminUser, session: SessionDep):
    return await scan_models(session, get_settings())


@router.patch("/models/{model_id}", response_model=ModelAdmin)
async def update_model(model_id: int, body: ModelUpdate, _: AdminUser, session: SessionDep, worker: WorkerDep):
    m = await session.get(LLMModel, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    data = body.model_dump(exclude_unset=True)
    if data.get("enabled") and m.status != "ok":
        raise HTTPException(400, f"Cannot enable a model with status '{m.status}': {m.status_detail or ''}".strip())
    if data.get("keep_loaded"):
        if not (data.get("enabled", m.enabled)):
            raise HTTPException(400, "Only an enabled model can be kept loaded")
        # 8 GB board: at most one resident model
        others = (await session.execute(select(LLMModel).where(LLMModel.keep_loaded.is_(True), LLMModel.id != m.id))).scalars()
        for o in others:
            o.keep_loaded = False
    if "sampling" in data:
        data["sampling"] = {k: v for k, v in (data["sampling"] or {}).items() if v is not None}
    for k, v in data.items():
        setattr(m, k, v)
    if not m.enabled:
        m.keep_loaded = False
        st = await session.get(AppSettings, 1)
        if st and st.default_model_id == m.id:
            st.default_model_id = None
    await session.commit()
    if m.keep_loaded:
        worker.submit(Job(kind="preload", model=to_spec(m, get_settings()), priority=PRIORITY_BACKGROUND))
    st = await session.get(AppSettings, 1)
    return _model_admin(m, st.default_model_id if st else None, worker.loaded_model_id)


@router.post("/models/{model_id}/reset-status", response_model=ModelAdmin)
async def reset_model_status(model_id: int, _: AdminUser, session: SessionDep, worker: WorkerDep):
    """Clears a sticky 'over_ram' flag so the model can be tried again."""
    m = await session.get(LLMModel, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    if m.status == "over_ram":
        m.status, m.status_detail, m.measured_ram_mb = "ok", None, None
    await session.commit()
    await scan_models(session, get_settings())
    await session.refresh(m)
    st = await session.get(AppSettings, 1)
    return _model_admin(m, st.default_model_id if st else None, worker.loaded_model_id)


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_model(model_id: int, _: AdminUser, session: SessionDep):
    """Removes the entry of a model whose file is gone from the models folder.

    Old chats and messages keep their text; only their link to this model is cleared
    (they then fall back to the default model). Models whose file still exists can't be
    removed here: delete the file, rescan, then remove it.
    """
    m = await session.get(LLMModel, model_id)
    if not m:
        raise HTTPException(404, "Model not found")
    if m.status != "missing":
        raise HTTPException(409, "Only models whose file is missing can be removed. Delete the file and rescan first.")
    # explicit, so it also works on databases that don't enforce ON DELETE SET NULL (SQLite in tests)
    await session.execute(update(Conversation).where(Conversation.model_id == m.id).values(model_id=None))
    await session.execute(update(Message).where(Message.model_id == m.id).values(model_id=None))
    await session.execute(update(AppSettings).where(AppSettings.default_model_id == m.id).values(default_model_id=None))
    await session.execute(delete(LLMModel).where(LLMModel.id == m.id))
    await session.commit()


@router.delete("/models", status_code=status.HTTP_200_OK)
async def remove_missing_models(_: AdminUser, session: SessionDep):
    """Removes every model entry whose file is gone. Returns how many were removed."""
    ids = (await session.execute(select(LLMModel.id).where(LLMModel.status == "missing"))).scalars().all()
    if ids:
        await session.execute(update(Conversation).where(Conversation.model_id.in_(ids)).values(model_id=None))
        await session.execute(update(Message).where(Message.model_id.in_(ids)).values(model_id=None))
        await session.execute(update(AppSettings).where(AppSettings.default_model_id.in_(ids)).values(default_model_id=None))
        await session.execute(delete(LLMModel).where(LLMModel.id.in_(ids)))
        await session.commit()
    return {"removed": len(ids)}


@router.post("/engine/unload")
async def unload_engine(_: AdminUser, worker: WorkerDep):
    if not worker.unload_now():
        raise HTTPException(409, "The NPU is busy; try again when idle")
    return {"ok": True}
