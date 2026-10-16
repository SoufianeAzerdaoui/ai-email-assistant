"""Environment-backed application settings."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@dataclass(frozen=True)
class Settings:
    jwt_secret: str
    jwt_expire_minutes: int


@lru_cache
def get_settings() -> Settings:
    secret = os.environ.get("JWT_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must contain at least 32 characters")
    try:
        expire_minutes = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))
    except ValueError as error:
        raise RuntimeError("JWT_EXPIRE_MINUTES must be an integer") from error
    if expire_minutes <= 0:
        raise RuntimeError("JWT_EXPIRE_MINUTES must be greater than zero")
    return Settings(jwt_secret=secret, jwt_expire_minutes=expire_minutes)


@lru_cache
def get_webhook_secret() -> str:
    secret = os.environ.get("WEBHOOK_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("WEBHOOK_SECRET must contain at least 32 characters")
    return secret
