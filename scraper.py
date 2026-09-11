import os
import re
import asyncio
import mimetypes
from urllib.parse import urlparse, parse_qs
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

# How many bot-relay buttons to trigger per scrape run. Keep this small —
# rapid-fire /start requests to the same bot(s) risk FloodWaitErrors or
# tripping anti-abuse behavior. A cron ping every ~10-15 min processing a
# handful at a time gets through a backlog steadily without hammering it.
MAX_BOT_FETCHES_PER_RUN = 5
BOT_REPLY_WAIT_SECONDS = 12
BOT_REPLY_POLL_INTERVAL = 2


def build_client() -> TelegramClient:
    return TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


def extract_video_links(text: str):
    """
    Returns a list of (url, label) pairs from plain pasted links in text.
    """
    results = []
    for line in text.splitlines():
        for match in VIDEO_LINK_RE.finditer(line):
            url = match.group(0)
            label = line.replace(url, "").strip(" -:|\u2022\t")
            results.append((url, label))
    return results


def parse_bot_deeplink(url: str):
    """
    Given a button URL like https://t.me/SomeBot?start=xyz123, returns
    (bot_username, start_payload), or (None, None) if it doesn't match.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return None, None

    if parsed.netloc not in ("t.me", "telegram.me", "telegram.dog"):
        return None, None

    bot_username = parsed.path.strip("/")
    if not bot_username:
        return None, None

    qs = parse_qs(parsed.query)
    payload = qs.get("start", [None])[0]
    if not payload:
        return None, None

    return bot_username, payload


def build_item_from_message(msg, channel_username, origin_message_id,
                             source_chat, title_hint=None):
    """
    Turns a Telegram message (from the channel OR from a bot's reply) into
    one or more MediaItem rows, reusing the same media/link detection logic
    either way.
    """
    items = []

    if msg.media and isinstance(msg.media, MessageMediaDocument) and msg.document:
        doc = msg.document
        file_name = None
        duration = None
        for attr in doc.attributes:
            if isinstance(attr, DocumentAttributeFilename):
                file_name = attr.file_name
            if isinstance(attr, DocumentAttributeVideo):
                duration = attr.duration

        items.append(MediaItem(
            channel_username=channel_username,
            message_id=origin_message_id,
            source_chat=source_chat,
            source_message_id=msg.id,
            title=(title_hint or (msg.text.splitlines()[0] if msg.text else None) or file_name or f"Untitled #{origin_message_id}")[:200],
            caption=msg.text,
            media_type="video" if duration else "document",
            file_name=file_name,
            mime_type=doc.mime_type,
            file_size=doc.size,
            duration=duration,
            date=msg.date.isoformat() if msg.date else None,
        ))

    elif msg.text:
        links = extract_video_links(msg.text)
        base_title = title_hint or (msg.text.splitlines()[0][:200] if msg.text.strip() else f"Untitled #{origin_message_id}")

        for url, label in links:
            file_name = url.split("/")[-1].split("?")[0]
            mime_type, _ = mimetypes.guess_type(file_name)
            items.append(MediaItem(
                channel_username=channel_username,
                message_id=origin_message_id,
                source_chat=source_chat,
                source_message_id=msg.id,
                title=(f"{base_title} ({label})" if label else base_title)[:200],
                caption=msg.text,
                media_type="link",
                url=url,
                file_name=file_name,
                mime_type=mime_type,
                date=msg.date.isoformat() if msg.date else None,
            ))

    return items


async def fetch_via_bot(client, bot_username, payload):
    """
    Sends /start <payload> to a bot (simulating tapping the channel button)
    and waits for its reply. Returns the reply Message, or None on timeout.
    """
    bot = await client.get_entity(bot_username)

    recent = await client.get_messages(bot, limit=1)
    last_id = recent[0].id if recent else 0

    await client.send_message(bot, f"/start {payload}")

    waited = 0
    while waited < BOT_REPLY_WAIT_SECONDS:
        await asyncio.sleep(BOT_REPLY_POLL_INTERVAL)
        waited += BOT_REPLY_POLL_INTERVAL
        new_msgs = await client.get_messages(bot, min_id=last_id, limit=5)
        if new_msgs:
            # newest first; take the most recent reply
            return new_msgs[0]

    return None


async def scrape_channel(limit: int = 200) -> int:
    """
    Fetches recent channel posts that aren't already fully processed. Posts
    with direct media/link get stored immediately. Posts with buttons that
    deep-link to a bot get EVERY button triggered (e.g. EP01, EP02, EP03...),
    each up to MAX_BOT_FETCHES_PER_RUN per run, tracked individually by
    payload so a partially-processed post picks up where it left off on the
    next run instead of being skipped or re-fetched.
    """
    init_db()
    client = build_client()
    saved = 0
    bot_fetches_used = 0

    async with client:
        with Session(engine) as db:
            existing_rows = db.exec(
                select(MediaItem.message_id, MediaItem.bot_payload).where(
                    MediaItem.channel_username == CHANNEL_USERNAME
                )
            ).all()

            # message_ids fully covered by a direct media/link item (no button involved)
            direct_done_ids = {mid for mid, payload in existing_rows if payload is None}

            # payloads already fetched successfully, per message_id
            done_payloads_by_msg = {}
            for mid, payload in existing_rows:
                if payload:
                    done_payloads_by_msg.setdefault(mid, set()).add(payload)

            async for msg in client.iter_messages(CHANNEL_USERNAME, limit=limit):
                if msg.id in direct_done_ids:
                    continue  # fully handled by direct media/link already

                items_to_add = []
                already_done = done_payloads_by_msg.get(msg.id, set())

                # Case 1 & 2: direct media or a plain pasted link in the post itself.
                # Only relevant the first time we see this message (no button progress yet).
                if not already_done:
                    direct_items = build_item_from_message(msg, CHANNEL_USERNAME, msg.id, source_chat=CHANNEL_USERNAME)
                    items_to_add.extend(direct_items)

                # Case 3: EVERY button on the post that deep-links to a bot
                # (a single post often has EP01/EP02/EP03/... as separate buttons)
                if not items_to_add and msg.buttons:
                    stop = False
                    for row in msg.buttons:
                        if stop:
                            break
                        for b in row:
                            if bot_fetches_used >= MAX_BOT_FETCHES_PER_RUN:
                                stop = True
                                break

                            url = getattr(b, "url", None)
                            if not url:
                                continue
                            bot_username, payload = parse_bot_deeplink(url)
                            if not bot_username or not payload or payload in already_done:
                                continue  # not a bot deep-link, or already fetched in a prior run

                            bot_fetches_used += 1
                            try:
                                reply = await fetch_via_bot(client, bot_username, payload)
                            except Exception:
                                reply = None  # flood wait, needs subscribe, etc. — retry next run

                            if reply:
                                title_hint = b.text or (msg.text.splitlines()[0] if msg.text else None)
                                new_items = build_item_from_message(
                                    reply, CHANNEL_USERNAME, msg.id,
                                    source_chat=bot_username, title_hint=title_hint,
                                )
                                for it in new_items:
                                    it.bot_payload = payload
                                items_to_add.extend(new_items)
                                already_done.add(payload)

                for item in items_to_add:
                    db.add(item)
                    saved += 1

            db.commit()

    return saved