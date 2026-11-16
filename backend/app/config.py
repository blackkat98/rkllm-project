from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- core ---
    app_name: str = "RKLLM Chat"
    database_url: str = "postgresql+asyncpg://rkllm:rkllm@localhost:5432/rkllm"
    cors_origins: list[str] = Field(default_factory=list)

    # --- auth ---
    jwt_secret: str = "change-me"
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    cookie_secure: bool = False  # set true when served over HTTPS
    admin_username: str = "admin"
    admin_email: str = "admin@example.com"
    admin_password: str = "changeme"
    login_max_attempts: int = 8  # per username+ip per window
    login_window_seconds: int = 300

    # --- engine ---
    rkllm_engine: Literal["rkllm", "mock"] = "rkllm"
    rkllm_lib_path: str = "librkllmrt.so"
    models_dir: str = "/models"
    # RK3588: cores 4-7 are the Cortex-A76 big cores
    rkllm_cpu_mask: int = (1 << 4) | (1 << 5) | (1 << 6) | (1 << 7)
    rkllm_cpu_num: int = 4
    default_max_context: int = 4096
    default_max_new_tokens: int = 2048
    idle_unload_minutes: int = 0  # 0 = never unload an idle model
    kv_fast_path: bool = True  # tier-3 memory: reuse the NPU KV cache for the "hot" chat

    # --- <=4B parameter policy (see README) ---
    max_model_file_gb: float = 5.5  # 4B w8a8 files are ~3.6-5.3 GB (large vocabularies at the top)
    max_model_ram_mb: int = 6000
    max_param_hint_b: float = 4.0
    # refuse to load when MemAvailable < estimated model RAM + this headroom (8 GB board)
    min_free_ram_mb: int = 512

    # --- memory (tier 2) ---
    summary_trigger_ratio: float = 0.70  # summarise when prompt > 70% of context
    summary_target_ratio: float = 0.45  # fold old turns until prompt < 45% of context
    keep_recent_messages: int = 6  # never fold the latest N messages
    chars_per_token: float = 3.0  # conservative token estimate when no tokenizer.json

    # --- mock engine ---
    mock_token_delay: float = 0.02
    mock_load_seconds: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
