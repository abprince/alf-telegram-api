import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from database import engine, init_db, MediaItem
from scraper import build_client, scrape_channel, CHANNEL_USERNAME

ADMIN_KEY = os.environ["ADMIN_KEY"]  # used to protect /admin/scrape from randoms

telethon_client = None  # created on startup, reused for streaming


@asynccontextmanager
async def lifespan(app: FastAPI):
    global telethon_client
    init_db()
    telethon_client = build_client()
    await telethon_client.start()
    yield
    await telethon_client.disconnect()


app = FastAPI(title="Telegram Media Catalog API", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/admin/scrape")
async def trigger_scrape(key: str):
    """
    Call this from your external cron pinger (e.g. every 10-14 min).
    Doubles as your keep-alive ping AND your scrape trigger.
    """
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="bad key")
    new_count = await scrape_channel()
    return {"new_items": new_count}


@app.get("/movies")
def list_movies(skip: int = 0, limit: int = 50):
    with Session(engine) as db:
        items = db.exec(
            select(MediaItem).offset(skip).limit(limit).order_by(MediaItem.id.desc())
        ).all()
        return items


@app.get("/movies/{item_id}")
def get_movie(item_id: int):
    with Session(engine) as db:
        item = db.get(MediaItem, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="not found")
        return item


@app.get("/movies/{item_id}/stream")
async def stream_movie(item_id: int, range: str = Header(default=None)):
    with Session(engine) as db:
        item = db.get(MediaItem, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="not found")
        if item.media_type not in ("video", "document"):
            raise HTTPException(status_code=400, detail="this item is a link, not a streamable file")

    # Fetch the live message object again so Telethon has a fresh file reference
    msg = await telethon_client.get_messages(CHANNEL_USERNAME, ids=item.message_id)
    if not msg or not msg.media:
        raise HTTPException(status_code=404, detail="media no longer available on Telegram")

    async def file_chunks():
        async for chunk in telethon_client.iter_download(msg.media, chunk_size=256 * 1024):
            yield chunk

    return StreamingResponse(
        file_chunks(),
        media_type=item.mime_type or "video/mp4",
        headers={
            "Content-Length": str(item.file_size) if item.file_size else "",
            "Accept-Ranges": "bytes",
        },
    )
