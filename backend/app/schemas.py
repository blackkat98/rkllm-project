import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------- auth / users ----------------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=255, description="username or email")
    password: str = Field(min_length=1, max_length=256)


class RegisterIn(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)


class UserOut(ORM):
    id: int
    username: str
    email: str
    display_name: str | None
    role: str
    is_active: bool
    custom_instructions: str | None
    settings: dict
    created_at: datetime
    last_login_at: datetime | None


class MeUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    email: EmailStr | None = None
    custom_instructions: str | None = Field(default=None, max_length=4000)
    settings: dict | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=256)


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)
    role: Literal["admin", "user"] = "user"


class AdminUserUpdate(BaseModel):
    email: EmailStr | None = None
    display_name: str | None = Field(default=None, max_length=128)
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=256)


class AuthConfig(BaseModel):
    open_signup: bool
    app_name: str


# ---------------- models ----------------
class ModelPublic(BaseModel):
    id: int
    display_name: str
    family: str
    max_context_len: int
    param_hint_b: float | None
    is_default: bool
    loaded: bool


class ModelAdmin(ORM):
    id: int
    filename: str
    display_name: str
    family: str
    max_context_len: int
    max_new_tokens: int
    sampling: dict
    enabled: bool
    keep_loaded: bool
    sort_order: int
    status: str
    status_detail: str | None
    file_size: int
    param_hint_b: float | None
    measured_ram_mb: int | None
    tokenizer_path: str | None
    scanned_at: datetime
    # computed
    is_default: bool = False
    loaded: bool = False
    est_ram_mb: int = 0
    warnings: list[str] = []


class ModelPolicy(BaseModel):
    max_param_b: float
    max_file_gb: float
    max_ram_mb: int
    min_free_ram_mb: int


class Sampling(BaseModel):
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    top_k: int | None = Field(default=None, ge=1, le=200)
    repeat_penalty: float | None = Field(default=None, ge=0.5, le=2)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)


class ModelUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    family: Literal["chatml", "deepseek", "gemma", "llama3", "llama2", "phi3"] | None = None
    max_context_len: int | None = Field(default=None, ge=512, le=16384)
    max_new_tokens: int | None = Field(default=None, ge=16, le=8192)
    sampling: Sampling | None = None
    enabled: bool | None = None
    keep_loaded: bool | None = None
    sort_order: int | None = None


class AppSettingsOut(ORM):
    open_signup: bool
    default_model_id: int | None
    auto_title: bool
    global_system_prompt: str | None


class AppSettingsUpdate(BaseModel):
    open_signup: bool | None = None
    default_model_id: int | None = None
    auto_title: bool | None = None
    global_system_prompt: str | None = Field(default=None, max_length=4000)


# ---------------- conversations ----------------
class ConversationOut(ORM):
    id: uuid.UUID
    title: str
    model_id: int | None
    system_prompt: str | None
    pinned: bool
    archived: bool
    created_at: datetime
    updated_at: datetime
    has_summary: bool = False


class ConversationCreate(BaseModel):
    model_id: int | None = None
    system_prompt: str | None = Field(default=None, max_length=4000)
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    pinned: bool | None = None
    archived: bool | None = None
    model_id: int | None = None
    system_prompt: str | None = Field(default=None, max_length=4000)


class MessageOut(ORM):
    id: int
    seq: int
    role: str
    content: str
    model_id: int | None
    status: str
    error: str | None
    prompt_tokens: int | None
    completion_tokens: int | None
    tok_per_s: float | None
    used_kv_cache: bool
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
    summary: str | None
    summary_upto_seq: int
    generating: bool = False


class SendMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    model_id: int | None = None


class RegenerateIn(BaseModel):
    model_id: int | None = None


class EditMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    model_id: int | None = None


# ---------------- api keys ----------------
class ApiKeyOut(ORM):
    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyCreated(ApiKeyOut):
    key: str
