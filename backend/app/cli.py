"""Administrative commands for installations without public registration."""

import argparse
import getpass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.database import get_engine
from app.models import User


def create_admin(email: str, password: str) -> None:
    normalized_email = email.strip().lower()
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("A valid email is required")
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")

    with Session(get_engine()) as db:
        if db.scalar(select(User.id).where(func.lower(User.email) == normalized_email)):
            raise ValueError("A user with this email already exists")
        db.add(User(
            email=normalized_email,
            password_hash=hash_password(password),
            is_admin=True,
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise ValueError("A user with this email already exists") from None


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create-admin")
    create_parser.add_argument("--email", required=True)
    create_parser.add_argument("--password", help="Omit to enter it without terminal echo")
    args = parser.parse_args()

    if args.command == "create-admin":
        password = args.password or getpass.getpass("Password: ")
        create_admin(args.email, password)
        print(f"Administrator {args.email.strip().lower()} created")


if __name__ == "__main__":
    main()
