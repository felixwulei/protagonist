#!/usr/bin/env python3
"""Protagonist Menu Bar App — local tool bridge.

Sits in the macOS menu bar. Runs a local HTTP server that exposes
local tools (Mail, Calendar, WeChat, Claude Code, files, apps, etc.)
for the friend agent to call.

Users can toggle individual tools on/off from the menu bar.

Run: python3 app.py
"""
from __future__ import annotations

import os
import sys
import json
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from dotenv import load_dotenv
# Load .env from telegram dir (shared config)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "telegram", ".env"))

import rumps

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from menubar.tools import execute_tool, TOOL_NAMES

PORT = 18800
CONFIG_PATH = os.path.expanduser("~/.protagonist/tools.json")

# Tool categories for cleaner menu display
TOOL_CATEGORIES = {
    "Email": ["read_emails", "search_emails", "send_email"],
    "Screen": ["capture_screen", "check_wechat"],
    "Code": ["run_claude_code"],
    "Files": ["find_files", "read_file"],
    "Apps": ["open_app", "quit_app", "run_command"],
    "Calendar": ["get_calendar_events", "create_reminder"],
    "Music": ["music_play", "music_pause", "music_next", "music_previous",
              "music_now_playing", "music_search_play"],
}

# Global set of enabled tools — shared between menu bar app and HTTP server
enabled_tools: set[str] = set()


def _load_config() -> set[str]:
    """Load enabled tools from config file."""
    try:
        with open(CONFIG_PATH, "r") as f:
            data = json.load(f)
            return set(data.get("enabled", TOOL_NAMES))
    except (FileNotFoundError, json.JSONDecodeError):
        # Default: all tools enabled
        return set(TOOL_NAMES)


def _save_config(tools: set[str]):
    """Save enabled tools to config file."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump({"enabled": sorted(tools)}, f, indent=2)


# --------------- HTTP Tool Server ---------------

class ToolHandler(BaseHTTPRequestHandler):
    """Handles tool execution requests from the agent."""

    def do_POST(self):
        if self.path == "/tool":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}

            name = body.get("name", "")
            args = body.get("args", {})

            # Check if tool is enabled
            if name not in enabled_tools:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "result": f"Tool '{name}' is disabled by the user."
                }).encode())
                return

            # Run async tool in event loop
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(execute_tool(name, args))
            except Exception as e:
                result = f"Error: {e}"
            finally:
                loop.close()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"result": result}).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "status": "ok",
                "tools": sorted(enabled_tools),
            }).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"  [server] {args[0]}")


# --------------- Menu Bar App ---------------

class ProtagonistApp(rumps.App):
    def __init__(self):
        global enabled_tools
        enabled_tools = _load_config()

        super().__init__(
            "Protagonist",
            icon=None,
            title="🤝",
        )
        self.server = None
        self.server_thread = None
        self._build_menu()
        self._start_server()

    def _build_menu(self):
        self.menu.clear()
        self.menu = [
            rumps.MenuItem("Status: Starting...", callback=None),
            None,
            rumps.MenuItem(
                f"Tools: {len(enabled_tools)}/{len(TOOL_NAMES)} enabled",
                callback=None,
            ),
            None,
        ]

        # Add category submenus with toggles
        for category, tools in TOOL_CATEGORIES.items():
            submenu = rumps.MenuItem(category)
            for tool_name in tools:
                item = rumps.MenuItem(
                    tool_name,
                    callback=self._toggle_tool,
                )
                item.state = 1 if tool_name in enabled_tools else 0
                submenu.add(item)
            self.menu.add(submenu)

        self.menu.add(None)

        enable_all = rumps.MenuItem("Enable All", callback=self._enable_all)
        disable_all = rumps.MenuItem("Disable All", callback=self._disable_all)
        self.menu.add(enable_all)
        self.menu.add(disable_all)

        self.menu.add(None)

    def _toggle_tool(self, sender):
        global enabled_tools
        tool_name = sender.title
        if tool_name in enabled_tools:
            enabled_tools.discard(tool_name)
            sender.state = 0
            print(f"[menubar] Disabled: {tool_name}")
        else:
            enabled_tools.add(tool_name)
            sender.state = 1
            print(f"[menubar] Enabled: {tool_name}")
        _save_config(enabled_tools)
        self._update_tool_count()

    def _enable_all(self, _):
        global enabled_tools
        enabled_tools = set(TOOL_NAMES)
        _save_config(enabled_tools)
        self._refresh_checks()
        print("[menubar] All tools enabled")

    def _disable_all(self, _):
        global enabled_tools
        enabled_tools = set()
        _save_config(enabled_tools)
        self._refresh_checks()
        print("[menubar] All tools disabled")

    def _refresh_checks(self):
        """Update all checkmarks after enable/disable all."""
        for category in TOOL_CATEGORIES:
            if category in self.menu:
                for tool_name in TOOL_CATEGORIES[category]:
                    if tool_name in self.menu[category]:
                        self.menu[category][tool_name].state = (
                            1 if tool_name in enabled_tools else 0
                        )
        self._update_tool_count()

    def _update_tool_count(self):
        for key in self.menu.keys():
            if "Tools:" in str(key):
                self.menu[key].title = (
                    f"Tools: {len(enabled_tools)}/{len(TOOL_NAMES)} enabled"
                )
                break

    def _start_server(self):
        def run():
            self.server = HTTPServer(("127.0.0.1", PORT), ToolHandler)
            print(f"[menubar] Tool server running on http://127.0.0.1:{PORT}")
            print(f"[menubar] {len(enabled_tools)}/{len(TOOL_NAMES)} tools enabled")
            rumps.Timer(lambda _: self._update_status("Connected"), 0.5).start()
            self.server.serve_forever()

        self.server_thread = threading.Thread(target=run, daemon=True)
        self.server_thread.start()

    def _update_status(self, status: str):
        for key in self.menu.keys():
            if "Status:" in str(key):
                self.menu[key].title = f"Status: {status}"
                break

    @rumps.clicked("Quit Protagonist")
    def quit_app(self, _):
        if self.server:
            self.server.shutdown()
        rumps.quit_application()


# --------------- Entry Point ---------------

if __name__ == "__main__":
    print("[menubar] Protagonist Menu Bar App starting...")
    print(f"[menubar] Port: {PORT}")
    ProtagonistApp().run()
