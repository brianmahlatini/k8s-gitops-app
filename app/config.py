"""Twelve-factor configuration: everything comes from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str
    version: str

    @classmethod
    def from_env(cls) -> Settings:
        level = os.getenv("LOG_LEVEL", "info").upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError(f"LOG_LEVEL must be debug/info/warning/error, got {level!r}")
        return cls(
            app_env=os.getenv("APP_ENV", "local"),
            log_level=level,
            version=os.getenv("APP_VERSION", "dev"),
        )
