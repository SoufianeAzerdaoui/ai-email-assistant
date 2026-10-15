"""Authentication endpoints. User creation stays outside the public API."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, unauthorized, verify_password
from app.database import get_db
from app.models import User


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    is_admin: bool


def user_response(user: User) -> UserResponse:
    return UserResponse(id=str(user.id), email=user.email, is_admin=user.is_admin)


@router.post("/login", response_model=TokenResponse)
def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    normalized_email = credentials.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == normalized_email))
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise unauthorized("Invalid email or password")
    return TokenResponse(access_token=create_access_token(user))


@router.get("/me", response_model=UserResponse)
def me(current_user: Annotated[User, Depends(get_current_user)]):
    return user_response(current_user)


@router.post("/logout", status_code=204)
def logout(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    current_user.token_version += 1
    db.commit()
