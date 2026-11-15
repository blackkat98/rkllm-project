import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    title_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    model_id: Mapped[int | None] = mapped_column(ForeignKey("llm_models.id", ondelete="SET NULL"))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    # tier-2 memory: rolling summary of messages with seq <= summary_upto_seq
    summary: Mapped[str | None] = mapped_column(Text)
    summary_upto_seq: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Message.seq",
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_seq", "conversation_id", "seq", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text, default="")
    model_id: Mapped[int | None] = mapped_column(ForeignKey("llm_models.id", ondelete="SET NULL"))
    # complete | streaming | aborted | error
    status: Mapped[str] = mapped_column(String(16), default="complete")
    error: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    tok_per_s: Mapped[float | None] = mapped_column(Float)
    used_kv_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
