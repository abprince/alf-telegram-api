import os
from typing import Optional
from sqlmodel import SQLModel, Field, create_engine, Session

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Add DATABASE_URL in Render Environment Variables."
    )

# Postgres providers sometimes give "postgres://" — SQLAlchemy wants "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, echo=False)


class MediaItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    channel_username: str = Field(index=True)
    message_id: int = Field(index=True)

    title: str
    caption: Optional[str] = None
    media_type: str
    url: Optional[str] = None

    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    duration: Optional[int] = None
    thumbnail_path: Optional[str] = None

    date: Optional[str] = None


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session