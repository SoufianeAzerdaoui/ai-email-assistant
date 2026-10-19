"""Environment-backed application settings."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

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


@dataclass(frozen=True)
class N8nDraftSettings:
    webhook_url: str
    webhook_secret: str
    timeout_seconds: float


@dataclass(frozen=True)
class N8nGmailSendSettings:
    webhook_url: str
    webhook_secret: str
    timeout_seconds: float


@lru_cache
def get_n8n_draft_settings() -> N8nDraftSettings:
    webhook_url = os.environ.get("N8N_DRAFT_WEBHOOK_URL", "")
    parsed_url = urlparse(webhook_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise RuntimeError("N8N_DRAFT_WEBHOOK_URL must be an HTTP(S) URL")
    if not parsed_url.path.startswith("/webhook/"):
        raise RuntimeError("N8N_DRAFT_WEBHOOK_URL must use the production /webhook/ path")
    webhook_secret = os.environ.get("N8N_WEBHOOK_SECRET", "")
    if len(webhook_secret) < 32:
        raise RuntimeError("N8N_WEBHOOK_SECRET must contain at least 32 characters")
    try:
        timeout_seconds = float(os.environ.get("N8N_REQUEST_TIMEOUT_SECONDS", "10"))
    except ValueError as error:
        raise RuntimeError("N8N_REQUEST_TIMEOUT_SECONDS must be a number") from error
    if timeout_seconds <= 0:
        raise RuntimeError("N8N_REQUEST_TIMEOUT_SECONDS must be greater than zero")
    return N8nDraftSettings(webhook_url, webhook_secret, timeout_seconds)


@lru_cache
def get_n8n_gmail_send_settings() -> N8nGmailSendSettings:
    webhook_url = os.environ.get("N8N_GMAIL_SEND_WEBHOOK_URL", "")
    parsed_url = urlparse(webhook_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise RuntimeError("N8N_GMAIL_SEND_WEBHOOK_URL must be an HTTP(S) URL")
    if not parsed_url.path.startswith("/webhook/"):
        raise RuntimeError("N8N_GMAIL_SEND_WEBHOOK_URL must use the production /webhook/ path")
    webhook_secret = os.environ.get("N8N_WEBHOOK_SECRET", "")
    if len(webhook_secret) < 32:
        raise RuntimeError("N8N_WEBHOOK_SECRET must contain at least 32 characters")
    try:
        timeout_seconds = float(os.environ.get("N8N_REQUEST_TIMEOUT_SECONDS", "10"))
    except ValueError as error:
        raise RuntimeError("N8N_REQUEST_TIMEOUT_SECONDS must be a number") from error
    if timeout_seconds <= 0:
        raise RuntimeError("N8N_REQUEST_TIMEOUT_SECONDS must be greater than zero")
    return N8nGmailSendSettings(webhook_url, webhook_secret, timeout_seconds)
