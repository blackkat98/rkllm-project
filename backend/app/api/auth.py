from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select

from app.auth.deps import CurrentUser, SessionDep
from app.auth.security import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    login_throttle,
    verify_password,
)
from app.config import get_settings
from app.db import utcnow
from app.models import AppSettings, User
from app.schemas import AuthConfig, LoginIn, MeUpdate, PasswordChange, RegisterIn, UserOut

router = APIRouter(prefix="/api/auth", tags=["auth"])


def set_auth_cookies(response: Response, user: User) -> None:
    s = get_settings()
    response.set_cookie(
        ACCESS_COOKIE, create_access_token(user.id), max_age=s.access_token_minutes * 60,
        httponly=True, secure=s.cookie_secure, samesite="lax", path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE, create_refresh_token(user.id, user.token_version),
        max_age=s.refresh_token_days * 86400,
        httponly=True, secure=s.cookie_secure, samesite="strict", path="/api/auth",
    )


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


@router.get("/config", response_model=AuthConfig)
async def auth_config(session: SessionDep):
    st = await session.get(AppSettings, 1)
    return AuthConfig(open_signup=bool(st and st.open_signup), app_name=get_settings().app_name)


@router.post("/login", response_model=UserOut)
async def login(body: LoginIn, request: Request, response: Response, session: SessionDep):
    ident = body.username.strip().lower()
    key = f"{ident}|{request.client.host if request.client else '-'}"
    if login_throttle.blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts, try again in a few minutes")
    user = (
        await session.execute(
            select(User).where(or_(func.lower(User.username) == ident, func.lower(User.email) == ident))
        )
    ).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        login_throttle.fail(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account disabled")
    login_throttle.reset(key)
    user.last_login_at = utcnow()
    await session.commit()
    set_auth_cookies(response, user)
    return user


@router.post("/register", response_model=UserOut, status_code=201)
async def register(body: RegisterIn, response: Response, session: SessionDep):
    st = await session.get(AppSettings, 1)
    if not (st and st.open_signup):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sign-up is disabled. Ask an administrator for an account.")
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
        password_hash=hash_password(body.password), role="user", settings={},
    )
    session.add(user)
    await session.commit()
    set_auth_cookies(response, user)
    return user


@router.post("/refresh", response_model=UserOut)
async def refresh(request: Request, response: Response, session: SessionDep):
    token = request.cookies.get(REFRESH_COOKIE)
    payload = decode_token(token, "refresh") if token else None
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    user = await session.get(User, int(payload["sub"]))
    if not user or not user.is_active or payload.get("ver") != user.token_version:
        clear_auth_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")
    set_auth_cookies(response, user)
    return user


@router.post("/logout", status_code=204)
async def logout(response: Response):
    clear_auth_cookies(response)


@router.post("/logout-all", status_code=204)
async def logout_all(user: CurrentUser, response: Response, session: SessionDep):
    user.token_version += 1
    await session.commit()
    clear_auth_cookies(response)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user


@router.patch("/me", response_model=UserOut)
async def update_me(body: MeUpdate, user: CurrentUser, session: SessionDep):
    data = body.model_dump(exclude_unset=True)
    if "email" in data and data["email"]:
        email = data["email"].lower()
        taken = (await session.execute(select(User.id).where(func.lower(User.email) == email, User.id != user.id))).first()
        if taken:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use")
        user.email = email
    if "display_name" in data:
        user.display_name = data["display_name"]
    if "custom_instructions" in data:
        user.custom_instructions = data["custom_instructions"] or None
    if data.get("settings") is not None:
        user.settings = {**(user.settings or {}), **data["settings"]}
    await session.commit()
    return user


@router.post("/password", status_code=204)
async def change_password(body: PasswordChange, user: CurrentUser, response: Response, session: SessionDep):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # log out other sessions
    await session.commit()
    set_auth_cookies(response, user)
