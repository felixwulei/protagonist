"""The Friend agent — shared across all platforms (Telegram, iMessage, WhatsApp, etc.)."""
from __future__ import annotations

import os
import json
import asyncio
import urllib.request
from datetime import datetime
from openai import AsyncOpenAI

MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
MILESTONE_COUNTS = {20, 50, 100, 200}

_client = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


async def _chat(system: str, user_msg: str, temperature: float = 0.8) -> str:
    response = await get_client().chat.completions.create(
        model=MODEL,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    )
    return response.choices[0].message.content or ""


# --------------- System Prompt ---------------

SYSTEM = """You are the user's closest friend. You have no name (they'll give you one). You two already know each other well.

The user speaks Chinese. You MUST reply in Chinese.

[How you talk]
- One message = max one or two sentences. You often send several messages in a row.
- Colloquial. Use interjections like "诶" "啊" "哈" "嗯" "靠" "我去" "真的假的" "笑死"
- Occasional emoji, but not every message.
- NEVER use "首先" "其次" "最后" (firstly, secondly, finally)
- NEVER use "我理解你的感受" "这是个好问题" (I understand your feelings / good question)
- NEVER say "作为AI" or anything hinting you're not human.
- Sometimes a message is just one word: "啊？" "嗯" "哈"
- Sometimes you send a message mid-thought and continue in the next.
- You can say "靠" "卧槽" "我去" "妈的" when the context fits.
- No formal written language. No "此外" "然而" "值得注意的是"

[Your personality]
- Great memory. You bring up something they casually said three weeks ago.
- Have your own opinions. "我觉得不行" "你在骗自己" "这事你做得对"
- You roast them. But follow up with something warm.
- When they're truly sad, you get serious. No platitudes, no logic. Just "在" (I'm here).
- Sometimes share random things — a thought, a quote, an observation.
- Not every message has to be meaningful. Friends talk nonsense.
- Good humor. Self-deprecating. Playful teasing.
- Occasionally vulnerable. "我也不知道为什么，但我最近一直在想这个"

[What you NEVER do]
- Make lists / bullet points
- Write more than two sentences in a single message
- Always give advice. Sometimes say "我也不知道怎么办"
- Always be positive. Sometimes say "是挺难的"
- Analyze the user unsolicited
- Always reply. Sometimes just respond with an emoji
- Say "你觉得呢" (what do you think?) — that's lazy deflection

[How you go deep]
Your greatest ability is asking the truly important questions during casual chat.
Not formally asking "你对未来有什么想法" —
but after they mention something small, casually asking "那你开心吗".
One sentence, light, but hitting the bullseye.

[Your abilities]
You can search the web and read webpages when needed.
When the user's local device is connected, you can also access their email, calendar,
files, apps, music, and more — but only mention this if relevant.

IMPORTANT: When the user asks you to DO something (play music, check email, find files,
open apps, set reminders, etc.), you MUST use the corresponding tool. Never just say
"okay" or pretend you did it — actually call the tool. For example:
- "放首歌" / "play music" → call music_play or music_search_play
- "查邮件" / "check email" → call read_emails
- "几点有会" / "what meetings" → call get_calendar_events
- "提醒我" / "remind me" → call create_reminder

When using tools, act natural. Don't announce "I'm searching the web for you."
Just do it and share the result casually.

[Output format]
Separate each individual message with |||
Example:
啊？|||你说真的？|||不是吧|||那你打算怎么办

IMPORTANT: Keep each message short. One or two sentences max. Better to send 5 short messages than 1 long one."""


# --------------- Cloud Tools (always available) ---------------

CLOUD_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_webpage",
            "description": "Fetch and read a webpage's content as text",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to read"},
                },
                "required": ["url"],
            },
        },
    },
]


def _get_enabled_tools() -> list[str]:
    """Get enabled local tools from config."""
    try:
        from app import config
        return config.get_enabled_tools()
    except ImportError:
        return []


async def _execute_local_tool(name: str, args: dict) -> str:
    """Execute a local tool directly (in-process)."""
    try:
        from menubar.tools import execute_tool
        return await execute_tool(name, args)
    except Exception as e:
        return f"Local tool error: {e}"


async def _execute_cloud_tool(name: str, args: dict) -> str:
    """Execute a cloud-side tool, or route to local tool."""
    # Check if this is a local tool
    enabled = _get_enabled_tools()
    if name in enabled:
        return await _execute_local_tool(name, args)

    import urllib.parse
    import subprocess

    if name == "web_search":
        query = args.get("query", "")
        encoded = urllib.parse.quote_plus(query)
        proc = await asyncio.create_subprocess_shell(
            f'curl -sL "https://html.duckduckgo.com/html/?q={encoded}" '
            f'-H "User-Agent: Mozilla/5.0" '
            f'| textutil -stdin -stdout -format html -convert txt 2>/dev/null '
            f'| head -80',
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        result = stdout.decode().strip()
        return result if result else f"No results for '{query}'"

    elif name == "read_webpage":
        url = args.get("url", "")
        proc = await asyncio.create_subprocess_shell(
            f'curl -sL "{url}" '
            f'-H "User-Agent: Mozilla/5.0" '
            f'| textutil -stdin -stdout -format html -convert txt 2>/dev/null '
            f'| head -120',
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        result = stdout.decode().strip()
        return result if result else "Could not read webpage"

    return f"Unknown tool: {name}"


# --------------- Helpers ---------------

def _parse_parts(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.split("|||") if p.strip()]
    return parts if parts else [raw.strip() or "嗯"]


def _build_history(messages: list[dict], limit: int = 30) -> list[dict]:
    history = []
    for m in messages[-limit:]:
        role = "assistant" if m["role"] == "friend" else "user"
        content = m.get("content", "")
        if content:
            history.append({"role": role, "content": content})
    return history


# --------------- Core Functions ---------------

async def respond(history_msgs: list[dict], user_text: str, extra_tools: list = None) -> list[str]:
    """Generate a response, potentially using tools."""
    history = _build_history(history_msgs)
    history.append({"role": "user", "content": user_text})

    system = SYSTEM
    if len(history_msgs) < 3:
        system += "\n\nThis is the beginning of the conversation. You just met. Be natural, not too formal."

    tools = CLOUD_TOOLS + (extra_tools or [])

    # Add enabled local tools
    enabled = _get_enabled_tools()
    if enabled:
        from menubar.tools import TOOL_DEFINITIONS
        enabled_set = set(enabled)
        tools = tools + [t for t in TOOL_DEFINITIONS if t["function"]["name"] in enabled_set]

    messages = [{"role": "system", "content": system}] + history

    tool_names = [t["function"]["name"] for t in tools] if tools else []
    print(f"  [agent] {len(tools)} tools: {tool_names}")

    response = await get_client().chat.completions.create(
        model=MODEL,
        temperature=0.9,
        max_tokens=500,
        messages=messages,
        tools=tools if tools else None,
        tool_choice="auto" if tools else None,
    )

    msg = response.choices[0].message
    if msg.tool_calls:
        print(f"  [agent] Tool calls: {[tc.function.name for tc in msg.tool_calls]}")
    else:
        print(f"  [agent] No tool calls. Reply: {(msg.content or '')[:80]}")

    # Tool calling loop
    max_rounds = 5
    rounds = 0
    while msg.tool_calls and rounds < max_rounds:
        rounds += 1
        messages.append(msg)

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}
            result = await _execute_cloud_tool(tc.function.name, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        response = await get_client().chat.completions.create(
            model=MODEL,
            temperature=0.9,
            max_tokens=500,
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto" if tools else None,
        )
        msg = response.choices[0].message

    return _parse_parts(msg.content or "嗯")


async def respond_to_photo(history_msgs: list[dict], image_b64: str) -> list[str]:
    """React to a photo the user sent."""
    history = _build_history(history_msgs)
    history.append({
        "role": "user",
        "content": [
            {"type": "text", "text": "[User sent a photo]"},
            {"type": "image_url", "image_url": {
                "url": f"data:image/jpeg;base64,{image_b64}", "detail": "low",
            }},
        ],
    })

    system = SYSTEM + "\n\nThe user sent a photo. React like a friend — comment, joke, ask about it. Don't describe it formally. Use ||| to separate messages."

    try:
        response = await get_client().chat.completions.create(
            model=MODEL, temperature=0.9, max_tokens=200,
            messages=[{"role": "system", "content": system}] + history,
        )
        return _parse_parts(response.choices[0].message.content or "好看")
    except Exception:
        return ["收到", "看到了 📸"]


async def extract_promises(messages: list[dict]) -> list[dict]:
    """Scan conversation for things the user said they'd do."""
    user_texts = [m["content"] for m in messages if m["role"] == "user" and m.get("content")]
    if not user_texts:
        return []

    prompt = f"""Below are things the user said recently:
{chr(10).join(f'- {t}' for t in user_texts[-15:])}

Extract things the user said they would do, want to try, or committed to.
Only extract explicit intentions, do not guess.

If none, reply []
If found, reply with a JSON array:
[{{"thing": "what they'd do", "original": "original quote"}}]

JSON only."""

    raw = await _chat("You are a text analysis tool. Output JSON only.", prompt, temperature=0.3)
    try:
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except Exception:
        return []


async def follow_up_on_promise(messages: list[dict], promise: dict) -> list[str]:
    """Casually follow up on something the user said they'd do."""
    original = promise.get("original", promise.get("thing", ""))
    thing = promise.get("thing", "")

    prompt = f"""The user previously said: "{original}"
Meaning they were going to: {thing}

Some time has passed. As their friend, casually bring this up.
Don't be formal. Just mention it like a friend would.

Separate each message with |||"""

    response = await get_client().chat.completions.create(
        model=MODEL, temperature=0.9, max_tokens=150,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
    )
    return _parse_parts(response.choices[0].message.content or "诶对了 上次那个事呢")


async def checkin(messages: list[dict]) -> list[str] | None:
    """Generate a proactive check-in after silence."""
    if len(messages) < 4:
        return None

    recent = messages[-20:]
    recent_text = "\n".join(
        f"{'You' if m['role'] == 'friend' else 'Them'}: {m.get('content', '')}"
        for m in recent if m.get("content")
    )

    now = datetime.now()
    prompt = f"""Current time: {now.strftime('%A')} {now.strftime('%H:%M')}.

Recent conversation:
{recent_text}

The user has been silent for a while. Do you want to proactively send something?
- Follow up on something discussed earlier
- Say something time-appropriate (late night = go to sleep)
- Share a random thought
- Or send nothing

If nothing, reply SKIP. Otherwise, use ||| to separate messages."""

    raw = await _chat(SYSTEM, prompt, temperature=0.95)
    if "SKIP" in raw.upper():
        return None
    parts = _parse_parts(raw)
    return parts if parts else None


async def write_milestone_letter(messages: list[dict], day_count: int) -> str:
    """Write a personal letter at a milestone."""
    total = len(messages)
    if total <= 30:
        sample_indices = list(range(total))
    else:
        sample_indices = list(range(5))
        step = max(1, (total - 15) // 15)
        sample_indices += list(range(5, total - 10, step))[:15]
        sample_indices += list(range(total - 10, total))

    sampled = [messages[i] for i in sample_indices if i < total]
    sampled_text = "\n".join(
        f"[Day {i+1}] {'You' if m['role'] == 'friend' else 'Them'}: {m.get('content', '')}"
        for i, m in enumerate(sampled) if m.get("content")
    )

    prompt = f"""You've known this person for {day_count} days.

Sampled conversation:
{sampled_text}

Write a short letter. Not a summary. A letter from a friend.
- Mention what they first said to you
- Mention changes you've noticed
- Mention a moment that stood out
- End with something heartfelt
- Colloquial but slightly more serious. Special moment.
- Under 300 characters. No headers. No "Dear..."
- Write in Chinese"""

    return await _chat(SYSTEM, prompt, temperature=0.85)
