# src/config.py
from __future__ import annotations

import json
import os
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_list_from_env(value: Optional[str]) -> List[str]:
    """
    Accept:
      - JSON list:   ["http://localhost:5173","*"]
      - CSV string:  http://localhost:5173,*
      - Single str:  *
      - Empty/None:  *
    Always return a non-empty list.
    """
    if value is None:
        return ["*"]

    s = value.strip()
    if not s:
        return ["*"]

    # Try JSON first
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                return parsed or ["*"]
        except Exception:
            # fall through to CSV split
            pass

    # Otherwise treat as comma-separated
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return parts or ["*"]


class Settings(BaseSettings):
    # App meta
    app_name: str = "AI Debate System"
    app_version: str = "0.1.0"

    # CORS (read raw string; we’ll parse ourselves)
    allowed_origins_raw: Optional[str] = Field(
        default="*",
        alias="ALLOWED_ORIGINS",
        description="CSV or JSON list of allowed origins",
    )

    # Security / rate limiting
    api_key: Optional[str] = Field(default=None, alias="API_KEY")
    rate_limit_default: Optional[str] = Field(default=None, alias="RATE_LIMIT_DEFAULT")

    # LLM / Providers
    llm_provider: Optional[str] = Field(default=None, alias="LLM_PROVIDER")
    llm_model: Optional[str] = Field(default=None, alias="LLM_MODEL")
    huggingface_api_token: Optional[str] = Field(default=None, alias="HUGGINGFACE_API_TOKEN")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    llm_temperature: Optional[float] = Field(default=None, alias="LLM_TEMPERATURE")
    llm_max_tokens: Optional[int] = Field(default=None, alias="LLM_MAX_TOKENS")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,  # allow aliases above
    )

    # ---- computed properties ----
    @property
    def allowed_origins(self) -> List[str]:
        return _parse_list_from_env(self.allowed_origins_raw)


# Create the singleton
settings = Settings()

# Mirror to os.environ for libs that read raw env vars
if settings.huggingface_api_token and not os.getenv("HUGGINGFACE_API_TOKEN"):
    os.environ["HUGGINGFACE_API_TOKEN"] = settings.huggingface_api_token
if settings.openai_api_key and not os.getenv("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = settings.openai_api_key
if settings.llm_provider and not os.getenv("LLM_PROVIDER"):
    os.environ["LLM_PROVIDER"] = settings.llm_provider
if settings.llm_model and not os.getenv("LLM_MODEL"):
    os.environ["LLM_MODEL"] = settings.llm_model
if settings.llm_temperature is not None and not os.getenv("LLM_TEMPERATURE"):
    os.environ["LLM_TEMPERATURE"] = str(settings.llm_temperature)
if settings.llm_max_tokens is not None and not os.getenv("LLM_MAX_TOKENS"):
    os.environ["LLM_MAX_TOKENS"] = str(settings.llm_max_tokens)
if settings.log_level and not os.getenv("LOG_LEVEL"):
    os.environ["LOG_LEVEL"] = settings.log_level
