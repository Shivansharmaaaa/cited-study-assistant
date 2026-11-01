"""Runtime configuration, read from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./study.db"
    secret_key: str = "dev-only-insecure-secret-do-not-use-in-prod"
    token_ttl_minutes: int = 60
    env: str = "dev"
    cors_origins: tuple[str, ...] = ("http://localhost:5173",)

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def load_settings() -> Settings:
    env = os.getenv("APP_ENV", "dev")
    secret = os.getenv("SECRET_KEY", "")
    if not secret:
        if env == "production":
            # Refuse to boot with a guessable signing key in production.
            raise RuntimeError("SECRET_KEY must be set when APP_ENV=production")
        secret = Settings.secret_key
    elif env == "production" and len(secret) < 32:
        raise RuntimeError("SECRET_KEY must be at least 32 characters in production")
    origins = tuple(
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
    )
    return Settings(
        database_url=os.getenv("DATABASE_URL", Settings.database_url),
        secret_key=secret,
        token_ttl_minutes=int(os.getenv("TOKEN_TTL_MINUTES", "60")),
        env=env,
        cors_origins=origins,
    )
