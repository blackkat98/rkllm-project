from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, utcnow


class LLMModel(Base):
    """One row per .rkllm file ever seen in MODELS_DIR (hybrid registry)."""

    __tablename__ = "llm_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), unique=True)  # relative to MODELS_DIR
    display_name: Mapped[str] = mapped_column(String(128))
    family: Mapped[str] = mapped_column(String(32))  # chat template family
    max_context_len: Mapped[int] = mapped_column(Integer, default=4096)
    max_new_tokens: Mapped[int] = mapped_column(Integer, default=2048)
    sampling: Mapped[dict] = mapped_column(JSON, default=dict)  # temperature, top_p, top_k, repeat_penalty
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    keep_loaded: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    # ok | missing | too_large | over_ram
    status: Mapped[str] = mapped_column(String(16), default="ok")
    status_detail: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    file_mtime: Mapped[float] = mapped_column(Float, default=0)
    param_hint_b: Mapped[float | None] = mapped_column(Float)
    measured_ram_mb: Mapped[int | None] = mapped_column(Integer)
    tokenizer_path: Mapped[str | None] = mapped_column(String(512))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
