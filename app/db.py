from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = sessionmaker(
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def make_engine():
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


def get_engine():
    global _engine
    if _engine is None:
        _engine = make_engine()
        _SessionLocal.configure(bind=_engine)
    return _engine


def SessionLocal() -> Session:
    get_engine()
    return _SessionLocal()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
