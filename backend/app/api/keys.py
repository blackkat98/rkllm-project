from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.auth.deps import CurrentUser, SessionDep
from app.auth.security import generate_api_key
from app.models import ApiKey
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut

router = APIRouter(prefix="/api/keys", tags=["api-keys"])


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(user: CurrentUser, session: SessionDep):
    return (
        await session.execute(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at))
    ).scalars().all()


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_key(body: ApiKeyCreate, user: CurrentUser, session: SessionDep):
    raw, prefix, digest = generate_api_key()
    key = ApiKey(user_id=user.id, name=body.name, prefix=prefix, key_hash=digest)
    session.add(key)
    await session.commit()
    return ApiKeyCreated(**ApiKeyOut.model_validate(key).model_dump(), key=raw)


@router.delete("/{key_id}", status_code=204)
async def delete_key(key_id: int, user: CurrentUser, session: SessionDep):
    key = await session.get(ApiKey, key_id)
    if not key or key.user_id != user.id:
        raise HTTPException(404, "Key not found")
    await session.delete(key)
    await session.commit()
