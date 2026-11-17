import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, or_, select

from app.api.state import ChatDep
from app.auth.deps import CurrentUser, SessionDep
from app.db import utcnow
from app.memory.summarizer import fallback_title
from app.models import AppSettings, Conversation, LLMModel, Message, User
from app.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
    EditMessageIn,
    MessageOut,
    RegenerateIn,
    SendMessageIn,
)
from app.services.chat import Generation, message_dict

router = APIRouter(prefix="/api/conversations", tags=["conversations"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


async def _owned(session, conversation_id: uuid.UUID, user: User) -> Conversation:
    conv = await session.get(Conversation, conversation_id)
    if not conv or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


def _out(conv: Conversation) -> ConversationOut:
    out = ConversationOut.model_validate(conv)
    out.has_summary = bool(conv.summary)
    return out


async def resolve_model(session, user: User, requested: int | None, conv: Conversation | None) -> LLMModel:
    """Admins: requested -> conversation's model -> own default -> instance default -> first enabled.

    Only admins choose models. Everyone else always gets the instance default (set in Admin), so
    the single NPU isn't swapping models between users. Their requested model is ignored, not
    rejected, so an outdated client keeps working.
    """
    st = await session.get(AppSettings, 1)
    instance_default = st.default_model_id if st else None
    if user.role == "admin":
        candidates = [
            requested,
            conv.model_id if conv else None,
            (user.settings or {}).get("default_model_id"),
            instance_default,
        ]
    else:
        candidates = [None, instance_default]
    for i, mid in enumerate(candidates):
        if mid is None:
            continue
        m = await session.get(LLMModel, int(mid))
        if m and m.enabled and m.status == "ok":
            return m
        if i == 0:
            raise HTTPException(400, "Selected model is not available")
    m = (
        await session.execute(
            select(LLMModel).where(LLMModel.enabled.is_(True), LLMModel.status == "ok").order_by(LLMModel.sort_order).limit(1)
        )
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(503, "No models are enabled yet. An administrator must enable one in Admin → Models.")
    return m


# ------------------------------------------------------------------ CRUD
@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    user: CurrentUser,
    session: SessionDep,
    q: str | None = Query(default=None, max_length=200),
    archived: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Conversation).where(Conversation.user_id == user.id, Conversation.archived.is_(archived))
    if q:
        like = f"%{q.lower()}%"
        in_messages = select(Message.conversation_id).where(func.lower(Message.content).like(like))
        stmt = stmt.where(or_(func.lower(Conversation.title).like(like), Conversation.id.in_(in_messages)))
    stmt = stmt.order_by(Conversation.pinned.desc(), Conversation.updated_at.desc()).limit(limit).offset(offset)
    return [_out(c) for c in (await session.execute(stmt)).scalars()]


@router.post("", response_model=ConversationOut, status_code=201)
async def create_conversation(body: ConversationCreate, user: CurrentUser, session: SessionDep):
    model = await resolve_model(session, user, body.model_id, None)
    conv = Conversation(user_id=user.id, model_id=model.id, system_prompt=body.system_prompt,
                        title=body.title or "New chat")
    session.add(conv)
    await session.commit()
    return _out(conv)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, chat: ChatDep):
    conv = await _owned(session, conversation_id, user)
    msgs = (await session.execute(select(Message).where(Message.conversation_id == conv.id).order_by(Message.seq))).scalars().all()
    base = _out(conv).model_dump()
    return ConversationDetail(
        **base,
        messages=[MessageOut.model_validate(m) for m in msgs],
        summary=conv.summary,
        summary_upto_seq=conv.summary_upto_seq,
        generating=chat.is_generating(conv.id),
    )


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(conversation_id: uuid.UUID, body: ConversationUpdate, user: CurrentUser, session: SessionDep):
    conv = await _owned(session, conversation_id, user)
    data = body.model_dump(exclude_unset=True)
    if "model_id" in data:
        if user.role != "admin":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only administrators can change the model")
        if data["model_id"] is not None:
            await resolve_model(session, user, data["model_id"], None)
    if "title" in data:
        conv.title_generated = True  # user-chosen title: never overwrite
    for k, v in data.items():
        setattr(conv, k, v)
    await session.commit()
    return _out(conv)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, chat: ChatDep):
    conv = await _owned(session, conversation_id, user)
    chat.stop(conv.id)
    await session.execute(delete(Message).where(Message.conversation_id == conv.id))
    await session.delete(conv)
    await session.commit()


@router.get("/{conversation_id}/title")
async def wait_for_title(conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, chat: ChatDep,
                         wait: float = Query(default=0, ge=0, le=60)):
    """Long-poll for the auto-generated title (it runs as a background NPU job)."""
    conv = await _owned(session, conversation_id, user)
    task = chat.title_tasks.get(conv.id)
    if task and wait:
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=wait)
        except (TimeoutError, Exception):
            pass
        await session.refresh(conv)
    return {"title": conv.title, "generated": conv.title_generated, "pending": conv.id in chat.title_tasks}


# ------------------------------------------------------------------ generation
async def _start_generation(session, chat, conv: Conversation, user: User, user_msg: Message,
                            model: LLMModel, prev_state: int | None, extra_meta: dict | None = None):
    next_seq = user_msg.seq + 1
    assistant = Message(conversation_id=conv.id, seq=next_seq, role="assistant", content="",
                        model_id=model.id, status="streaming")
    session.add(assistant)
    conv.updated_at = utcnow()
    conv.model_id = model.id
    await session.commit()
    gen = chat.start(Generation(
        conversation_id=conv.id, user_id=user.id, assistant_message_id=assistant.id,
        user_message_id=user_msg.id, model_id=model.id, prev_state=prev_state,
    ))
    meta = {
        "conversation": _out(conv).model_dump(mode="json"),
        "user_message": message_dict(user_msg),
        "assistant_message": message_dict(assistant),
        "model": {"id": model.id, "display_name": model.display_name},
        **(extra_meta or {}),
    }
    return StreamingResponse(chat.stream(gen, first=[("meta", meta)]), media_type="text/event-stream", headers=SSE_HEADERS)


def _ensure_idle(chat, conv: Conversation) -> None:
    if chat.is_generating(conv.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "A reply is still being generated in this chat")


@router.post("/{conversation_id}/messages")
async def send_message(conversation_id: uuid.UUID, body: SendMessageIn, user: CurrentUser, session: SessionDep, chat: ChatDep):
    conv = await _owned(session, conversation_id, user)
    _ensure_idle(chat, conv)
    model = await resolve_model(session, user, body.model_id, conv)
    last = (await session.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.seq.desc()).limit(1)
    )).scalar_one_or_none()
    # tier-3 hint: the KV cache can only be reused if the chat ends with a complete answer
    prev_state = last.id if last and last.role == "assistant" and last.status == "complete" else None
    if last is None and not conv.title_generated:
        conv.title = fallback_title(body.content)
    user_msg = Message(conversation_id=conv.id, seq=(last.seq + 1) if last else 1, role="user", content=body.content)
    session.add(user_msg)
    await session.flush()
    return await _start_generation(session, chat, conv, user, user_msg, model, prev_state)


@router.post("/{conversation_id}/regenerate")
async def regenerate(conversation_id: uuid.UUID, body: RegenerateIn, user: CurrentUser, session: SessionDep, chat: ChatDep):
    conv = await _owned(session, conversation_id, user)
    _ensure_idle(chat, conv)
    model = await resolve_model(session, user, body.model_id, conv)
    msgs = (await session.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.seq.desc()).limit(2)
    )).scalars().all()
    if not msgs:
        raise HTTPException(400, "Nothing to regenerate")
    removed = None
    if msgs[0].role == "assistant":
        removed = msgs[0].id
        await session.delete(msgs[0])
        await session.flush()
        user_msg = msgs[1] if len(msgs) > 1 else None
    else:
        user_msg = msgs[0]
    if not user_msg or user_msg.role != "user":
        raise HTTPException(400, "Nothing to regenerate")
    return await _start_generation(session, chat, conv, user, user_msg, model, None, {"removed_message_id": removed})


@router.post("/{conversation_id}/messages/{message_id}/edit")
async def edit_message(conversation_id: uuid.UUID, message_id: int, body: EditMessageIn,
                       user: CurrentUser, session: SessionDep, chat: ChatDep):
    conv = await _owned(session, conversation_id, user)
    _ensure_idle(chat, conv)
    msg = await session.get(Message, message_id)
    if not msg or msg.conversation_id != conv.id or msg.role != "user":
        raise HTTPException(404, "Message not found")
    model = await resolve_model(session, user, body.model_id, conv)
    msg.content = body.content
    await session.execute(delete(Message).where(Message.conversation_id == conv.id, Message.seq > msg.seq))
    if conv.summary_upto_seq >= msg.seq:  # the summary contains the edited text: rebuild it lazily
        conv.summary, conv.summary_upto_seq = None, 0
    await session.flush()
    return await _start_generation(session, chat, conv, user, msg, model, None, {"truncated_after_seq": msg.seq})


@router.post("/{conversation_id}/stop", status_code=204)
async def stop(conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, chat: ChatDep):
    conv = await _owned(session, conversation_id, user)
    chat.stop(conv.id)
    return Response(status_code=204)


@router.get("/{conversation_id}/stream")
async def attach(conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep, chat: ChatDep):
    """Re-attach to an in-progress generation (e.g. after a page reload)."""
    conv = await _owned(session, conversation_id, user)
    gen = chat.active.get(conv.id)
    if not gen:
        return Response(status_code=204)
    return StreamingResponse(chat.stream(gen), media_type="text/event-stream", headers=SSE_HEADERS)
