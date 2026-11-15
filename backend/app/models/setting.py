from sqlalchemy import Boolean, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AppSettings(Base):
    """Singleton row (id=1) with instance-wide settings editable by admins."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    open_signup: Mapped[bool] = mapped_column(Boolean, default=False)
    default_model_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_models.id", ondelete="SET NULL")
    )
    auto_title: Mapped[bool] = mapped_column(Boolean, default=True)
    global_system_prompt: Mapped[str | None] = mapped_column(Text)
