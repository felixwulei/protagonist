"""Protagonist LLM Proxy Server.

OpenAI-compatible proxy that forwards requests using our API key.
Users authenticate with their device_id — no OpenAI key needed.

Usage:
    uvicorn server.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
import time
import json
import sqlite3
import hashlib
import httpx
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse

# --------------- Config ---------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = "https://api.openai.com/v1"
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")  # Free tier: 2000 queries/month
DAILY_TOKEN_LIMIT = int(os.getenv("DAILY_TOKEN_LIMIT", "100000"))  # per device
DB_PATH = os.getenv("PROXY_DB_PATH", "proxy.db")

# --------------- Database ---------------


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db():
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            date TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_usage_device_date
            ON usage(device_id, date);
    """)
    conn.close()


# --------------- Auth ---------------


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _extract_device_id(request: Request) -> str:
    """Extract device_id from Authorization: Bearer {device_id}."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization header")
    device_id = auth[7:].strip()
    if not device_id:
        raise HTTPException(401, "Empty device_id")
    return device_id


def _check_device(device_id: str):
    """Verify device exists and is within daily limits."""
    conn = _get_db()
    try:
        device = conn.execute(
            "SELECT * FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()
        if not device:
            raise HTTPException(401, "Unknown device. Call /v1/register first.")

        # Update last_seen
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE devices SET last_seen = ? WHERE device_id = ?",
            (now, device_id),
        )

        # Check daily usage
        row = conn.execute(
            "SELECT COALESCE(SUM(tokens_in + tokens_out), 0) as total "
            "FROM usage WHERE device_id = ? AND date = ?",
            (device_id, _today()),
        ).fetchone()
        daily_total = row["total"] if row else 0
        if daily_total >= DAILY_TOKEN_LIMIT:
            raise HTTPException(
                429,
                f"Daily token limit reached ({DAILY_TOKEN_LIMIT}). Resets at midnight UTC.",
            )

        conn.commit()
    finally:
        conn.close()


def _record_usage(device_id: str, endpoint: str, tokens_in: int, tokens_out: int):
    """Record token usage."""
    conn = _get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO usage (device_id, date, endpoint, tokens_in, tokens_out, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (device_id, _today(), endpoint, tokens_in, tokens_out, now),
        )
        conn.commit()
    finally:
        conn.close()


# --------------- App ---------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db()
    yield


app = FastAPI(title="Protagonist Proxy", lifespan=lifespan)


# --------------- Routes ---------------


@app.post("/v1/register")
async def register_device(request: Request):
    """Register a new device."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    device_id = body.get("device_id", "")
    if not device_id:
        raise HTTPException(400, "device_id is required")

    conn = _get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        existing = conn.execute(
            "SELECT * FROM devices WHERE device_id = ?", (device_id,)
        ).fetchone()

        if existing:
            return {"status": "already_registered", "device_id": device_id}

        conn.execute(
            "INSERT INTO devices (device_id, created_at, last_seen) VALUES (?, ?, ?)",
            (device_id, now, now),
        )
        conn.commit()
        return {"status": "registered", "device_id": device_id}
    finally:
        conn.close()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """Proxy chat completions to OpenAI."""
    device_id = _extract_device_id(request)
    _check_device(device_id)

    body = await request.json()
    is_stream = body.get("stream", False)

    async with httpx.AsyncClient(timeout=120.0) as client:
        if is_stream:
            # Streaming response
            async def stream_generator():
                tokens_in = 0
                tokens_out = 0
                async with client.stream(
                    "POST",
                    f"{OPENAI_BASE_URL}/chat/completions",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type": "application/json",
                    },
                ) as resp:
                    if resp.status_code != 200:
                        error_body = await resp.aread()
                        yield f"data: {error_body.decode()}\n\n"
                        return
                    async for line in resp.aiter_lines():
                        if line:
                            yield f"{line}\n"
                            # Try to extract usage from final chunk
                            if line.startswith("data: ") and line != "data: [DONE]":
                                try:
                                    chunk = json.loads(line[6:])
                                    usage = chunk.get("usage")
                                    if usage:
                                        tokens_in = usage.get("prompt_tokens", 0)
                                        tokens_out = usage.get("completion_tokens", 0)
                                except (json.JSONDecodeError, KeyError):
                                    pass
                        yield "\n"

                _record_usage(device_id, "chat/completions", tokens_in, tokens_out)

            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        else:
            # Non-streaming
            resp = await client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
            )

            if resp.status_code != 200:
                raise HTTPException(resp.status_code, resp.json())

            data = resp.json()

            # Record usage
            usage = data.get("usage", {})
            _record_usage(
                device_id,
                "chat/completions",
                usage.get("prompt_tokens", 0),
                usage.get("completion_tokens", 0),
            )

            return JSONResponse(data)


@app.post("/v1/audio/transcriptions")
async def audio_transcriptions(request: Request):
    """Proxy audio transcriptions to OpenAI Whisper."""
    device_id = _extract_device_id(request)
    _check_device(device_id)

    # Forward the multipart form data as-is
    content_type = request.headers.get("content-type", "")
    raw_body = await request.body()

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{OPENAI_BASE_URL}/audio/transcriptions",
            content=raw_body,
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": content_type,
            },
        )

        if resp.status_code != 200:
            raise HTTPException(resp.status_code, resp.json())

        data = resp.json()

        # Estimate tokens for Whisper (rough: ~1 token per 4 chars)
        text = data.get("text", "")
        estimated_tokens = max(1, len(text) // 4)
        _record_usage(device_id, "audio/transcriptions", estimated_tokens, 0)

        return JSONResponse(data)


@app.post("/v1/search")
async def web_search(request: Request):
    """Web search via Brave Search API."""
    device_id = _extract_device_id(request)
    _check_device(device_id)

    body = await request.json()
    query = body.get("query", "")
    if not query:
        raise HTTPException(400, "query is required")

    count = min(body.get("count", 5), 10)

    if not BRAVE_API_KEY:
        raise HTTPException(503, "Search not configured on server")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": count},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": BRAVE_API_KEY,
            },
        )

        if resp.status_code != 200:
            raise HTTPException(resp.status_code, f"Brave Search error: {resp.text}")

        data = resp.json()
        results = []
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", ""),
            })

        _record_usage(device_id, "search", 1, 0)
        return {"results": results}


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/v1/usage/{device_id}")
async def get_usage(device_id: str):
    """Get usage stats for a device."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(tokens_in + tokens_out), 0) as total "
            "FROM usage WHERE device_id = ? AND date = ?",
            (device_id, _today()),
        ).fetchone()
        daily_total = row["total"] if row else 0
        return {
            "device_id": device_id,
            "date": _today(),
            "tokens_used": daily_total,
            "tokens_limit": DAILY_TOKEN_LIMIT,
            "tokens_remaining": max(0, DAILY_TOKEN_LIMIT - daily_total),
        }
    finally:
        conn.close()
