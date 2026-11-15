from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import ACCESS_COOKIE, decode_token, hash_api_key
from app.db import get_session, utcnow
from app.models import ApiKey, User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(request: Request, session: SessionDep) -> User:
    token = request.cookies.get(ACCESS_COOKIE)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    payload = decode_token(token, "access") if token else None
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = await session.get(User, int(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def get_api_key_user(request: Request, session: SessionDep) -> User:
    """Auth for /v1/*: `Authorization: Bearer rk-...` API key (or a logged-in browser session)."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer rk-"):
        key = (
            await session.execute(select(ApiKey).where(ApiKey.key_hash == hash_api_key(auth[7:])))
        ).scalar_one_or_none()
        if key:
            user = await session.get(User, key.user_id)
            if user and user.is_active:
                key.last_used_at = utcnow()
                await session.commit()
                return user
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return await get_current_user(request, session)


ApiKeyUser = Annotated[User, Depends(get_api_key_user)]
