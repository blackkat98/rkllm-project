import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.config import get_settings
from app.db import utcnow

_hasher = PasswordHasher()

ACCESS_COOKIE = "rk_access"
REFRESH_COOKIE = "rk_refresh"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _encode(payload: dict, ttl: timedelta) -> str:
    now = utcnow()
    payload = {**payload, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def create_access_token(user_id: int) -> str:
    s = get_settings()
    return _encode({"sub": str(user_id), "typ": "access"}, timedelta(minutes=s.access_token_minutes))


def create_refresh_token(user_id: int, token_version: int) -> str:
    s = get_settings()
    return _encode(
        {"sub": str(user_id), "typ": "refresh", "ver": token_version},
        timedelta(days=s.refresh_token_days),
    )


def decode_token(token: str, expected_type: str) -> dict | None:
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != expected_type:
        return None
    return payload


# --- API keys (OpenAI-compatible endpoints) ---


def generate_api_key() -> tuple[str, str, str]:
    """Returns (plaintext, prefix, sha256)."""
    raw = "rk-" + secrets.token_urlsafe(32)
    return raw, raw[:10], hash_api_key(raw)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# --- tiny in-memory login throttle (single-process deployment) ---


class LoginThrottle:
    def __init__(self) -> None:
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        window = get_settings().login_window_seconds
        q = self._fails[key]
        now = time.monotonic()
        while q and now - q[0] > window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        return len(self._prune(key)) >= get_settings().login_max_attempts

    def fail(self, key: str) -> None:
        self._prune(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        self._fails.pop(key, None)


login_throttle = LoginThrottle()
