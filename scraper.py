import os
from datetime import datetime
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import MessageMediaDocument, DocumentAttributeVideo, DocumentAttributeFilename
from sqlmodel import Session, select

from database import engine, MediaItem, init_db

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
SESSION_STRING = os.environ["TELEGRAM_SESSION"]
CHANNEL_USERNAME = os.environ["TELEGRAM_CHANNEL"]  # e.g. "somechannel" (no @)


def build_client() -> TelegramClient:
    return TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


async def scrape_channel(limit: int = 200) -> int:
    """
    Fetches the most recent `limit` messages from CHANNEL_USERNAME that
    aren't already stored, and saves their metadata.
    Returns the number of new items saved.
    """
    init_db()
    client = build_client()
    saved = 0

    async with client:
        with Session(engine) as db:
            existing_ids = set(
                db.exec(
                    select(MediaItem.message_id).where(
                        MediaItem.channel_username == CHANNEL_USERNAME
                    )
                ).all()
            )

            async for msg in client.iter_messages(CHANNEL_USERNAME, limit=limit):
                if msg.id in existing_ids:
                    continue

                item = None

                # Case 1: video/document media
                if msg.media and isinstance(msg.media, MessageMediaDocument) and msg.document:
                    doc = msg.document
                    file_name = None
                    duration = None
                    for attr in doc.attributes:
                        if isinstance(attr, DocumentAttributeFilename):
                            file_name = attr.file_name
                        if isinstance(attr, DocumentAttributeVideo):
                            duration = attr.duration

                    item = MediaItem(
                        channel_username=CHANNEL_USERNAME,
                        message_id=msg.id,
                        title=(msg.text or file_name or f"Untitled #{msg.id}")[:200],
                        caption=msg.text,
                        media_type="video" if duration else "document",
                        file_name=file_name,
                        mime_type=doc.mime_type,
                        file_size=doc.size,
                        duration=duration,
                        date=msg.date.isoformat() if msg.date else None,
                    )

                # Case 2: plain text message containing a link, no media
                elif msg.text and ("http://" in msg.text or "https://" in msg.text):
                    item = MediaItem(
                        channel_username=CHANNEL_USERNAME,
                        message_id=msg.id,
                        title=msg.text[:200],
                        caption=msg.text,
                        media_type="link",
                        url=msg.text.strip(),
                        date=msg.date.isoformat() if msg.date else None,
                    )

                if item:
                    db.add(item)
                    saved += 1

            db.commit()

    return saved
