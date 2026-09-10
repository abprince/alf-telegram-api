import os
import re
import mimetypes
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

# Only pick up links that actually point at a video file, not every URL
# in the message (skip promo links, @channel mentions, t.me links, etc.)
VIDEO_LINK_RE = re.compile(
    r"https?://\S+?\.(?:mp4|mkv|avi|mov|m3u8|webm)(?:\?\S*)?",
    re.IGNORECASE,
)


def build_client() -> TelegramClient:
    return TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


def extract_video_links(text: str):
    """
    Returns a list of (url, label) pairs. `label` is whatever text shared
    the line with the link (often a quality tag like "720p" or "Episode 3"),
    stripped of the URL itself, so you get something usable as a title hint.
    """
    results = []
    for line in text.splitlines():
        for match in VIDEO_LINK_RE.finditer(line):
            url = match.group(0)
            label = line.replace(url, "").strip(" -:|\u2022\t")
            results.append((url, label))
    return results


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

                items_to_add = []

                # Case 1: video/document media actually uploaded to Telegram
                if msg.media and isinstance(msg.media, MessageMediaDocument) and msg.document:
                    doc = msg.document
                    file_name = None
                    duration = None
                    for attr in doc.attributes:
                        if isinstance(attr, DocumentAttributeFilename):
                            file_name = attr.file_name
                        if isinstance(attr, DocumentAttributeVideo):
                            duration = attr.duration

                    items_to_add.append(MediaItem(
                        channel_username=CHANNEL_USERNAME,
                        message_id=msg.id,
                        title=(msg.text.splitlines()[0] if msg.text else file_name or f"Untitled #{msg.id}")[:200],
                        caption=msg.text,
                        media_type="video" if duration else "document",
                        file_name=file_name,
                        mime_type=doc.mime_type,
                        file_size=doc.size,
                        duration=duration,
                        date=msg.date.isoformat() if msg.date else None,
                    ))

                # Case 2: plain text message with one or more direct video links
                # (this will be the common case for most channels — .mp4/.mkv
                # links to files hosted elsewhere, not uploaded to Telegram)
                elif msg.text:
                    links = extract_video_links(msg.text)
                    base_title = msg.text.splitlines()[0][:200] if msg.text.strip() else f"Untitled #{msg.id}"

                    for url, label in links:
                        file_name = url.split("/")[-1].split("?")[0]
                        mime_type, _ = mimetypes.guess_type(file_name)
                        items_to_add.append(MediaItem(
                            channel_username=CHANNEL_USERNAME,
                            message_id=msg.id,
                            title=(f"{base_title} ({label})" if label else base_title)[:200],
                            caption=msg.text,
                            media_type="link",
                            url=url,
                            file_name=file_name,
                            mime_type=mime_type,
                            date=msg.date.isoformat() if msg.date else None,
                        ))

                for item in items_to_add:
                    db.add(item)
                    saved += 1

            db.commit()

    return saved