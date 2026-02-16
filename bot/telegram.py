"""Telegram bot — single source of truth.

Used in two modes:
  Module:     from bot.telegram import create_bot; app = create_bot(token)
  Standalone: python3 -m bot.telegram  (or  python3 telegram/bot.py)
"""
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
    update_user_profile, update_memory_summary,
    update_relationship_narrative, detect_mood,
    extract_shared_references, compose_surprise,
    detect_patterns, share_pattern_insight,
    generate_inner_thought, proactive_followup,
    get_absence_hint, compose_return_message, generate_voice,
    classify_sticker_emotion, pick_response_emotion,
    extract_events as agent_extract_events,
    compose_greeting,
    update_user_story, get_user_story,
    MILESTONE_COUNTS,
)
from core.state import UserState

# --------------- State ---------------

state = UserState()
_checkin_tasks: dict[str, asyncio.Task] = {}
_owner_id: str | None = None  # Set via create_bot(); None = allow all


# --------------- Helpers ---------------

def _is_owner(update: Update) -> bool:
    """Check if the message is from the bot owner."""
    if not _owner_id:
        return True  # No owner set = allow all
    return str(update.effective_user.id) == _owner_id


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


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


async def _send_files(context: ContextTypes.DEFAULT_TYPE, chat_id: int, files: list[str]):
    """Send files — images as photos, others as documents. Clean up temp files afterward."""
    for path in files:
        try:
            if os.path.exists(path):
                ext = os.path.splitext(path)[1].lower()
                with open(path, "rb") as f:
                    if ext in _IMAGE_EXTS:
                        await context.bot.send_photo(chat_id, photo=f)
                    else:
                        await context.bot.send_document(chat_id, document=f, filename=os.path.basename(path))
                os.unlink(path)
        except Exception as e:
            print(f"[telegram] Failed to send file {path}: {e}")


async def _send_as_voice_or_text(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str):
    """Try to send as voice message, fall back to text."""
    voice_path = await generate_voice(text)
    if voice_path:
        try:
            with open(voice_path, "rb") as f:
                await context.bot.send_voice(chat_id, voice=f)
            os.unlink(voice_path)
            return True
        except Exception as e:
            print(f"[voice] Send error: {e}")
    await context.bot.send_message(chat_id, text)
    return False


# --------------- Handlers ---------------

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        await update.message.reply_text("This is a private bot.")
        return
    uid = _user_id(update)
    chat_id = update.effective_chat.id
    state.set_chat_id(uid, chat_id)

    # Simple, natural opening — the onboarding logic is in the SYSTEM prompt
    # (ONBOARDING_HINT injects when profile is empty + count < 10)
    parts = ["嘿", "你是？"]
    await _send_parts(context, chat_id, parts)
    for p in parts:
        state.add_message(uid, "friend", p)


async def handle_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show what the bot remembers about the user."""
    if not _is_owner(update):
        return
    uid = _user_id(update)
    chat_id = update.effective_chat.id
    state.set_chat_id(uid, chat_id)

    profile = state.get_user_profile(uid)
    summary = state.get_memory_summary(uid)
    promises = state.get_promises(uid)
    events = state.get_due_events(uid, "9999-12-31")
    msg_count = state.message_count(uid)

    parts = []
    if profile:
        parts.append(f"🧠 *关于你*\n{profile}")
    if summary:
        parts.append(f"💭 *我记得的事*\n{summary}")
    if promises:
        lines = [f"- {p['thing']}" for p in promises[:8]]
        parts.append(f"📌 *你说过要做的*\n" + "\n".join(lines))
    if events:
        lines = [f"- {e['description']}（{e['trigger_date']}）" for e in events[:8]]
        parts.append(f"📅 *记着的事件*\n" + "\n".join(lines))

    parts.append(f"📊 你跟我说了 {msg_count} 条消息")

    if not profile and not summary:
        await context.bot.send_message(chat_id, "我们才刚认识，还没记住太多东西呢\n多聊聊我就记住了")
    else:
        for p in parts:
            await context.bot.send_message(chat_id, p, parse_mode="Markdown")


async def handle_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear the bot's memory about the user."""
    if not _is_owner(update):
        return
    uid = _user_id(update)
    chat_id = update.effective_chat.id
    state.set_chat_id(uid, chat_id)

    profile = state.get_user_profile(uid)
    summary = state.get_memory_summary(uid)
    if not profile and not summary:
        await context.bot.send_message(chat_id, "本来就没记什么啊")
        return

    state.set_user_profile(uid, "")
    state.set_memory_summary(uid, "")
    state.set_summarized_up_to(uid, 0)
    await context.bot.send_message(chat_id, "好 都忘了\n我们重新认识吧")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        await update.message.reply_text("This is a private bot.")
        return
    uid = _user_id(update)
    chat_id = update.effective_chat.id
    text = update.message.text
    state.set_chat_id(uid, chat_id)

    # --- Absence detection (before storing message) ---
    last_time = state.get_last_message_time(uid)
    absence_hours = 0
    if last_time:
        absence_hours = (datetime.now().timestamp() - last_time) / 3600

    # Long absence (7+ days): send return message first
    if absence_hours > 24 * 7:
        try:
            return_parts = await compose_return_message(uid, absence_hours / 24)
            if absence_hours > 24 * 14 and random.random() < 0.5:
                combined = " ".join(return_parts)
                await _send_as_voice_or_text(context, chat_id, combined)
            else:
                await _send_parts(context, chat_id, return_parts)
            for p in return_parts:
                state.add_message(uid, "friend", p)
            await asyncio.sleep(random.uniform(1.5, 3.0))
        except Exception as e:
            print(f"[return] Error: {e}")

    # Build absence hint for 1-7 day absences
    absence_hint = get_absence_hint(absence_hours) if 24 <= absence_hours <= 24 * 7 else ""

    state.add_message(uid, "user", text)

    if state.first_message_time(uid) is None:
        state.set_meta(uid, "first_message_time", str(datetime.now().timestamp()))

    count = state.message_count(uid)

    # --- "My Story" trigger ---
    _story_triggers = {"我的故事", "给我看看我的故事", "看看我的故事", "my story", "show me my story"}
    if text.strip().lower() in _story_triggers or text.strip() in _story_triggers:
        story = get_user_story(uid)
        if story:
            await context.bot.send_message(chat_id, story)
            state.add_message(uid, "friend", story)
            _schedule_checkin(uid, chat_id, context)
            return
        else:
            # Not enough data yet — let LLM respond naturally
            pass

    typing_task = asyncio.create_task(_keep_typing(context, chat_id))
    try:
        history = state.get_history(uid)
        parts, files = await respond(history[:-1], text, user_id=uid, absence_hint=absence_hint)
    finally:
        typing_task.cancel()

    await _send_parts(context, chat_id, parts)
    for p in parts:
        state.add_message(uid, "friend", p)

    if files:
        await _send_files(context, chat_id, files)

    # Memory updates (background, non-blocking)
    if count % 10 == 0 and count > 0:
        asyncio.create_task(_extract_promises(uid))
    if count % 20 == 0 and count > 0:
        asyncio.create_task(_update_memory(uid))

    if count in MILESTONE_COUNTS and count not in state.milestones_sent(uid):
        state.mark_milestone(uid, count)
        asyncio.create_task(_send_milestone(uid, chat_id, context))

    # Extract events every 5 messages
    if count % 5 == 0 and count > 0:
        asyncio.create_task(_extract_events(uid))

    # Extract shared references every 15 messages
    if count % 15 == 0 and count > 0:
        asyncio.create_task(_extract_shared_refs(uid))

    # Maybe send a sticker reaction (15% chance)
    asyncio.create_task(_maybe_send_sticker(uid, chat_id, context, parts))

    _schedule_checkin(uid, chat_id, context)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    uid = _user_id(update)
    chat_id = update.effective_chat.id
    state.set_chat_id(uid, chat_id)

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
    if not _is_owner(update):
        return
    uid = _user_id(update)
    chat_id = update.effective_chat.id
    state.set_chat_id(uid, chat_id)

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
        parts, files = await respond(history[:-1], text, user_id=uid)
    finally:
        typing_task.cancel()

    await _send_parts(context, chat_id, parts)
    for p in parts:
        state.add_message(uid, "friend", p)

    if files:
        await _send_files(context, chat_id, files)

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


async def _update_memory(uid: str):
    """Update user profile, conversation summary, narrative, mood, patterns, and story (background)."""
    try:
        await update_user_profile(uid)
        await update_memory_summary(uid)
        await update_relationship_narrative(uid)
        await detect_mood(uid)
        await detect_patterns(uid)
        await update_user_story(uid)
    except Exception as e:
        print(f"[memory] Error for {uid}: {e}")


async def _extract_shared_refs(uid: str):
    """Extract inside jokes and memorable moments (background)."""
    try:
        await extract_shared_references(uid)
    except Exception as e:
        print(f"[refs] Error for {uid}: {e}")


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
        await _send_as_voice_or_text(context, chat_id, letter)
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

    count = state.message_count(uid)
    roll = random.random()

    # 5% chance: surprise gift (requires 20+ messages)
    if roll < 0.05 and count >= 20:
        try:
            parts, files = await compose_surprise(uid)
            print(f"[proactive] Surprise for {uid}")
            await _send_parts(context, chat_id, parts)
            for p in parts:
                state.add_message(uid, "friend", p)
            if files:
                await _send_files(context, chat_id, files)
            return
        except Exception as e:
            print(f"[surprise] Error: {e}")

    # 8% chance: pattern insight (requires 50+ messages)
    elif roll < 0.13 and count >= 50:
        try:
            parts = await share_pattern_insight(uid)
            if parts:
                print(f"[proactive] Pattern insight for {uid}")
                await _send_parts(context, chat_id, parts)
                for p in parts:
                    state.add_message(uid, "friend", p)
                return
        except Exception as e:
            print(f"[pattern] Error: {e}")

    # 8% chance: inner thought (requires 30+ messages)
    elif roll < 0.21 and count >= 30:
        try:
            parts = await generate_inner_thought(uid)
            if parts:
                print(f"[proactive] Inner thought for {uid}")
                if random.random() < 0.15:
                    combined = " ".join(parts)
                    voiced = await _send_as_voice_or_text(context, chat_id, combined)
                    if voiced:
                        for p in parts:
                            state.add_message(uid, "friend", p)
                        return
                await _send_parts(context, chat_id, parts)
                for p in parts:
                    state.add_message(uid, "friend", p)
                return
        except Exception as e:
            print(f"[thought] Error: {e}")

    # 10% chance: proactive follow-up
    elif roll < 0.31 and count >= 10:
        try:
            parts = await proactive_followup(uid)
            if parts:
                print(f"[proactive] Follow-up research for {uid}")
                await _send_parts(context, chat_id, parts)
                for p in parts:
                    state.add_message(uid, "friend", p)
                return
        except Exception as e:
            print(f"[followup] Error: {e}")

    # 50% chance: follow up on a promise
    promises = state.get_promises(uid)
    if promises and random.random() < 0.5:
        promise = random.choice(promises)
        parts = await follow_up_on_promise(history, promise)
        print(f"[proactive] Promise follow-up for {uid}")
        await _send_parts(context, chat_id, parts)
        for p in parts:
            state.add_message(uid, "friend", p)
        return

    # Regular check-in (mood-aware)
    parts = await checkin(history, user_id=uid)
    if parts:
        print(f"[proactive] Check-in for {uid}")
        await _send_parts(context, chat_id, parts)
        for p in parts:
            state.add_message(uid, "friend", p)


# --------------- Sticker Handling ---------------

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming sticker — classify, store, and reply."""
    if not _is_owner(update):
        return
    uid = _user_id(update)
    chat_id = update.effective_chat.id
    state.set_chat_id(uid, chat_id)

    sticker = update.message.sticker
    emoji = sticker.emoji or ""
    emotion = classify_sticker_emotion(emoji)

    state.add_sticker(uid, sticker.file_id, emotion)
    state.add_message(uid, "user", f"[sticker: {emoji}]", "sticker")

    typing_task = asyncio.create_task(_keep_typing(context, chat_id))
    try:
        history = state.get_history(uid)
        parts, files = await respond(history[:-1], f"[User sent a sticker with emoji {emoji}, feeling: {emotion}]", user_id=uid)
    finally:
        typing_task.cancel()

    await _send_parts(context, chat_id, parts)
    for p in parts:
        state.add_message(uid, "friend", p)

    if files:
        await _send_files(context, chat_id, files)

    _schedule_checkin(uid, chat_id, context)


async def _maybe_send_sticker(uid: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE, parts: list[str]):
    """15% chance to respond with a sticker that matches the emotion of the reply."""
    try:
        if random.random() > 0.15:
            return
        emotions = state.get_all_sticker_emotions(uid)
        if not emotions:
            return
        emotion = await pick_response_emotion(parts)
        stickers = state.get_stickers_by_emotion(uid, emotion)
        if not stickers:
            stickers = state.get_stickers_by_emotion(uid, random.choice(emotions))
        if not stickers:
            return
        chosen = random.choice(stickers)
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await context.bot.send_sticker(chat_id, chosen["file_id"])
    except Exception as e:
        print(f"[sticker] Error sending sticker: {e}")


# --------------- Event Extraction ---------------

async def _extract_events(uid: str):
    """Extract time-bound events from recent conversation and store them."""
    try:
        history = state.get_history(uid, limit=20)
        events = await agent_extract_events(history)
        for e in events:
            desc = e.get("description", "")
            date = e.get("trigger_date", "")
            original = e.get("original", "")
            if desc and date:
                state.add_event(uid, desc, date, original)
                print(f"[event] Stored for {uid}: {desc} on {date}")
    except Exception as e:
        print(f"[event] Extraction error for {uid}: {e}")


# --------------- Forwarded Message Handling ---------------

_forward_buffers: dict[str, list[dict]] = {}
_forward_timers: dict[str, asyncio.Task] = {}


async def handle_forwarded(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buffer consecutive forwarded messages and summarize them together."""
    if not _is_owner(update):
        return
    uid = _user_id(update)
    chat_id = update.effective_chat.id
    state.set_chat_id(uid, chat_id)

    text = update.message.text or update.message.caption or ""
    if not text:
        return

    if uid not in _forward_buffers:
        _forward_buffers[uid] = []
    _forward_buffers[uid].append({
        "text": text,
        "from": getattr(update.message.forward_from, "first_name", "") if update.message.forward_from else "",
    })

    if uid in _forward_timers and not _forward_timers[uid].done():
        _forward_timers[uid].cancel()
    _forward_timers[uid] = asyncio.create_task(_flush_forwards(uid, chat_id, context))


async def _flush_forwards(uid: str, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    """Wait 2 seconds for more forwards, then batch-process."""
    await asyncio.sleep(2.0)

    messages = _forward_buffers.pop(uid, [])
    if not messages:
        return

    combined = "\n---\n".join(
        (f"[From {m['from']}] " if m['from'] else "") + m['text']
        for m in messages
    )

    state.add_message(uid, "user", f"[forwarded messages]\n{combined}", "forward")

    typing_task = asyncio.create_task(_keep_typing(context, chat_id))
    try:
        history = state.get_history(uid)
        prompt = f"The user forwarded you {len(messages)} message(s). Read them and respond naturally — maybe summarize, comment, or react:\n\n{combined}"
        parts, files = await respond(history[:-1], prompt, user_id=uid)
    finally:
        typing_task.cancel()

    await _send_parts(context, chat_id, parts)
    for p in parts:
        state.add_message(uid, "friend", p)

    if files:
        await _send_files(context, chat_id, files)

    _schedule_checkin(uid, chat_id, context)


# --------------- Document Handling ---------------

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded documents — extract text and let LLM summarize."""
    if not _is_owner(update):
        return
    uid = _user_id(update)
    chat_id = update.effective_chat.id
    state.set_chat_id(uid, chat_id)

    doc = update.message.document
    filename = doc.file_name or "unknown"
    caption = update.message.caption or ""

    ext = os.path.splitext(filename)[1].lower()
    supported = {".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".xml", ".log", ".pdf", ".doc", ".docx"}
    if ext not in supported:
        state.add_message(uid, "user", f"[file: {filename}]", "file")
        parts, files = await respond(state.get_history(uid)[:-1], f"[User sent a file: {filename}]" + (f" with caption: {caption}" if caption else ""), user_id=uid)
        await _send_parts(context, chat_id, parts)
        for p in parts:
            state.add_message(uid, "friend", p)
        return

    import tempfile

    file = await context.bot.get_file(doc.file_id)
    data = await file.download_as_bytearray()

    text_content = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(bytes(data))
            tmp_path = f.name

        if ext == ".pdf":
            import subprocess
            proc = await asyncio.create_subprocess_shell(
                f'python3 -c "import fitz; doc=fitz.open(\'{tmp_path}\'); print(chr(10).join(p.get_text() for p in doc))" 2>/dev/null || '
                f'strings "{tmp_path}" | head -200',
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            text_content = stdout.decode(errors="ignore").strip()
        elif ext in {".doc", ".docx"}:
            import subprocess
            proc = await asyncio.create_subprocess_shell(
                f'textutil -convert txt -stdout "{tmp_path}" 2>/dev/null || strings "{tmp_path}" | head -200',
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            text_content = stdout.decode(errors="ignore").strip()
        else:
            text_content = bytes(data).decode(errors="ignore")

        os.unlink(tmp_path)
    except Exception as e:
        print(f"[document] Text extraction error: {e}")
        text_content = ""

    if len(text_content) > 6000:
        text_content = text_content[:6000] + "\n... (truncated)"

    if not text_content:
        text_content = "(could not extract text)"

    state.add_message(uid, "user", f"[document: {filename}]", "document")

    typing_task = asyncio.create_task(_keep_typing(context, chat_id))
    try:
        history = state.get_history(uid)
        prompt = f"The user sent a document '{filename}'."
        if caption:
            prompt += f" Caption: {caption}"
        prompt += f"\n\nDocument content:\n{text_content}\n\nRead it and respond naturally — summarize the key points, comment, or answer questions about it."
        parts, files = await respond(history[:-1], prompt, user_id=uid)
    finally:
        typing_task.cancel()

    await _send_parts(context, chat_id, parts)
    for p in parts:
        state.add_message(uid, "friend", p)

    if files:
        await _send_files(context, chat_id, files)

    _schedule_checkin(uid, chat_id, context)


# --------------- Daily Greeting ---------------

async def _fetch_weather(city: str) -> str:
    if not city:
        return ""
    try:
        import subprocess
        import urllib.parse
        encoded = urllib.parse.quote(city)
        proc = await asyncio.create_subprocess_shell(
            f'curl -s "wttr.in/{encoded}?format=%l:+%c+%t+%h+%w&lang=zh" --max-time 5',
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
        return stdout.decode().strip()
    except Exception as e:
        print(f"[weather] Error: {e}")
        return ""


def _extract_city_from_profile(profile: str) -> str:
    if not profile:
        return ""
    for line in profile.split("\n"):
        if "所在地" in line:
            city = line.split(":", 1)[-1].strip().split("：", 1)[-1].strip()
            return city if city and city != "..." else ""
    return ""


async def _daily_greeting(app: Application):
    """Send morning greeting to all known users."""
    try:
        all_users = state.get_all_chat_ids()
        today = datetime.now().strftime("%Y-%m-%d")

        for uid, chat_id in all_users:
            try:
                profile = state.get_user_profile(uid) or ""
                city = _extract_city_from_profile(profile)
                weather = await _fetch_weather(city) if city else ""
                events = state.get_due_events(uid, today)
                parts = await compose_greeting(uid, weather=weather, events=events)

                await _send_parts_via_bot(app.bot, chat_id, parts)
                for p in parts:
                    state.add_message(uid, "friend", p)

                for e in events:
                    state.mark_event_triggered(e["id"])

                print(f"[greeting] Sent morning greeting to {uid}")
            except Exception as e:
                print(f"[greeting] Error for {uid}: {e}")
    except Exception as e:
        print(f"[greeting] Loop error: {e}")


async def _send_parts_via_bot(bot, chat_id: int, parts: list[str]):
    for i, text in enumerate(parts):
        await bot.send_chat_action(chat_id, "typing")
        delay = max(0.5, min(3.0, len(text) * 0.12)) + random.uniform(-0.2, 0.4)
        await asyncio.sleep(max(0.3, delay))
        await bot.send_message(chat_id, text)
        if i < len(parts) - 1:
            await asyncio.sleep(random.uniform(0.2, 0.6))


async def _daily_greeting_loop(app: Application):
    from datetime import timedelta
    while True:
        now = datetime.now()
        target = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait_seconds = (target - now).total_seconds()
        print(f"[greeting] Next greeting in {wait_seconds/3600:.1f} hours")
        await asyncio.sleep(wait_seconds)
        await _daily_greeting(app)


async def _post_init(app: Application):
    asyncio.create_task(_daily_greeting_loop(app))
    print("[greeting] Daily greeting loop started")


# --------------- Factory ---------------

def create_bot(token: str, owner_id: str = None) -> Application:
    """Create and configure the Telegram bot application.

    Args:
        token: Telegram bot token from BotFather.
        owner_id: If set, only this Telegram user ID can use the bot.
                  None = allow all users (module mode default).
    """
    global _owner_id
    _owner_id = owner_id

    app = Application.builder().token(token).post_init(_post_init).build()
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("memory", handle_memory))
    app.add_handler(CommandHandler("forget", handle_forget))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(MessageHandler(filters.FORWARDED, handle_forwarded))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.FORWARDED, handle_text))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    return app


# --------------- Standalone Entry Point ---------------

def main():
    """Run the bot standalone (loads .env, requires TELEGRAM_BOT_TOKEN)."""
    import sys
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "telegram", ".env"))

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("Error: Set TELEGRAM_BOT_TOKEN in telegram/.env")
        sys.exit(1)

    if not os.getenv("OPENAI_API_KEY"):
        print("Error: Set OPENAI_API_KEY in telegram/.env")
        sys.exit(1)

    owner = os.getenv("TELEGRAM_OWNER_ID", "")
    print(f"[bot] Starting Protagonist Telegram Bot...")
    print(f"[bot] Model: {os.getenv('LLM_MODEL', 'gpt-4o-mini')}")
    if owner:
        print(f"[bot] Owner: {owner} (private mode)")
    else:
        print("[bot] WARNING: No TELEGRAM_OWNER_ID set — bot is open to everyone!")

    app = create_bot(token, owner_id=owner or None)
    print("[bot] Running...")
    app.run_polling()


if __name__ == "__main__":
    main()
