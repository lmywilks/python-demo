"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:

    def load_dotenv() -> bool:
        return False


@dataclass(frozen=True)
class Settings:
    """Application settings for the agent workflow."""

    gateway: str = "mock"
    model: str = "mock/testing-agent"
    api_base: str | None = None
    temperature: float = 0.2
    timeout_seconds: int = 60


def load_settings() -> Settings:
    """Load settings from `.env` and the process environment."""

    load_dotenv()
    return Settings(
        gateway=os.getenv("LLM_GATEWAY", Settings.gateway).lower(),
        model=os.getenv("LLM_MODEL", Settings.model),
        api_base=os.getenv("LLM_API_BASE") or None,
        temperature=float(os.getenv("LLM_TEMPERATURE", Settings.temperature)),
        timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", Settings.timeout_seconds)),
    )
