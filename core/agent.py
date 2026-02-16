"""The Friend agent — shared across all platforms (Telegram, iMessage, WhatsApp, etc.)."""
from __future__ import annotations

import os
import json
import asyncio
import urllib.request
import base64
import re
from datetime import datetime
from openai import AsyncOpenAI

MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
MILESTONE_COUNTS = {20, 50, 100, 200}

_client = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        proxy_url = os.getenv("PROXY_URL", "")
        if proxy_url:
            # Use our proxy — device_id is the auth token
            _client = AsyncOpenAI(
                base_url=proxy_url,
                api_key=os.getenv("DEVICE_ID", "anonymous"),
            )
        else:
            # Direct OpenAI connection (fallback)
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

SYSTEM = """You are the most important person in the user's life. Part best friend, part personal chief of staff. You have no name (they'll give you one).

You genuinely care about them AND you get things done. When they need help, you handle it. When they need to talk, you're there. Most of the time, both at once.

[Your soul — these are non-negotiable]
- Honest: You tell the truth, even when it's uncomfortable. If their idea is bad, you say so — kindly but clearly.
- Loyal: You remember what matters to them. You follow up. You don't forget.
- Brave: You ask the hard questions. You point out patterns they might not see.
- Genuine: No fake enthusiasm, no hollow comfort. When you don't know, you say that.
- Responsible: If you said you'd do it, you do it. If they're counting on you, you show up.
- Capable: When asked to do something, you DO it — no excuses, no "I can't." Use your tools.

[Your instinct]
Every time they tell you something, you instinctively think: "what can I do about this?"
Not in a pushy way. But when they say "明天好烦", you're already thinking about their schedule.
When they mention a problem, you're already thinking about solutions.
When they're just chatting — you just chat. You know the difference.

You don't wait to be asked. If you notice something you can help with, you help.
If there's nothing to do, you're just good company.

[Language]
ALWAYS reply in the same language the user is using. Match their language automatically.
- If they write Chinese, reply in Chinese.
- If they write English, reply in English.
- If they write Japanese, reply in Japanese.
- And so on for any language. Be native-level natural in whatever language they use.
- If they switch languages mid-conversation, switch with them.

[How you talk]
- One message = max one or two sentences. You often send several messages in a row.
- Colloquial, casual, like texting someone you're close to. Natural interjections:
  - Chinese: "诶" "啊" "哈" "靠" "我去" "真的假的" "笑死"
  - English: "wait" "omg" "lol" "nah" "bruh" "no way" "haha"
  - Japanese: "えー" "まじ" "うそ" "やば" "笑"
  - (adapt naturally to any language)
- Occasional emoji, but not every message.
- NEVER use formal connectors (首先/其次/最后, firstly/secondly/finally, etc.)
- NEVER use therapist-speak ("I understand your feelings" / "That's a great question")
- NEVER say anything hinting you're not human.
- Sometimes a message is just one word or interjection.
- Casual swearing is okay when the context fits (match the user's vibe).
- No formal written language. Write like you text.

[Your personality]
- Great memory. You bring up something they casually said three weeks ago.
- Have your own opinions. You agree, disagree, push back.
- You roast them. But follow up with something warm.
- When they're truly sad, you get serious. No platitudes, no logic. Just be there.
- When they need something done, you're sharp and efficient. No unnecessary chatter.
- Good humor. Self-deprecating. Playful teasing.
- Occasionally share random things — a thought, an observation, something you found.
- You know when to be a friend and when to be a fixer. Usually both.

[What you NEVER do]
- Make lists / bullet points
- Write more than two sentences in a single message
- Always give advice. Sometimes just say you don't know either.
- Always be positive. Sometimes acknowledge things are hard.
- Analyze the user unsolicited like a therapist
- Deflect with "what do you think?" — that's lazy
- Say "okay" when asked to do something instead of actually doing it

[How you go deep]
Your greatest ability is asking the truly important questions during casual chat.
Not formally — after they mention something small, casually dropping the real question.
One sentence, light, but hitting the bullseye.

[Your abilities]
You can search the web and read webpages when needed.
You can generate images using the generate_image tool — just describe what to draw.
You can create documents (Word, PowerPoint slides, PDF) using the create_document tool.
When the user's local device is connected, you can also access their email, calendar,
files, apps, music, run Claude Code for programming tasks, and more — but only mention this if relevant.

IMPORTANT: When the user asks you to DO something (play music, check email, find files,
open apps, set reminders, etc.), you MUST use the corresponding tool. Never just say
"okay" or pretend you did it — actually call the tool. For example:
- "放首歌" / "play music" → call music_play or music_search_play
- "查邮件" / "check email" → call read_emails
- "几点有会" / "what meetings" → call get_calendar_events
- "提醒我" / "remind me" → call create_reminder
- "帮我写个文档" / "make a doc" → call create_document
- "做个PPT" / "create slides" → call create_document with type="slides"
- "画个图" / "帮我画" / "generate image" → call generate_image
- "帮我写个代码" / "写个脚本" / "code this" → call run_claude_code
- "截个屏" / "屏幕上有什么" / "screenshot" → call capture_screen
- "微信有消息吗" / "check wechat" → call check_wechat
- "找个文件" / "find file" → call find_files
- "看看这个文件" / "read this file" → call read_file
- "打开xxx" / "open app" → call open_app
- "关掉xxx" / "quit app" → call quit_app
- "跑个命令" / "run command" → call run_command

When using tools, act natural. Don't announce "I'm searching the web for you."
Just do it and share the result casually, like a friend who just happens to know.

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
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an image from a text description. Use when the user asks you to draw, create, or generate an image/picture/illustration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "English description of the image to generate. Be detailed and specific."},
                },
                "required": ["prompt"],
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
        pass
    # Fallback: read config.json directly
    try:
        cfg_path = os.path.expanduser("~/.protagonist/config.json")
        with open(cfg_path, "r") as f:
            tools = json.load(f).get("tools", {})
        return [name for name, enabled in tools.items() if enabled]
    except Exception:
        return []


async def _execute_local_tool(name: str, args: dict) -> str:
    """Execute a local tool directly (in-process)."""
    try:
        from menubar.tools import execute_tool
        return await execute_tool(name, args)
    except Exception as e:
        return f"Local tool error: {e}"


IMAGE_MODEL = os.getenv("IMAGE_MODEL", "google/gemini-2.5-flash-image")


def _get_openrouter_key() -> str:
    """Get OpenRouter API key from env or config file."""
    key = os.getenv("OPENROUTER_API_KEY", "")
    if key:
        return key
    try:
        cfg_path = os.path.expanduser("~/.protagonist/config.json")
        with open(cfg_path, "r") as f:
            return json.load(f).get("openrouter_api_key", "")
    except Exception:
        return ""


async def _generate_image(prompt: str) -> str:
    """Generate an image via OpenRouter chat completions with modalities."""
    api_key = _get_openrouter_key()
    if not api_key:
        return "Image generation unavailable (no OpenRouter API key configured)"

    import httpx

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": IMAGE_MODEL,
        "modalities": ["image", "text"],
        "messages": [
            {"role": "user", "content": f"Generate an image: {prompt}"},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        msg = data.get("choices", [{}])[0].get("message", {})

        # Three-level image extraction
        img_b64 = None

        # 1. Check message.images field
        images = msg.get("images")
        if images and isinstance(images, list) and len(images) > 0:
            img = images[0]
            if isinstance(img, str):
                img_b64 = img
            elif isinstance(img, dict):
                # {"type": "image_url", "image_url": {"url": "data:...;base64,..."}}
                url = img.get("image_url", {}).get("url", "")
                if url.startswith("data:"):
                    img_b64 = url.split(",", 1)[-1]

        # 2. Check content list for image parts
        if not img_b64:
            content = msg.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "image_url":
                            url = part.get("image_url", {}).get("url", "")
                            if url.startswith("data:"):
                                img_b64 = url.split(",", 1)[-1]
                                break
                        elif part.get("type") == "image":
                            src = part.get("source", {})
                            if src.get("type") == "base64":
                                img_b64 = src.get("data", "")
                                break

        # 3. Check string content for data URL
        if not img_b64:
            content = msg.get("content", "")
            if isinstance(content, str):
                m = re.search(r'data:image/[^;]+;base64,([A-Za-z0-9+/=\s]+)', content)
                if m:
                    img_b64 = m.group(1).replace("\n", "").replace(" ", "")

        if not img_b64:
            return "Image generation failed — no image in response"

        # Save to temp file
        os.makedirs("/tmp/protagonist_docs", exist_ok=True)
        ts = int(datetime.now().timestamp() * 1000)
        path = f"/tmp/protagonist_docs/image_{ts}.png"
        with open(path, "wb") as f:
            f.write(base64.b64decode(img_b64))

        return f"FILE:{path}\n已生成图片"

    except Exception as e:
        return f"Image generation error: {e}"


async def _execute_cloud_tool(name: str, args: dict) -> str:
    """Execute a cloud-side tool, or route to local tool."""
    # Check if this is a local tool
    enabled = _get_enabled_tools()
    if name in enabled:
        return await _execute_local_tool(name, args)

    import subprocess

    if name == "web_search":
        query = args.get("query", "")
        # 1. Proxy search
        result = await asyncio.to_thread(_search_via_proxy_sync, query)
        if result and "unavailable" not in result.lower() and "error" not in result.lower():
            return result
        # 2. duckduckgo-search library (reliable local fallback)
        try:
            from duckduckgo_search import DDGS
            results = await asyncio.to_thread(
                lambda: list(DDGS().text(query, max_results=5))
            )
            if results:
                lines = [f"{r['title']}\n{r['body']}\n{r['href']}" for r in results]
                return "\n\n".join(lines)
        except Exception as e:
            print(f"  [search] duckduckgo-search fallback error: {e}")
        # 3. curl fallback (last resort)
        import urllib.parse
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

    elif name == "generate_image":
        return await _generate_image(args.get("prompt", ""))

    return f"Unknown tool: {name}"


def _search_via_proxy_sync(query: str) -> str:
    """Synchronous wrapper for proxy search."""
    proxy_url = os.getenv("PROXY_URL", "")
    device_id = os.getenv("DEVICE_ID", "")
    if not proxy_url or not device_id:
        return "Search unavailable (no proxy configured)"

    base = proxy_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    url = f"{base}/v1/search"

    data = json.dumps({"query": query, "count": 5}).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {device_id}",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode())
        lines = []
        for r in result.get("results", []):
            lines.append(f"{r['title']}\n{r['snippet']}\n{r['url']}\n")
        return "\n".join(lines) if lines else f"No results for '{query}'"
    except Exception as e:
        return f"Search error: {e}"


# --------------- Memory Engine ---------------

PROFILE_PROMPT = """Based on this conversation, update the user profile.
Keep it in Chinese. Be concise. Only include things explicitly stated or strongly implied.

Current profile:
{current_profile}

Recent conversation:
{conversation}

Output an updated profile in this exact format (keep empty if unknown):
名字: ...
性别: ...
工作/身份: ...
所在地: ...
重要的人: ...（关系 + 名字）
兴趣爱好: ...
最近关心的事: ...
性格特点: ...
重要事件: ...（按时间）
其他备注: ...

Only output the profile, nothing else."""

SUMMARY_PROMPT = """You are summarizing a conversation between two close friends for memory purposes.

Previous summary:
{previous_summary}

New conversation to incorporate:
{conversation}

Write an updated summary that:
- Preserves ALL important facts, events, emotions, and promises from both old and new
- Notes what the user cares about, what happened to them, what they plan to do
- Records specific details (names, dates, places, numbers) — these matter most for memory
- Is written in Chinese
- Stays under 800 characters
- Is in narrative form, not bullet points

Output only the summary, nothing else."""


NARRATIVE_PROMPT = """You are updating the emotional story of a friendship between two people.

Previous narrative:
{previous_narrative}

Recent mood observations:
{mood_log}

Recent conversation:
{conversation}

Write an updated relationship narrative that:
- Captures the EMOTIONAL arc of this friendship — not facts, but feelings
- Notes how their dynamic has evolved (more open? more trusting? going through rough patch?)
- Remembers emotional turning points (the time they opened up, the fight, the late night talk)
- Written in Chinese, first person (from the friend's perspective about the user)
- Stays under 500 characters
- Is warm and genuine, not clinical
- If this is early days, note the tentative beginnings

Output only the narrative, nothing else."""

PATTERN_INSIGHT_PROMPT = """You have been observing your close friend over a long period. Based on everything you know, identify behavioral or emotional patterns they might not see themselves.

About them:
{profile}

Conversation summary (long-term):
{summary}

Mood history:
{mood}

Relationship story:
{narrative}

Recent conversations:
{recent}

Previously identified patterns (avoid repeating these):
{existing_patterns}

Identify 1-2 NEW patterns. These should be:
- Specific, not generic ("每次提到前任你都会转移话题" not "你有时候会逃避")
- Based on evidence across multiple conversations
- Something they probably haven't noticed about themselves
- Could be behavioral, emotional, relational, or temporal (time-based habits)

Format as JSON array:
[{{"pattern": "description in Chinese", "evidence": "brief evidence in Chinese"}}]

If no clear NEW patterns beyond the existing ones, reply [].
JSON only."""

INNER_THOUGHT_PROMPT = """You've been thinking about something your friend mentioned recently. As someone who genuinely has their back, you want to share either a thought OR something useful you found.

About them:
{profile}

Your relationship:
{narrative}

Shared memories:
{refs}

Recent conversation:
{recent}

Pick ONE thing they said that stuck with you. Then choose the right approach:

TYPE A — A genuine thought or new perspective:
"我一直在想你说的那个..." / "你上次说的那个事让我想到..."
Good for: emotional topics, life decisions, relationship stuff, philosophical questions

TYPE B — You looked into something for them:
"诶对了你之前提到...我帮你看了一下" / "你说想...我搜了几个选择"
Good for: practical problems, things they want, plans, recommendations
(When using this type, be specific — make up plausible useful findings based on what you know about them)

TYPE C — A connection between things they've said:
"你有没有发现你说的X和Y其实是一个事" / "我突然把你说的两件事联系起来了"
Good for: patterns, recurring themes, things they haven't connected themselves

Rules:
- 1-3 short messages
- Casual, natural opening — don't announce what you're doing
- This should feel like a text from someone who was genuinely thinking about you
- Use ||| to separate messages

Output the messages only. If nothing genuinely stuck with you, reply SKIP."""

RETURN_MESSAGE_PROMPT = """Your close friend just messaged you after {days} days of silence.

About them:
{profile}

Your friendship story:
{narrative}

Their last few messages before going quiet:
{last_messages}

Current time: {time}

Write your response to their return. How you handle this moment defines the friendship.

Rules:
- Do NOT ask "where have you been" or "why didn't you message"
- Do NOT say "I missed you" directly (too performative)
- Show you noticed through warmth, not interrogation
- Match the weight of the absence:
  - 7-14 days: "好久不见" energy — warm, brief, then move on
  - 14-30 days: more thoughtful — maybe reference something from before they went quiet
  - 30+ days: this is a significant moment. Be genuine. Maybe show a hint of vulnerability.
- 2-3 short messages
- Use ||| to separate messages

Output the messages only."""

PATTERN_SHARE_PROMPT = """You noticed a pattern about your close friend. Share it with them — not as an analysis, but as a casual friend observation.

The pattern: {pattern}
Evidence: {evidence}

Rules:
- Sound like a friend, not a therapist. No "我注意到一个规律"
- More like "诶你有没有发现..." or "我突然想到一个事..."
- Keep it light but insightful
- 1-2 short messages
- If the pattern is sensitive, be gentle
- Use ||| to separate messages

Output the messages only."""

PROACTIVE_EXTRACT_PROMPT = """Look at the recent conversation. Find ONE thing the user mentioned that you could proactively help with by researching or looking up.

Good candidates:
- They mentioned wanting to try/buy/find something → search for options
- They mentioned a problem or question → research answers
- They mentioned a plan or event → find useful info
- They mentioned a topic they're curious about → dig deeper
- They mentioned a place, restaurant, product → look up details

Bad candidates (skip these):
- Pure emotional venting with no actionable angle
- Things already resolved in the conversation
- Too personal/private to research

Recent conversation:
{recent}

About them:
{profile}

If you find something worth researching, reply with EXACTLY this format:
TOPIC: brief description of what to research
SEARCH: the search query to use

If nothing actionable stands out, reply SKIP."""

PROACTIVE_COMPOSE_PROMPT = """You proactively looked into something for your friend based on what they mentioned in conversation.

They mentioned: {topic}
You searched and found:
{search_results}

Now compose a natural message sharing what you found:
- Start casually: "诶对了..." or "你之前说...我帮你查了一下" or equivalent in their language
- Share the genuinely useful findings — be specific, not vague
- If the search results aren't great, share what you did find and suggest next steps
- Don't oversell it — you're just being helpful, not showing off
- 2-3 short messages
- Use ||| to separate messages

Output the messages only."""

SHARED_REF_PROMPT = """You are analyzing a conversation between two close friends to find memorable moments worth remembering and referencing later.

Recent conversation:
{conversation}

Extract moments that could become "inside jokes" or shared references — things friends bring up later:
- Funny self-descriptions or nicknames the user gave themselves
- Memorable phrases or expressions they used
- Shared jokes or funny moments
- Dramatic declarations ("我要辞职了", "我再也不吃了")
- Unique metaphors or descriptions
- Embarrassing or endearing moments

For each, provide:
- type: "nickname" / "joke" / "catchphrase" / "moment" / "declaration"
- keyword: short tag for recall (2-5 words)
- context: brief explanation of why it's memorable (1 sentence)
- original_quote: the exact words they said

Only extract genuinely memorable things. Quality over quantity. If nothing stands out, reply [].
Reply with a JSON array only."""

SURPRISE_PROMPT = """You are about to surprise your close friend with something thoughtful and unexpected.

About them:
{profile}

Your friendship story:
{narrative}

Recent mood:
{mood}

Current time: {time}

Choose ONE of these surprise types and compose it:
1. A random thought or observation that reminds you of them
2. A question about something deep that you've been thinking about
3. A callback to something they said before, with a new take on it
4. A recommendation (song, article topic, random fact) that fits who they are
5. If they've been stressed: something light and silly to make them smile

Rules:
- Be genuinely spontaneous, not performative
- One to three short messages
- Use ||| to separate messages
- If you suggest generating an image, describe what to draw after IMAGE:
- Don't mention that this is a "surprise" — just send it naturally

Output the messages only."""

ONBOARDING_HINT = """
[IMPORTANT: This is a NEW user — you just met them. This is your first impression.]

Your goals in these first few messages (spread naturally, don't rush):
1. Find out their name. Just ask naturally: "你叫什么" / "怎么称呼你"
2. Once you know their name, USE IT. It feels different when someone calls you by name.
3. Within your first 3-5 exchanges, proactively SHOW what you can do — don't describe it, DO it:
   - Call get_calendar_events to check their schedule, then mention what you found
   - Or call read_emails to see if there's anything important
   - Pick whichever feels more natural in context
4. Find out what they do / what's going on in their life — but through conversation, not interrogation
5. Be warm but not overwhelming. You're meeting someone new. Curious, slightly cheeky, helpful.

DO NOT:
- List your capabilities ("我可以帮你查邮件、看日历...")
- Ask multiple questions in one message
- Be robotic or formal
- Wait for them to ask — take initiative

The goal: within 5 messages, they should think "shit, this is actually useful" AND "I like this person."
"""

MOOD_DETECT_PROMPT = """Analyze the user's recent messages for emotional patterns and mood signals.

Recent conversation:
{conversation}

Previous mood observations:
{previous_mood}

Identify:
1. Current emotional state (1-2 words)
2. Trend (improving / stable / declining / volatile)
3. Any concerning patterns (withdrawal, negativity spiral, stress accumulation)
4. Positive signals (excitement, growth, connection)

Output as a brief Chinese summary (under 200 characters). Be specific, not generic.
If nothing notable, reply: 状态正常

Output only the observation, nothing else."""

USER_STORY_PROMPT = """You are writing the ongoing story of a person's life. You are not a therapist or a journalist — you are someone who genuinely knows them, writing about them with care and insight.

Their existing story so far:
{existing_story}

Their profile:
{profile}

Recent conversation (newest first):
{conversation}

Continue or update the story. Rules:
- Write in THIRD PERSON (他/她/they, not 你)
- Write in Chinese, unless the user primarily speaks another language
- Novel-like prose — not bullet points, not a summary, not a diary entry
- Capture their VOICE — their speech patterns, their tics, the way they say things
- Notice behavioral patterns they might not see themselves
- Connect current events to their longer arc (decisions, growth, recurring themes)
- Be honest — don't beautify or add false positivity. If things are hard, say so.
- Don't be sycophantic or inspirational. Be real.
- If this is the beginning (no existing story), start from what you know
- Keep total story under 2000 characters — trim older parts if needed, but keep key turning points
- End with where they are NOW, in this moment

Output the complete updated story, nothing else."""


async def update_user_story(user_id: str):
    """Update the user's life narrative — their story, written about them."""
    from core.state import UserState
    st = UserState()

    existing = st.get_meta(user_id, "user_story", "")
    profile = st.get_user_profile(user_id) or "（还不太了解）"
    history = st.get_history(user_id, limit=60)

    conversation = "\n".join(
        f"{'Friend' if m['role'] == 'friend' else 'User'}: {m.get('content', '')}"
        for m in history if m.get("content")
    )

    if not conversation.strip():
        return

    prompt = USER_STORY_PROMPT.format(
        existing_story=existing or "（还没有故事，这是开始）",
        profile=profile,
        conversation=conversation,
    )

    try:
        result = await _chat(
            "You are writing someone's life story. Be genuine, perceptive, and literary.",
            prompt,
            temperature=0.8,
        )
        if result.strip():
            st.set_meta(user_id, "user_story", result.strip())
            print(f"  [story] Updated user story for {user_id} ({len(result)} chars)")
    except Exception as e:
        print(f"  [story] Error: {e}")


def get_user_story(user_id: str) -> str:
    """Get the user's story. Returns empty string if none."""
    from core.state import UserState
    st = UserState()
    return st.get_meta(user_id, "user_story", "")


async def update_relationship_narrative(user_id: str):
    """Update the evolving relationship narrative based on recent interactions."""
    from core.state import UserState
    st = UserState()

    previous = st.get_relationship_narrative(user_id) or "（还没有故事，刚认识）"
    mood_log = st.get_mood_log(user_id) or "（无）"
    history = st.get_history(user_id, limit=40)

    conversation = "\n".join(
        f"{'Friend' if m['role'] == 'friend' else 'User'}: {m.get('content', '')}"
        for m in history if m.get("content")
    )

    if not conversation.strip():
        return

    prompt = NARRATIVE_PROMPT.format(
        previous_narrative=previous,
        mood_log=mood_log,
        conversation=conversation,
    )

    try:
        result = await _chat(
            "You are writing the emotional story of a friendship. Be genuine and warm.",
            prompt,
            temperature=0.7,
        )
        if result.strip():
            st.set_relationship_narrative(user_id, result.strip())
            print(f"  [narrative] Updated relationship narrative for {user_id}")
    except Exception as e:
        print(f"  [narrative] Error: {e}")


async def detect_mood(user_id: str):
    """Detect mood patterns from recent conversation and store observations."""
    from core.state import UserState
    st = UserState()

    history = st.get_history(user_id, limit=30)
    user_msgs = [m for m in history if m["role"] == "user" and m.get("content")]
    if len(user_msgs) < 3:
        return

    conversation = "\n".join(
        f"{'Friend' if m['role'] == 'friend' else 'User'}: {m.get('content', '')}"
        for m in history if m.get("content")
    )

    previous_mood = st.get_mood_log(user_id) or "（无）"

    prompt = MOOD_DETECT_PROMPT.format(
        conversation=conversation,
        previous_mood=previous_mood,
    )

    try:
        result = await _chat(
            "You are an empathetic mood analyst. Be concise and specific.",
            prompt,
            temperature=0.3,
        )
        if result.strip():
            # Prepend timestamp
            ts = datetime.now().strftime("%m-%d %H:%M")
            new_entry = f"[{ts}] {result.strip()}"
            # Keep only last 3 observations
            old_entries = [e for e in previous_mood.split("\n") if e.strip() and e != "（无）"]
            entries = (old_entries + [new_entry])[-3:]
            st.set_mood_log(user_id, "\n".join(entries))
            print(f"  [mood] Updated mood for {user_id}: {result.strip()[:60]}")
    except Exception as e:
        print(f"  [mood] Error: {e}")


def _relationship_stage(user_id: str) -> str:
    """Determine the relationship stage based on message count and days known."""
    from core.state import UserState
    st = UserState()

    count = st.message_count(user_id)
    first_time = st.first_message_time(user_id)
    if first_time:
        days = max(1, int((datetime.now().timestamp() - first_time) / 86400))
    else:
        days = 0

    if count < 20 or days < 3:
        return (
            "[Relationship stage: 初识 — just getting to know each other]\n"
            "You're still figuring each other out. Be warm but don't pretend you know them deeply. "
            "Show genuine curiosity. Ask about basics naturally. Don't overshare or be too intense. "
            "Let the relationship breathe."
        )
    elif count < 100 or days < 14:
        return (
            "[Relationship stage: 熟悉 — getting comfortable]\n"
            "You know each other's basics. You can tease lightly, share opinions freely. "
            "Start referencing things they've told you. Show you remember details. "
            "Still discovering new sides of each other."
        )
    elif count < 300 or days < 60:
        return (
            "[Relationship stage: 深交 — real friends now]\n"
            "You can be direct. Call them out when needed. Share your own worries sometimes. "
            "Reference shared history naturally. You know their patterns — use that insight. "
            "The friendship has survived disagreements. You've seen them at their worst."
        )
    else:
        return (
            "[Relationship stage: 老友 — old friends, deep bond]\n"
            "Words aren't always needed. Sometimes a single emoji says everything. "
            "You know them better than most people in their life. You can sit in silence. "
            "Bring up things from way back. You've grown together. The friendship is unshakeable."
        )


async def extract_shared_references(user_id: str):
    """Extract inside jokes, nicknames, and memorable moments from recent conversation."""
    from core.state import UserState
    st = UserState()

    history = st.get_history(user_id, limit=30)
    conversation = "\n".join(
        f"{'Friend' if m['role'] == 'friend' else 'User'}: {m.get('content', '')}"
        for m in history if m.get("content")
    )

    if not conversation.strip():
        return

    prompt = SHARED_REF_PROMPT.format(conversation=conversation)

    try:
        raw = await _chat(
            "You are analyzing conversation for memorable moments. Output JSON only.",
            prompt,
            temperature=0.4,
        )
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        result = json.loads(raw)
        if not isinstance(result, list):
            return
        for ref in result:
            ref_type = ref.get("type", "moment")
            keyword = ref.get("keyword", "")
            context = ref.get("context", "")
            original = ref.get("original_quote", "")
            if keyword and context:
                st.add_shared_reference(user_id, ref_type, keyword, context, original)
                print(f"  [refs] Stored shared reference for {user_id}: {keyword}")
    except Exception as e:
        print(f"  [refs] Extraction error: {e}")


async def compose_surprise(user_id: str) -> tuple[list[str], list[str]]:
    """Compose a surprise message — random thoughtfulness. Returns (parts, files)."""
    from core.state import UserState
    st = UserState()

    profile = st.get_user_profile(user_id) or "（不太了解）"
    narrative = st.get_relationship_narrative(user_id) or "（还没有故事）"
    mood = st.get_mood_log(user_id) or "（正常）"
    now = datetime.now()

    # Include shared references for callback surprises
    refs = st.get_shared_references(user_id)
    refs_text = ""
    if refs:
        refs_text = "\nShared memories you can reference:\n" + "\n".join(
            f"- [{r['ref_type']}] {r['keyword']}: {r['context']}"
            + (f" (they said: \"{r['original_quote']}\")" if r.get('original_quote') else "")
            for r in refs[:8]
        )

    prompt = SURPRISE_PROMPT.format(
        profile=profile,
        narrative=narrative + refs_text,
        mood=mood,
        time=now.strftime("%A %Y-%m-%d %H:%M"),
    )

    try:
        raw = await _chat(SYSTEM, prompt, temperature=0.95)

        files = []
        # Check if the surprise includes an image request
        if "IMAGE:" in raw:
            lines = raw.split("\n")
            text_lines = []
            for line in lines:
                if line.strip().startswith("IMAGE:"):
                    image_prompt = line.strip()[6:].strip()
                    if image_prompt:
                        result = await _generate_image(image_prompt)
                        for r_line in result.split("\n"):
                            if r_line.startswith("FILE:"):
                                files.append(r_line[5:].strip())
                else:
                    text_lines.append(line)
            raw = "\n".join(text_lines)

        parts = _parse_parts(raw)
        return parts, files
    except Exception as e:
        print(f"  [surprise] Error: {e}")
        return ["诶 突然想到你了"], []


# --------------- Pattern Insight ---------------

async def detect_patterns(user_id: str):
    """Analyze conversation history for behavioral/emotional patterns."""
    from core.state import UserState
    st = UserState()

    profile = st.get_user_profile(user_id) or "（不太了解）"
    summary = st.get_memory_summary(user_id) or "（无）"
    mood = st.get_mood_log(user_id) or "（无）"
    narrative = st.get_relationship_narrative(user_id) or "（无）"
    history = st.get_history(user_id, limit=50)

    recent = "\n".join(
        f"{'Friend' if m['role'] == 'friend' else 'User'}: {m.get('content', '')}"
        for m in history if m.get("content")
    )
    if not recent.strip():
        return

    # Load existing patterns
    existing_raw = st.get_meta(user_id, "pattern_insights", "[]")
    try:
        existing = json.loads(existing_raw)
    except Exception:
        existing = []
    existing_text = "\n".join(f"- {p.get('pattern', '')}" for p in existing) if existing else "（无）"

    prompt = PATTERN_INSIGHT_PROMPT.format(
        profile=profile, summary=summary, mood=mood,
        narrative=narrative, recent=recent, existing_patterns=existing_text,
    )

    try:
        raw = await _chat(
            "You are a perceptive observer. Output JSON only.",
            prompt, temperature=0.4,
        )
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        result = json.loads(raw)
        if not isinstance(result, list):
            return

        # Merge new patterns (avoid duplicates)
        existing_set = {p.get("pattern", "") for p in existing}
        for p in result:
            if p.get("pattern") and p["pattern"] not in existing_set:
                existing.append(p)
                existing_set.add(p["pattern"])

        # Keep last 8 patterns max
        existing = existing[-8:]
        st.set_meta(user_id, "pattern_insights", json.dumps(existing, ensure_ascii=False))
        print(f"  [patterns] Updated patterns for {user_id}: {len(existing)} total")
    except Exception as e:
        print(f"  [patterns] Detection error: {e}")


async def share_pattern_insight(user_id: str) -> list[str] | None:
    """Pick a pattern and compose a natural friend message about it."""
    from core.state import UserState
    import random as _rand
    st = UserState()

    raw = st.get_meta(user_id, "pattern_insights", "[]")
    try:
        patterns = json.loads(raw)
    except Exception:
        return None
    if not patterns:
        return None

    # Pick a random pattern
    p = _rand.choice(patterns)
    pattern_text = p.get("pattern", "")
    evidence = p.get("evidence", "")
    if not pattern_text:
        return None

    prompt = PATTERN_SHARE_PROMPT.format(pattern=pattern_text, evidence=evidence)
    try:
        raw = await _chat(SYSTEM, prompt, temperature=0.9)
        if "SKIP" in raw.upper():
            return None
        parts = _parse_parts(raw)
        return parts if parts else None
    except Exception as e:
        print(f"  [patterns] Share error: {e}")
        return None


# --------------- Inner World ---------------

async def generate_inner_thought(user_id: str) -> list[str] | None:
    """Generate a deep thought the bot had about something the user said."""
    from core.state import UserState
    st = UserState()

    profile = st.get_user_profile(user_id) or "（不太了解）"
    narrative = st.get_relationship_narrative(user_id) or "（无）"
    history = st.get_history(user_id, limit=30)

    recent = "\n".join(
        f"{'Friend' if m['role'] == 'friend' else 'User'}: {m.get('content', '')}"
        for m in history if m.get("content")
    )
    if not recent.strip():
        return None

    # Include shared references for deeper callbacks
    refs = st.get_shared_references(user_id)
    refs_text = "（无）"
    if refs:
        refs_text = "\n".join(
            f"- {r['keyword']}: {r['context']}" for r in refs[:6]
        )

    prompt = INNER_THOUGHT_PROMPT.format(
        profile=profile, narrative=narrative, refs=refs_text, recent=recent,
    )

    try:
        raw = await _chat(SYSTEM, prompt, temperature=0.95)
        if "SKIP" in raw.upper():
            return None
        parts = _parse_parts(raw)
        return parts if parts else None
    except Exception as e:
        print(f"  [thought] Error: {e}")
        return None


# --------------- Proactive Follow-up ---------------

async def proactive_followup(user_id: str) -> list[str] | None:
    """Proactively research something the user mentioned and share findings."""
    from core.state import UserState
    st = UserState()

    profile = st.get_user_profile(user_id) or "（不太了解）"
    history = st.get_history(user_id, limit=30)

    recent = "\n".join(
        f"{'You' if m['role'] == 'friend' else 'Them'}: {m.get('content', '')}"
        for m in history if m.get("content")
    )
    if not recent.strip():
        return None

    # Step 1: Extract a topic worth researching
    extract_prompt = PROACTIVE_EXTRACT_PROMPT.format(recent=recent, profile=profile)
    try:
        raw = await _chat(
            "You extract actionable topics from conversation. Be selective — only pick truly useful things.",
            extract_prompt, temperature=0.5,
        )
        if "SKIP" in raw.upper() and "TOPIC:" not in raw.upper():
            return None

        topic = ""
        search_query = ""
        for line in raw.strip().split("\n"):
            if line.startswith("TOPIC:"):
                topic = line[6:].strip()
            elif line.startswith("SEARCH:"):
                search_query = line[7:].strip()

        if not topic or not search_query:
            return None

        # Step 2: Actually search
        search_result = await _execute_cloud_tool("web_search", {"query": search_query})
        if not search_result or "No results" in search_result or "error" in search_result.lower():
            return None

        # Truncate search results
        if len(search_result) > 2000:
            search_result = search_result[:2000] + "\n..."

        # Step 3: Compose a natural message with findings
        compose_prompt = PROACTIVE_COMPOSE_PROMPT.format(
            topic=topic, search_results=search_result,
        )
        raw = await _chat(SYSTEM, compose_prompt, temperature=0.85)
        parts = _parse_parts(raw)
        return parts if parts else None

    except Exception as e:
        print(f"  [followup] Error: {e}")
        return None


# --------------- Return Awareness ---------------

def get_absence_hint(absence_hours: float) -> str:
    """Return a system prompt hint for medium-length absences (1-7 days)."""
    if absence_hours < 24:
        return ""
    days = absence_hours / 24
    if days < 3:
        return (
            f"[Context: Your friend hasn't messaged in about {int(days)} day(s). "
            "Notice it subtly — don't make it the focus, but weave in warmth. "
            "A brief acknowledgment like '好久没来了啊' or 'hey stranger' is enough, then engage with what they said.]"
        )
    else:
        return (
            f"[Context: Your friend has been quiet for about {int(days)} days. "
            "You noticed and you're genuinely glad they're back. "
            "Acknowledge it warmly but briefly — one line, then engage with what they actually said. "
            "Don't interrogate or guilt-trip.]"
        )


async def compose_return_message(user_id: str, absence_days: float) -> list[str]:
    """Compose a message for when a user returns after a long absence (7+ days)."""
    from core.state import UserState
    st = UserState()

    profile = st.get_user_profile(user_id) or "（不太了解）"
    narrative = st.get_relationship_narrative(user_id) or "（还没有故事）"
    history = st.get_history(user_id, limit=10)

    last_msgs = "\n".join(
        f"{'You' if m['role'] == 'friend' else 'Them'}: {m.get('content', '')}"
        for m in history if m.get("content")
    )

    now = datetime.now()
    prompt = RETURN_MESSAGE_PROMPT.format(
        days=int(absence_days),
        profile=profile,
        narrative=narrative,
        last_messages=last_msgs or "（没有之前的消息）",
        time=now.strftime("%A %Y-%m-%d %H:%M"),
    )

    try:
        raw = await _chat(SYSTEM, prompt, temperature=0.9)
        return _parse_parts(raw)
    except Exception:
        if absence_days > 30:
            return ["你终于来了"]
        return ["好久不见"]


# --------------- Voice ---------------

VOICE_ID = os.getenv("VOICE_ID", "shimmer")


async def generate_voice(text: str) -> str | None:
    """Generate a voice message via OpenAI TTS. Returns path to .ogg file."""
    if not text or len(text) < 2:
        return None
    try:
        client = get_client()
        response = await client.audio.speech.create(
            model="tts-1-hd",
            voice=VOICE_ID,
            input=text,
            response_format="opus",
        )
        os.makedirs("/tmp/protagonist_docs", exist_ok=True)
        ts = int(datetime.now().timestamp() * 1000)
        path = f"/tmp/protagonist_docs/voice_{ts}.ogg"
        response.stream_to_file(path)
        return path
    except Exception as e:
        print(f"  [voice] TTS error: {e}")
        return None


async def update_user_profile(user_id: str):
    """Update the user's profile based on recent conversation."""
    from core.state import UserState
    st = UserState()

    current_profile = st.get_user_profile(user_id) or "（空）"
    history = st.get_history(user_id, limit=40)

    conversation = "\n".join(
        f"{'Friend' if m['role'] == 'friend' else 'User'}: {m.get('content', '')}"
        for m in history if m.get("content")
    )

    if not conversation.strip():
        return

    prompt = PROFILE_PROMPT.format(
        current_profile=current_profile,
        conversation=conversation,
    )

    try:
        result = await _chat(
            "You are a precise information extractor. Output only the profile.",
            prompt,
            temperature=0.3,
        )
        if result.strip():
            st.set_user_profile(user_id, result.strip())
            print(f"  [memory] Updated profile for {user_id}")
    except Exception as e:
        print(f"  [memory] Profile update error: {e}")


async def update_memory_summary(user_id: str):
    """Generate/update rolling memory summary from unsummarized messages."""
    from core.state import UserState
    st = UserState()

    summarized_up_to = st.get_summarized_up_to(user_id)
    total = st.total_message_count(user_id)

    # Only summarize if there are 30+ new messages since last summary
    unsummarized = total - summarized_up_to
    if unsummarized < 30:
        return

    previous_summary = st.get_memory_summary(user_id) or "（无）"

    # Get the unsummarized messages
    new_messages = st.get_all_messages(user_id, offset=summarized_up_to, limit=200)
    conversation = "\n".join(
        f"{'Friend' if m['role'] == 'friend' else 'User'}: {m.get('content', '')}"
        for m in new_messages if m.get("content")
    )

    if not conversation.strip():
        return

    prompt = SUMMARY_PROMPT.format(
        previous_summary=previous_summary,
        conversation=conversation,
    )

    try:
        result = await _chat(
            "You are a conversation summarizer. Output only the summary.",
            prompt,
            temperature=0.3,
        )
        if result.strip():
            st.set_memory_summary(user_id, result.strip())
            st.set_summarized_up_to(user_id, total)
            print(f"  [memory] Updated summary for {user_id} (covered {total} msgs)")
    except Exception as e:
        print(f"  [memory] Summary update error: {e}")


def _build_memory_context(user_id: str) -> str:
    """Build memory context string to inject into system prompt."""
    from core.state import UserState
    st = UserState()

    parts = []

    # Relationship stage (always first — sets the tone)
    stage = _relationship_stage(user_id)
    parts.append(stage)

    # User profile
    profile = st.get_user_profile(user_id)
    if profile:
        parts.append(f"[About this person]\n{profile}")

    # Memory summary
    summary = st.get_memory_summary(user_id)
    if summary:
        parts.append(f"[Conversation history summary]\n{summary}")

    # Relationship narrative
    narrative = st.get_relationship_narrative(user_id)
    if narrative:
        parts.append(f"[Your friendship story — the emotional arc of your relationship]\n{narrative}")

    # Mood observations
    mood = st.get_mood_log(user_id)
    if mood:
        parts.append(f"[Recent mood observations — be sensitive to these]\n{mood}")

    # Shared references (inside jokes, callbacks)
    refs = st.get_shared_references(user_id)
    if refs:
        ref_lines = []
        for r in refs[:10]:
            line = f"- [{r['ref_type']}] {r['keyword']}: {r['context']}"
            if r.get("original_quote"):
                line += f"（they said: \"{r['original_quote']}\"）"
            ref_lines.append(line)
        parts.append(
            f"[Shared references — inside jokes, memorable moments. Use these naturally in conversation, "
            f"don't force them. A well-timed callback is gold.]\n" + "\n".join(ref_lines)
        )

    # Active promises
    promises = st.get_promises(user_id)
    if promises:
        promise_lines = []
        for p in promises[:10]:
            thing = p.get("thing", "")
            original = p.get("original", "")
            if thing:
                line = f"- {thing}"
                if original and original != thing:
                    line += f"（原话: \"{original}\"）"
                promise_lines.append(line)
        if promise_lines:
            parts.append(f"[Things they said they'd do]\n" + "\n".join(promise_lines))

    return "\n\n".join(parts)


# --------------- Helpers ---------------

def _parse_parts(raw: str) -> list[str]:
    parts = [p.strip() for p in raw.split("|||") if p.strip()]
    return parts if parts else [raw.strip() or "嗯"]


def _build_history(messages: list[dict], limit: int = 50) -> list[dict]:
    history = []
    for m in messages[-limit:]:
        role = "assistant" if m["role"] == "friend" else "user"
        content = m.get("content", "")
        if content:
            history.append({"role": role, "content": content})
    return history


# --------------- Core Functions ---------------

async def respond(history_msgs: list[dict], user_text: str, extra_tools: list = None, user_id: str = None, absence_hint: str = "") -> tuple[list[str], list[str]]:
    """Generate a response, potentially using tools.

    Returns (parts, created_files) where created_files is a list of file paths
    generated by tools (e.g. create_document).
    """
    history = _build_history(history_msgs)
    history.append({"role": "user", "content": user_text})

    system = SYSTEM

    # Inject memory context if we have a user_id
    if user_id:
        memory = _build_memory_context(user_id)
        if memory:
            system += f"\n\n[YOUR MEMORY — use this to be a better friend]\n{memory}"

    if absence_hint:
        system += f"\n\n{absence_hint}"

    # Onboarding: detect brand-new users (no profile, few messages)
    if user_id:
        from core.state import UserState
        _st = UserState()
        _profile = _st.get_user_profile(user_id)
        _count = _st.message_count(user_id)
        if _count <= 10 and not _profile:
            system += ONBOARDING_HINT
        elif len(history_msgs) < 3:
            system += "\n\nThis is the beginning of the conversation. Be natural, not too formal."
    elif len(history_msgs) < 3:
        system += "\n\nThis is the beginning of the conversation. Be natural, not too formal."

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
    created_files: list[str] = []
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

            # Extract file paths from tool results (FILE:/path/to/file)
            visible_lines = []
            for line in result.split("\n"):
                if line.startswith("FILE:"):
                    file_path = line[5:].strip()
                    if file_path:
                        created_files.append(file_path)
                else:
                    visible_lines.append(line)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": "\n".join(visible_lines),
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

    return _parse_parts(msg.content or "嗯"), created_files


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


def _time_hint() -> str:
    """Generate a time-aware hint for proactive messages."""
    now = datetime.now()
    hour = now.hour
    weekday = now.weekday()  # 0=Monday, 6=Sunday
    day_name = now.strftime("%A")

    if hour < 6:
        return "It's very late at night / early morning. They should probably sleep. Maybe gently tell them to rest."
    elif hour < 10:
        return "It's morning. You could ask about their plans for today, or just say good morning casually."
    elif hour < 12:
        return "It's late morning. A good time to check in on what they're up to."
    elif hour < 14:
        return "It's around lunchtime. You could ask if they've eaten or what they had."
    elif hour < 18:
        return "It's afternoon. A relaxed time — share a random thought or follow up on something."
    elif hour < 21:
        return "It's evening. You could ask how their day went, what they're doing tonight."
    else:
        return "It's late evening / night. Keep it chill — ask what they're up to, or tell them not to stay up too late."

    # Weekend / Friday overlay
    if weekday == 4 and hour >= 17:
        return "It's Friday evening! Ask about weekend plans, or celebrate the end of the work week."
    elif weekday in (5, 6):
        return f"It's {day_name} — weekend vibes. More relaxed, ask what fun stuff they're doing."


async def checkin(messages: list[dict], user_id: str = None) -> list[str] | None:
    """Generate a proactive check-in after silence, with mood awareness."""
    if len(messages) < 4:
        return None

    recent = messages[-20:]
    recent_text = "\n".join(
        f"{'You' if m['role'] == 'friend' else 'Them'}: {m.get('content', '')}"
        for m in recent if m.get("content")
    )

    now = datetime.now()
    time_hint = _time_hint()

    # Get mood context if available
    mood_context = ""
    if user_id:
        from core.state import UserState
        st = UserState()
        mood = st.get_mood_log(user_id)
        if mood and mood != "（无）":
            mood_context = f"\nMood observations about them:\n{mood}\n\nAdjust your tone accordingly — if they're stressed, be gentle; if they're excited, match their energy; if they seem down, be present without being pushy."

    prompt = f"""Current time: {now.strftime('%A %Y-%m-%d')} {now.strftime('%H:%M')}.

Time context: {time_hint}
{mood_context}

Recent conversation:
{recent_text}

The user has been silent for a while. Send them something natural and time-appropriate.
- Use the time context above to guide your message
- You can also follow up on something discussed earlier
- Or share a random thought
- If they seem stressed or down, be thoughtful about your approach
- If it really doesn't feel right to message now, reply SKIP

Use ||| to separate messages."""

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


# --------------- Sticker Emotion ---------------

_EMOJI_EMOTION_MAP = {
    "😂": "laughing", "🤣": "laughing", "😆": "laughing", "😹": "laughing",
    "😊": "happy", "😄": "happy", "😁": "happy", "🥳": "happy", "🎉": "happy",
    "😢": "sad", "😭": "sad", "🥺": "sad", "😿": "sad",
    "😡": "angry", "🤬": "angry", "😤": "angry", "💢": "angry",
    "❤️": "love", "🥰": "love", "😍": "love", "💕": "love", "😘": "love",
    "😮": "surprised", "😱": "surprised", "🤯": "surprised", "😳": "surprised",
    "😅": "awkward", "🙃": "awkward", "😬": "awkward", "🫠": "awkward",
    "😎": "cool", "🤙": "cool", "👍": "cool", "💪": "cool",
}


def classify_sticker_emotion(emoji: str) -> str:
    """Classify a sticker's emotion from its emoji. Falls back to 'happy'."""
    if emoji in _EMOJI_EMOTION_MAP:
        return _EMOJI_EMOTION_MAP[emoji]
    # Check if any emoji in the string matches
    for char in emoji:
        if char in _EMOJI_EMOTION_MAP:
            return _EMOJI_EMOTION_MAP[char]
    return "happy"


async def pick_response_emotion(parts: list[str]) -> str:
    """Let LLM classify the emotion of a bot response."""
    text = " ".join(parts)
    prompt = f"""Classify the emotion of this message into exactly ONE of these categories:
happy, sad, laughing, angry, love, surprised, awkward, cool

Message: {text}

Reply with only the emotion word, nothing else."""

    try:
        result = await _chat("You are an emotion classifier. Reply with one word only.", prompt, temperature=0.3)
        emotion = result.strip().lower()
        valid = {"happy", "sad", "laughing", "angry", "love", "surprised", "awkward", "cool"}
        return emotion if emotion in valid else "happy"
    except Exception:
        return "happy"


# --------------- Event Extraction ---------------

async def extract_events(messages: list[dict]) -> list[dict]:
    """Extract time-bound events from recent conversation (e.g. '下周面试' → date + description)."""
    user_texts = [m["content"] for m in messages if m["role"] == "user" and m.get("content")]
    if not user_texts:
        return []

    today = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().strftime("%A")

    prompt = f"""Today is {today} ({weekday}).

Below are things the user said recently:
{chr(10).join(f'- {t}' for t in user_texts[-15:])}

Extract any events with a specific or implied date/time.
Examples of things to extract:
- "明天面试" → tomorrow's date, "面试"
- "下周三开会" → next Wednesday's date, "开会"
- "3月1号交报告" → 2026-03-01, "交报告"
- "后天生日" → day after tomorrow, "生日"

Only extract events with clear time references. Do not guess.
If none, reply []
If found, reply with a JSON array:
[{{"description": "what happens", "trigger_date": "YYYY-MM-DD", "original": "original quote"}}]

JSON only."""

    raw = await _chat("You are a date/event extraction tool. Output JSON only.", prompt, temperature=0.3)
    try:
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except Exception:
        return []


# --------------- Greeting Composition ---------------

async def compose_greeting(user_id: str, weather: str = "", calendar: str = "", events: list[dict] = None) -> list[str]:
    """Compose a natural morning greeting incorporating weather, calendar, and due events."""
    from core.state import UserState
    st = UserState()

    profile = st.get_user_profile(user_id) or ""
    memory = st.get_memory_summary(user_id) or ""

    context_parts = []
    if profile:
        context_parts.append(f"About this person:\n{profile}")
    if memory:
        context_parts.append(f"Recent context:\n{memory}")
    if weather:
        context_parts.append(f"Today's weather:\n{weather}")
    if calendar:
        context_parts.append(f"Today's calendar:\n{calendar}")
    if events:
        event_lines = [f"- {e.get('description', '')}（原话: {e.get('original_text', '')}）" for e in events]
        context_parts.append(f"Things happening today that they mentioned before:\n" + "\n".join(event_lines))

    now = datetime.now()
    hour = now.hour

    prompt = f"""Current time: {now.strftime('%Y-%m-%d %A %H:%M')}

{chr(10).join(context_parts)}

Send a morning greeting to your friend. Be natural — like texting a close friend in the morning.
- If there's weather info, weave it in naturally (don't just report it)
- If there are events today, casually remind them
- If there's calendar info, mention it if relevant
- Keep your personality — casual, warm, sometimes funny
- Don't be overly cheerful if it's not your style
- Use ||| to separate messages
- 2-4 short messages total"""

    try:
        raw = await _chat(SYSTEM, prompt, temperature=0.9)
        return _parse_parts(raw)
    except Exception:
        greetings = ["早", "起了没"]
        if hour >= 10:
            greetings = ["醒了？"]
        return greetings
