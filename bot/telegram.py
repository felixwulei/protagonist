"""Telegram bot module — importable by the main app."""
from __future__ import annotations

import os
import asyncio
import random
import base64
from datetime import datetime

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from core.agent import (
    respond, respond_to_photo, extract_promises,
    follow_up_on_promise, checkin, write_milestone_letter,
    MILESTONE_COUNTS,
)
from core.state import UserState

from app import config

# --------------- State ---------------

state = UserState()
_checkin_tasks: dict[str, asyncio.Task] = {}


# --------------- Helpers ---------------

def _user_id(update: Update) -> str:
    return f"tg:{update.effective_user.id}"


async def _keep_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        while True:
            await context.bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def _send_parts(context: ContextTypes.DEFAULT_TYPE, chat_id: int, parts: list[str]):
    for i, text in enumerate(parts):
        await context.bot.send_chat_action(chat_id, "typing")
        delay = max(0.5, min(3.0, len(text) * 0.12)) + random.uniform(-0.2, 0.4)
        await asyncio.sleep(max(0.3, delay))
        await context.bot.send_message(chat_id, text)
        if i < len(parts) - 1:
            await asyncio.sleep(random.uniform(0.2, 0.6))


# --------------- Handlers ---------------

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = _user_id(update)
    chat_id = update.effective_chat.id

    greetings = [
        ["嘿", "你来了"],
        ["哟", "终于来找我了"],
        ["嘿嘿", "等你半天了"],
    ]
    parts = random.choice(greetings)
    await _send_parts(context, chat_id, parts)
    for p in parts:
        state.add_message(uid, "friend", p)

    await asyncio.sleep(1.0)
    await context.bot.send_chat_action(chat_id, "typing")
    await asyncio.sleep(1.2)
    q = "你现在什么状态"
    await context.bot.send_message(chat_id, q)
    state.add_message(uid, "friend", q)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = _user_id(update)
    chat_id = update.effective_chat.id
    text = update.message.text

    state.add_message(uid, "user", text)

    if state.first_message_time(uid) is None:
        state.set_meta(uid, "first_message_time", str(datetime.now().timestamp()))

    count = state.message_count(uid)

    typing_task = asyncio.create_task(_keep_typing(context, chat_id))
    try:
        history = state.get_history(uid)
        parts = await respond(history[:-1], text)
    finally:
        typing_task.cancel()

    await _send_parts(context, chat_id, parts)
    for p in parts:
        state.add_message(uid, "friend", p)

    if count % 10 == 0 and count > 0:
        asyncio.create_task(_extract_promises(uid))

    if count in MILESTONE_COUNTS and count not in state.milestones_sent(uid):
        state.mark_milestone(uid, count)
        asyncio.create_task(_send_milestone(uid, chat_id, context))

    _schedule_checkin(uid, chat_id, context)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = _user_id(update)
    chat_id = update.effective_chat.id

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    data = await file.download_as_bytearray()
    b64 = base64.b64encode(bytes(data)).decode()

    state.add_message(uid, "user", "[photo]", "photo")

    typing_task = asyncio.create_task(_keep_typing(context, chat_id))
    try:
        history = state.get_history(uid)
        parts = await respond_to_photo(history, b64)
    finally:
        typing_task.cancel()

    await _send_parts(context, chat_id, parts)
    for p in parts:
        state.add_message(uid, "friend", p)
    _schedule_checkin(uid, chat_id, context)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = _user_id(update)
    chat_id = update.effective_chat.id

    file = await context.bot.get_file(update.message.voice.file_id)
    data = await file.download_as_bytearray()

    import tempfile
    from core.agent import get_client

    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(bytes(data))
            f.flush()
            transcript = await get_client().audio.transcriptions.create(
                model="whisper-1",
                file=open(f.name, "rb"),
                language="zh",
            )
            os.unlink(f.name)
            text = transcript.text
    except Exception as e:
        print(f"[voice] Transcription error: {e}")
        text = ""

    if not text:
        await context.bot.send_message(chat_id, "没听清 再说一遍？")
        return

    state.add_message(uid, "user", text, "voice")

    typing_task = asyncio.create_task(_keep_typing(context, chat_id))
    try:
        history = state.get_history(uid)
        parts = await respond(history[:-1], text)
    finally:
        typing_task.cancel()

    await _send_parts(context, chat_id, parts)
    for p in parts:
        state.add_message(uid, "friend", p)
    _schedule_checkin(uid, chat_id, context)


# --------------- Background Tasks ---------------

async def _extract_promises(uid: str):
    try:
        history = state.get_history(uid)
        new_promises = await extract_promises(history)
        for p in new_promises:
            state.add_promise(uid, p.get("thing", ""), p.get("original", ""))
    except Exception as e:
        print(f"[promise] Error for {uid}: {e}")


async def _send_milestone(uid: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    try:
        await asyncio.sleep(5)
        announce = ["诶 等一下", "我想跟你说点东西"]
        await _send_parts(context, chat_id, announce)
        for p in announce:
            state.add_message(uid, "friend", p)

        await asyncio.sleep(2)
        history = state.get_history(uid)
        first_time = state.first_message_time(uid) or datetime.now().timestamp()
        days = max(1, int((datetime.now().timestamp() - first_time) / 86400))
        letter = await write_milestone_letter(history, days)

        await context.bot.send_chat_action(chat_id, "typing")
        await asyncio.sleep(2)
        await context.bot.send_message(chat_id, letter)
        state.add_message(uid, "friend", letter)
        print(f"[milestone] Sent letter to {uid} at {state.message_count(uid)} messages")
    except Exception as e:
        print(f"[milestone] Error: {e}")


def _schedule_checkin(uid: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    if uid in _checkin_tasks and not _checkin_tasks[uid].done():
        _checkin_tasks[uid].cancel()
    _checkin_tasks[uid] = asyncio.create_task(_do_checkin(uid, chat_id, context))


async def _do_checkin(uid: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    wait = random.uniform(180, 480)
    await asyncio.sleep(wait)
    history = state.get_history(uid)
    if not history:
        return

    promises = state.get_promises(uid)
    if promises and random.random() < 0.5:
        promise = random.choice(promises)
        parts = await follow_up_on_promise(history, promise)
        print(f"[proactive] Promise follow-up for {uid}")
        await _send_parts(context, chat_id, parts)
        for p in parts:
            state.add_message(uid, "friend", p)
        return

    parts = await checkin(history)
    if parts:
        print(f"[proactive] Check-in for {uid}")
        await _send_parts(context, chat_id, parts)
        for p in parts:
            state.add_message(uid, "friend", p)


# --------------- Factory ---------------

def create_bot(token: str) -> Application:
    """Create and configure the Telegram bot application."""
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    return app
