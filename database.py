import os
from typing import Optional
from sqlmodel import SQLModel, Field, create_engine, Session

# DATABASE_URL example (Neon/Supabase Postgres):
# postgresql://user:password@host/dbname?sslmode=require
DATABASE_URL = os.environ["DATABASE_URL"]

# Postgres providers sometimes give "postgres://" — SQLAlchemy wants "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, echo=False)


class MediaItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)

    # Telegram identifiers — needed to re-fetch/stream the file later
    channel_username: str = Field(index=True)
    message_id: int = Field(index=True)

    title: str
    caption: Optional[str] = None
    media_type: str  # "video", "document", "link"
    url: Optional[str] = None  # for plain links posted as text

    file_name: Optional[str] = None
    mime_type: Optional[str] = None
    file_size: Optional[int] = None  # bytes
    duration: Optional[int] = None   # seconds, if available
    thumbnail_path: Optional[str] = None

    date: Optional[str] = None  # ISO string of when it was posted


def init_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
