from fastapi import APIRouter
from sqlalchemy import select

from app.api.state import WorkerDep
from app.auth.deps import CurrentUser, SessionDep
from app.models import AppSettings, LLMModel
from app.schemas import ModelPublic

router = APIRouter(prefix="/api", tags=["models"])


async def usable_models(session) -> list[LLMModel]:
    return list(
        (
            await session.execute(
                select(LLMModel)
                .where(LLMModel.enabled.is_(True), LLMModel.status == "ok")
                .order_by(LLMModel.sort_order, LLMModel.display_name)
            )
        ).scalars()
    )


@router.get("/models", response_model=list[ModelPublic])
async def list_models(user: CurrentUser, session: SessionDep, worker: WorkerDep):
    st = await session.get(AppSettings, 1)
    default_id = st.default_model_id if st else None
    loaded = worker.loaded_model_id
    return [
        ModelPublic(
            id=m.id, display_name=m.display_name, family=m.family, max_context_len=m.max_context_len,
            param_hint_b=m.param_hint_b, is_default=m.id == default_id, loaded=m.id == loaded,
        )
        for m in await usable_models(session)
    ]


@router.get("/engine/status")
async def engine_status(user: CurrentUser, worker: WorkerDep):
    return worker.status()
