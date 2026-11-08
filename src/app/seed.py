"""Fake demo data for local development: one user and two notes."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db import Note, User
from app.security import hash_password

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo-password-123"  # noqa: S105 - fake seed data, documented in the README


async def seed(engine: AsyncEngine) -> bool:
    """Adds the demo user once. Returns False when it already exists."""
    async with async_sessionmaker(engine)() as session, session.begin():
        existing = await session.execute(select(User.id).where(User.email == DEMO_EMAIL))
        if existing.scalar_one_or_none() is not None:
            return False
        user = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PASSWORD))
        session.add(user)
        await session.flush()
        session.add_all(
            [
                Note(user_id=user.id, title="Welcome", body="This is fake seed data."),
                Note(user_id=user.id, title="Try the API", body="See /docs for every endpoint."),
            ]
        )
    return True
