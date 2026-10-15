"""Password hashing, JWT creation and FastAPI authentication dependency."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User


ALGORITHM = "HS256"
password_hasher = PasswordHasher()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerificationError):
        return False


def create_access_token(
    user: User,
    *,
    now: datetime | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    settings = get_settings()
    issued_at = now or datetime.now(timezone.utc)
    expiration = issued_at + (expires_delta or timedelta(minutes=settings.jwt_expire_minutes))
    return jwt.encode(
        {
            "sub": str(user.id),
            "ver": user.token_version,
            "iat": issued_at,
            "exp": expiration,
        },
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def unauthorized(detail: str = "Invalid or expired authentication token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        user_id = UUID(payload["sub"])
        token_version = payload["ver"]
        if not isinstance(token_version, int):
            raise ValueError
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized() from None

    user = db.get(User, user_id)
    if user is None or user.token_version != token_version:
        raise unauthorized()
    return user
