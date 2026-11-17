"""OpenAI-compatible /v1 endpoints (stateless), mirroring rkllm_api_bundle/server.py but
authenticated with per-user API keys and queued through the shared NPU worker."""

import json
import time
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.models import usable_models
from app.api.state import WorkerDep
from app.auth.deps import ApiKeyUser, SessionDep
from app.config import get_settings
from app.engine.registry import to_spec
from app.engine.templates import Msg, get_template
from app.engine.worker import Job
from app.memory.context import HistoryItem, plan_context
from app.memory.tokens import TokenCounter
from app.models import AppSettings, LLMModel

router = APIRouter(prefix="/v1", tags=["openai-compatible"])


class ChatMessageIn(BaseModel):
    role: str
    content: str | list | None = ""


class ChatCompletionIn(BaseModel):
    model: str | None = None
    messages: list[ChatMessageIn] = Field(min_length=1)
    stream: bool = False


def _text(content) -> str:
    if isinstance(content, list):  # [{"type":"text","text":...}]
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


@router.get("/models")
async def v1_models(user: ApiKeyUser, session: SessionDep):
    return {
        "object": "list",
        "data": [
            {"id": m.filename, "object": "model", "owned_by": "rkllm", "name": m.display_name}
            for m in await usable_models(session)
        ],
    }


@router.post("/chat/completions")
async def chat_completions(body: ChatCompletionIn, user: ApiKeyUser, session: SessionDep, worker: WorkerDep):
    settings = get_settings()
    model = None
    # only admins' keys choose the model; other keys always use the instance default
    if body.model and user.role == "admin":
        model = (await session.execute(
            select(LLMModel).where(or_(LLMModel.filename == body.model, LLMModel.display_name == body.model))
        )).scalar_one_or_none()
    if model is None:
        st = await session.get(AppSettings, 1)
        if st and st.default_model_id:
            model = await session.get(LLMModel, st.default_model_id)
    if model is None:
        models = await usable_models(session)
        model = models[0] if models else None
    if not model or not model.enabled or model.status != "ok":
        raise HTTPException(404, "Model not available")

    system = "\n\n".join(_text(m.content) for m in body.messages if m.role == "system") or None
    history = [HistoryItem(i, m.role, _text(m.content)) for i, m in enumerate(body.messages) if m.role in ("user", "assistant")]
    spec = to_spec(model, settings)
    plan = plan_context(
        system_without_summary=[None, None, system], summary=None, history=history,
        max_context=model.max_context_len, generation_reserve=spec.generation_reserve,
        counter=TokenCounter(settings.chars_per_token), allow_fold=False,
    )
    prompt = get_template(model.family).render(plan.system, [Msg(m.role, m.content) for m in plan.messages])
    job = Job(kind="openai", model=spec, prompt=prompt)
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    if body.stream:
        async def gen():
            async for ev, data in worker.stream(job):
                if ev == "token":
                    chunk = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model.filename,
                             "choices": [{"index": 0, "delta": {"content": data["text"]}, "finish_reason": None}]}
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                elif ev == "error":
                    yield f"data: {json.dumps({'error': {'message': data.get('message')}})}\n\n"
                elif ev == "done":
                    chunk = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model.filename,
                             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                    yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    parts: list[str] = []
    done: dict = {}
    async for ev, data in worker.stream(job):
        if ev == "token":
            parts.append(data["text"])
        elif ev == "error":
            raise HTTPException(500, data.get("message", "Generation failed"))
        elif ev == "done":
            done = data
    prompt_tokens = plan.est_tokens - spec.generation_reserve
    return {
        "id": cid, "object": "chat.completion", "created": created, "model": model.filename,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "".join(parts)}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": done.get("tokens", 0),
                  "total_tokens": prompt_tokens + done.get("tokens", 0)},
    }
