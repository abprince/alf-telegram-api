# Telegram Media Catalog API

FastAPI backend that scrapes a Telegram channel's media/links and serves
them to your Flutter app, including proxied video streaming.

## 1. Get Telegram API credentials

1. Go to https://my.telegram.org -> "API Development Tools"
2. Create an app, note down `api_id` and `api_hash`

## 2. Generate a session string (do this on your own PC, once)

```bash
pip install telethon
python generate_session.py
```

It'll ask for your phone number and the login code Telegram texts/sends
you. It prints a long session string at the end — copy it. This is how
Render logs in as your Telegram user account without you being present.

**Treat this string like a password.** Anyone with it can access your
Telegram account. Don't commit it to git.

## 3. Get a free Postgres database (NOT Render's — it expires)

Use **Neon** (neon.tech) or **Supabase** (supabase.com) — both have free
tiers that don't expire mid-semester. Create a project, copy the
connection string, it'll look like:

```
postgresql://user:password@host/dbname?sslmode=require
```

That's your `DATABASE_URL`.

> Why not just use SQLite on Render? Render's free web services have an
> **ephemeral filesystem** — any local file (including a SQLite DB) gets
> wiped on restarts/redeploys, which happen constantly on the free tier's
> sleep/wake cycle. An external Postgres survives that.

## 4. Deploy to Render

1. Push this folder to a GitHub repo
2. On Render: New -> Web Service -> connect the repo (it'll pick up `render.yaml`)
3. Set the environment variables when prompted:
   - `TELEGRAM_API_ID`
   - `TELEGRAM_API_HASH`
   - `TELEGRAM_SESSION` (from step 2)
   - `TELEGRAM_CHANNEL` (channel username, no `@`)
   - `DATABASE_URL` (from step 3)
   - `ADMIN_KEY` (make up any long random string — protects your scrape endpoint)
4. Deploy. First scrape hasn't run yet — your `/movies` list will be empty
   until you trigger one (next step).

## 5. Keep it alive + auto-scrape with an external cron ping

Use **cron-job.org** (free) to hit this URL every 10–14 minutes:

```
https://YOUR-APP.onrender.com/admin/scrape?key=YOUR_ADMIN_KEY
```

This does double duty: it stops Render's free tier from sleeping, AND
it's what actually triggers new-message scraping (there's no background
scheduler running inside the app — the cron ping IS the scheduler).

## 6. API endpoints for your Flutter app

- `GET /movies` — list of scraped items (title, type, duration, file size, etc.)
- `GET /movies/{id}` — one item's full metadata
- `GET /movies/{id}/stream` — streams the video bytes directly (point a
  video player widget's URL at this)

In Flutter, `video_player` or `chewie` can usually point straight at the
`/stream` URL like any other network video.

## Known limitations (fine for a uni project, worth mentioning in your report)

- `/stream` doesn't implement proper HTTP range requests yet, so
  seeking/scrubbing in the video player may not work smoothly — only
  linear playback. Implementing range support is a good "future work"
  bullet point if you want to extend this.
- Render free tier cold-starts after 15 min idle even with the cron
  ping if the ping fails once — expect an occasional slow first request.
- Only tested against **public** channels the account can view without
  joining restrictions.

## Legal note

This only works cleanly, and won't get your Telegram account or hosting
flagged, if the channel you scrape is one you control or has content
you have rights to distribute. Keep that in mind for the channel you
demo with.
