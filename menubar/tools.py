"""Local macOS tools — executed on the user's machine via the menu bar app."""
from __future__ import annotations

import os
import json
import asyncio
import base64
import tempfile
import subprocess


# --------------- Tool Registry ---------------

TOOL_NAMES = [
    "read_emails", "search_emails", "send_email",
    "capture_screen", "check_wechat",
    "run_claude_code",
    "find_files", "read_file",
    "open_app", "quit_app", "run_command",
    "get_calendar_events", "create_reminder",
    "music_play", "music_pause", "music_next", "music_previous",
    "music_now_playing", "music_search_play",
]

# Tool definitions for OpenAI function calling (sent to agent when local tools are available)
TOOL_DEFINITIONS = [
    {"type": "function", "function": {"name": "read_emails", "description": "Read recent emails from Mail.app", "parameters": {"type": "object", "properties": {"count": {"type": "integer", "description": "How many emails", "default": 5}, "unread_only": {"type": "boolean", "description": "Unread only", "default": False}}}}},
    {"type": "function", "function": {"name": "search_emails", "description": "Search emails by keyword", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Search keyword"}, "count": {"type": "integer", "default": 5}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "send_email", "description": "Send an email via Mail.app", "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "subject", "body"]}}},
    {"type": "function", "function": {"name": "capture_screen", "description": "Screenshot the screen or a specific app and analyze what's visible", "parameters": {"type": "object", "properties": {"app_name": {"type": "string", "description": "App to capture (omit for full screen)"}, "question": {"type": "string", "description": "What to look for", "default": "Describe what's on screen"}}}}},
    {"type": "function", "function": {"name": "check_wechat", "description": "Screenshot WeChat and check for unread messages", "parameters": {"type": "object", "properties": {"question": {"type": "string", "default": "Any unread messages? Who sent them?"}}}}},
    {"type": "function", "function": {"name": "run_claude_code", "description": "Run Claude Code CLI for a programming task", "parameters": {"type": "object", "properties": {"task": {"type": "string", "description": "The programming task"}, "working_dir": {"type": "string", "description": "Working directory"}}, "required": ["task"]}}},
    {"type": "function", "function": {"name": "find_files", "description": "Search for files using Spotlight", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "file_type": {"type": "string", "description": "e.g. pdf, docx, py"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "read_file", "description": "Read a file's contents", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "open_app", "description": "Open an application", "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "quit_app", "description": "Quit an application", "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "run_command", "description": "Run a shell command", "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer", "default": 30}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "get_calendar_events", "description": "Get upcoming calendar events", "parameters": {"type": "object", "properties": {"days": {"type": "integer", "default": 1}}}}},
    {"type": "function", "function": {"name": "create_reminder", "description": "Create a reminder", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "due_date": {"type": "string", "description": "YYYY-MM-DD HH:MM"}}, "required": ["title"]}}},
    {"type": "function", "function": {"name": "music_play", "description": "Resume or start playing music (Apple Music or Spotify)", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "music_pause", "description": "Pause the currently playing music", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "music_next", "description": "Skip to the next track", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "music_previous", "description": "Go back to the previous track", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "music_now_playing", "description": "Get info about the currently playing track", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "music_search_play", "description": "Search for a song, artist or album and play it", "parameters": {"type": "object", "properties": {"query": {"type": "string", "description": "Song name, artist, or album to search and play"}}, "required": ["query"]}}},
]


async def execute_tool(name: str, args: dict) -> str:
    """Execute a local tool and return text result."""
    print(f"  [tool] {name}({json.dumps(args, ensure_ascii=False)})")
    try:
        fn = _TOOL_MAP.get(name)
        if not fn:
            return f"Unknown tool: {name}"
        result = await fn(**args)
        if len(result) > 4000:
            result = result[:4000] + "\n...(truncated)"
        return result
    except Exception as e:
        return f"Tool error: {e}"


# --------------- Helpers ---------------

async def _applescript(script: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return f"AppleScript error: {stderr.decode().strip()}"
    return stdout.decode().strip()


async def _shell(cmd: str, timeout: int = 30) -> str:
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode() + stderr.decode()
        return output.strip() if output.strip() else "(no output)"
    except asyncio.TimeoutError:
        proc.kill()
        return "(timed out)"
    except Exception as e:
        return f"Error: {e}"


async def _screenshot_analyze(question: str = "Describe what's on screen", app_name: str = None) -> str:
    """Screenshot + GPT-4V analysis."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    tmp = tempfile.mktemp(suffix=".png")
    try:
        if app_name:
            await _applescript(f'tell application "{app_name}" to activate')
            await asyncio.sleep(0.8)
        await _shell(f'screencapture -x "{tmp}"', timeout=5)
        if not os.path.exists(tmp):
            return "Screenshot failed"
        with open(tmp, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        response = await client.chat.completions.create(
            model=model, max_tokens=500,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": question},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}", "detail": "low"}},
            ]}],
        )
        return response.choices[0].message.content or "Could not analyze"
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# --------------- Tool Implementations ---------------

async def _read_emails(count: int = 5, unread_only: bool = False) -> str:
    f = "whose read status is false" if unread_only else ""
    return await _applescript(f'''
    tell application "Mail"
        set output to ""
        set msgs to (messages of inbox {f})
        set n to {count}
        if (count of msgs) < n then set n to (count of msgs)
        repeat with i from 1 to n
            set m to item i of msgs
            set isRead to read status of m
            set mk to ""
            if not isRead then set mk to "[UNREAD] "
            set output to output & mk & "From: " & sender of m & " | " & subject of m & " | " & (date received of m as string) & linefeed
        end repeat
        return output
    end tell''') or "No emails found"


async def _search_emails(query: str, count: int = 5) -> str:
    q = query.replace('"', '\\"')
    return await _applescript(f'''
    tell application "Mail"
        set output to ""
        set results to (messages of inbox whose subject contains "{q}" or sender contains "{q}")
        set n to {count}
        if (count of results) < n then set n to (count of results)
        repeat with i from 1 to n
            set m to item i of results
            set output to output & "From: " & sender of m & " | " & subject of m & " | " & (date received of m as string) & linefeed
        end repeat
        if output is "" then return "No matching emails"
        return output
    end tell''')


async def _send_email(to: str, subject: str, body: str) -> str:
    s = subject.replace('"', '\\"')
    b = body.replace('"', '\\"')
    result = await _applescript(f'''
    tell application "Mail"
        set newMsg to make new outgoing message with properties {{subject:"{s}", content:"{b}", visible:true}}
        tell newMsg to make new to recipient at end of to recipients with properties {{address:"{to}"}}
        send newMsg
    end tell''')
    return f"Email sent to {to}" if "error" not in result.lower() else f"Failed: {result}"


async def _capture_screen(app_name: str = None, question: str = "Describe what's on screen") -> str:
    return await _screenshot_analyze(question=question, app_name=app_name)


async def _check_wechat(question: str = "Any unread messages? Who sent them?") -> str:
    check = await _applescript('tell application "System Events" to (name of processes) contains "WeChat"')
    if "true" not in check.lower():
        return "WeChat is not running"
    return await _screenshot_analyze(f"This is WeChat. {question}", app_name="WeChat")


async def _run_claude_code(task: str, working_dir: str = None) -> str:
    cmd = f'claude -p {json.dumps(task, ensure_ascii=False)} --output-format text'
    if working_dir:
        cmd = f'cd {json.dumps(working_dir)} && {cmd}'
    print(f"  [claude-code] {task[:80]}...")
    result = await _shell(cmd, timeout=120)
    print(f"  [claude-code] Done ({len(result)} chars)")
    return result


async def _find_files(query: str, file_type: str = None) -> str:
    cmd = f'mdfind "{query}" | grep -i "\\.{file_type}$" | head -15' if file_type else f'mdfind "{query}" | head -15'
    return await _shell(cmd, timeout=10) or f"No files found for '{query}'"


async def _read_file(path: str) -> str:
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return f"File not found: {path}"
    ext = os.path.splitext(expanded)[1].lower()
    if ext in (".pdf", ".docx", ".doc", ".rtf"):
        return await _shell(f'textutil -stdout -convert txt "{expanded}" 2>/dev/null || strings "{expanded}" | head -100')
    try:
        with open(expanded, "r", errors="replace") as f:
            return f.read(8000)
    except Exception as e:
        return f"Read failed: {e}"


async def _open_app(app_name: str) -> str:
    await _applescript(f'tell application "{app_name}" to activate')
    return f"Opened {app_name}"


async def _quit_app(app_name: str) -> str:
    result = await _applescript(f'tell application "{app_name}" to quit')
    return f"Quit {app_name}" if "error" not in result.lower() else f"Could not quit {app_name}"


async def _run_command(command: str, timeout: int = 30) -> str:
    return await _shell(command, timeout=timeout)


async def _get_calendar_events(days: int = 1) -> str:
    return await _applescript(f'''
    set today to current date
    set endDate to today + ({days} * days)
    set output to ""
    tell application "Calendar"
        repeat with cal in calendars
            set evts to (every event of cal whose start date >= today and start date <= endDate)
            repeat with evt in evts
                set output to output & summary of evt & " | " & (start date of evt as string) & " - " & (end date of evt as string) & linefeed
            end repeat
        end repeat
    end tell
    if output is "" then return "No events in the next {days} day(s)"
    return output''') or f"No events in the next {days} day(s)"


async def _create_reminder(title: str, due_date: str = None) -> str:
    t = title.replace('"', '\\"')
    if due_date:
        script = f'tell application "Reminders" to make new reminder with properties {{name:"{t}", due date:date "{due_date}"}}'
    else:
        script = f'tell application "Reminders" to make new reminder with properties {{name:"{t}"}}'
    result = await _applescript(script)
    return f"Reminder created: {title}" if "error" not in result.lower() else f"Failed: {result}"


def _music_app() -> str:
    """Detect which music app is running: Music (Apple Music) or Spotify."""
    # Check Spotify first since it's more common for global users
    import subprocess as sp
    result = sp.run(
        ["osascript", "-e", 'tell application "System Events" to (name of processes) contains "Spotify"'],
        capture_output=True, text=True, timeout=3,
    )
    if "true" in result.stdout.lower():
        return "Spotify"
    return "Music"


async def _music_play() -> str:
    app = _music_app()
    await _applescript(f'tell application "{app}" to activate')
    await asyncio.sleep(0.3)
    # If nothing is queued, play the user's library
    result = await _applescript(f'''
    tell application "{app}"
        if player state is not playing then
            try
                play playlist "Library"
            on error
                play
            end try
        else
            play
        end if
    end tell''')
    await asyncio.sleep(0.5)
    return await _music_now_playing()


async def _music_pause() -> str:
    app = _music_app()
    await _applescript(f'tell application "{app}" to pause')
    return f"Paused {app}"


async def _music_next() -> str:
    app = _music_app()
    await _applescript(f'tell application "{app}" to next track')
    # Get new track info
    await asyncio.sleep(0.5)
    return await _music_now_playing()


async def _music_previous() -> str:
    app = _music_app()
    await _applescript(f'tell application "{app}" to previous track')
    await asyncio.sleep(0.5)
    return await _music_now_playing()


async def _music_now_playing() -> str:
    app = _music_app()
    if app == "Spotify":
        result = await _applescript('''
        tell application "Spotify"
            if player state is playing then
                set t to name of current track
                set a to artist of current track
                set al to album of current track
                return "Playing: " & t & " by " & a & " (Album: " & al & ")"
            else
                return "Not playing"
            end if
        end tell''')
    else:
        result = await _applescript('''
        tell application "Music"
            if player state is playing then
                set t to name of current track
                set a to artist of current track
                set al to album of current track
                return "Playing: " & t & " by " & a & " (Album: " & al & ")"
            else
                return "Not playing"
            end if
        end tell''')
    return result or "No music app is playing"


async def _music_search_play(query: str) -> str:
    app = _music_app()
    q = query.replace('"', '\\"')
    if app == "Spotify":
        uri = f"spotify:search:{q}"
        await _shell(f'open "{uri}"', timeout=5)
        await asyncio.sleep(1.5)
        await _applescript('''
        tell application "Spotify" to activate
        delay 0.5
        tell application "System Events"
            keystroke return
        end tell''')
        await asyncio.sleep(1)
        return await _music_now_playing()
    else:
        import urllib.parse

        # Step 1: look up canonical track name via iTunes API
        encoded = urllib.parse.quote_plus(query)
        search_names = [q]  # always search the original query
        api_name, api_artist, api_url = "", "", ""
        # Search both CN and US stores to get both Chinese and English names
        for country in ["CN", "US"]:
            api_result = await _shell(
                f'curl -s "https://itunes.apple.com/search?term={encoded}&media=music&limit=1&country={country}"',
                timeout=10,
            )
            try:
                data = json.loads(api_result)
                if data.get("resultCount", 0) > 0:
                    track = data["results"][0]
                    name = track.get("trackName", "")
                    artist = track.get("artistName", "")
                    url = track.get("trackViewUrl", "")
                    if not api_name:
                        api_name = name
                    if not api_artist:
                        api_artist = artist
                    if not api_url:
                        api_url = url
                    for n in [name, artist]:
                        clean = n.replace('"', '\\"')
                        if clean and clean not in search_names:
                            search_names.append(clean)
            except (json.JSONDecodeError, KeyError):
                pass

        # Step 2: search ALL playlists with each name variant separately
        result = "NOT_FOUND"
        for search_term in search_names:
            st = search_term.replace('"', '\\"')
            print(f"  [music] Searching playlists for: {st}")
            r = await _applescript(
                f'tell application "Music"\n'
                f'activate\n'
                f'set allPlaylists to every playlist\n'
                f'repeat with p in allPlaylists\n'
                f'try\n'
                f'set results to (every track of p whose name contains "{st}")\n'
                f'if (count of results) > 0 then\n'
                f'set t to item 1 of results\n'
                f'play t\n'
                f'return "Playing: " & name of t & " by " & artist of t\n'
                f'end if\n'
                f'end try\n'
                f'try\n'
                f'set results to (every track of p whose artist contains "{st}")\n'
                f'if (count of results) > 0 then\n'
                f'set t to item 1 of results\n'
                f'play t\n'
                f'return "Playing: " & name of t & " by " & artist of t\n'
                f'end if\n'
                f'end try\n'
                f'end repeat\n'
                f'return "NOT_FOUND"\n'
                f'end tell'
            )
            print(f"  [music] Result: {r[:100]}")
            if r.startswith("Playing:"):
                result = r
                break
        if "NOT_FOUND" not in result:
            return result

        # Step 3: not in any playlist — open in Apple Music
        if api_url:
            await _shell(f'open "{api_url}"', timeout=5)
            return f"Found: {api_name} by {api_artist}. Opened in Apple Music — tap play to start."
        return f"Could not find '{query}'."


_TOOL_MAP = {
    "read_emails": _read_emails,
    "search_emails": _search_emails,
    "send_email": _send_email,
    "capture_screen": _capture_screen,
    "check_wechat": _check_wechat,
    "run_claude_code": _run_claude_code,
    "find_files": _find_files,
    "read_file": _read_file,
    "open_app": _open_app,
    "quit_app": _quit_app,
    "run_command": _run_command,
    "get_calendar_events": _get_calendar_events,
    "create_reminder": _create_reminder,
    "music_play": _music_play,
    "music_pause": _music_pause,
    "music_next": _music_next,
    "music_previous": _music_previous,
    "music_now_playing": _music_now_playing,
    "music_search_play": _music_search_play,
}
