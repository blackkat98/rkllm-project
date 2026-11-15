from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")  # admin | user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # bumped on password change / "log out everywhere" -> invalidates refresh tokens
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    custom_instructions: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)  # theme, default_model_id, ...
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"
