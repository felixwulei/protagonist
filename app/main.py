#!/usr/bin/env python3
"""Protagonist — your AI friend lives in Telegram.

Single entry point: runs the menu bar app + Telegram bot together.
"""
from __future__ import annotations

import os
import sys
import asyncio
import threading
import json
import urllib.request
import webbrowser

# Ensure project root is in path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import rumps

from app import config
from app.setup_wizard import run_setup


# --------------- Tool Categories (for menu bar display) ---------------

TOOL_CATEGORIES = {
    "Email": ["read_emails", "search_emails", "send_email"],
    "Screen": ["capture_screen", "check_wechat"],
    "Code": ["run_claude_code"],
    "Files": ["find_files", "read_file"],
    "Apps": ["open_app", "quit_app", "run_command"],
    "Calendar": ["get_calendar_events", "create_reminder"],
    "Music": [
        "music_play", "music_pause", "music_next", "music_previous",
        "music_now_playing", "music_search_play",
    ],
    "Documents": ["create_document"],
}


class ProtagonistApp(rumps.App):
    def __init__(self):
        super().__init__("Protagonist", icon=None, title="\U0001f91d")
        self.bot_thread = None
        self.bot_running = False
        self._build_menu()

    def _build_menu(self):
        cfg = config.load()
        enabled = config.get_enabled_tools()
        total = len(cfg.get("tools", {}))

        self.menu.clear()

        if config.is_setup_complete():
            self.menu = [
                rumps.MenuItem("Status: Starting bot...", callback=None),
                None,
                rumps.MenuItem(
                    f"Tools: {len(enabled)}/{total} enabled", callback=None,
                ),
                None,
            ]
            # Tool category toggles
            for category, tools in TOOL_CATEGORIES.items():
                submenu = rumps.MenuItem(category)
                for tool_name in tools:
                    item = rumps.MenuItem(tool_name, callback=self._toggle_tool)
                    item.state = 1 if tool_name in enabled else 0
                    submenu.add(item)
                self.menu.add(submenu)

            self.menu.add(None)
            self.menu.add(rumps.MenuItem("Enable All", callback=self._enable_all))
            self.menu.add(rumps.MenuItem("Disable All", callback=self._disable_all))
            self.menu.add(None)
            self.menu.add(rumps.MenuItem("Reconfigure...", callback=self._reconfigure))
        else:
            self.menu = [
                rumps.MenuItem("Status: Not configured", callback=None),
                None,
                rumps.MenuItem("Set Up...", callback=self._run_setup),
                None,
            ]

    def _toggle_tool(self, sender):
        tool_name = sender.title
        currently_enabled = sender.state == 1
        config.set_tool_enabled(tool_name, not currently_enabled)
        sender.state = 0 if currently_enabled else 1
        self._update_tool_count()

    def _enable_all(self, _):
        for tools in TOOL_CATEGORIES.values():
            for t in tools:
                config.set_tool_enabled(t, True)
        self._refresh_checks()

    def _disable_all(self, _):
        for tools in TOOL_CATEGORIES.values():
            for t in tools:
                config.set_tool_enabled(t, False)
        self._refresh_checks()

    def _refresh_checks(self):
        enabled = config.get_enabled_tools()
        for category in TOOL_CATEGORIES:
            if category in self.menu:
                for tool_name in TOOL_CATEGORIES[category]:
                    if tool_name in self.menu[category]:
                        self.menu[category][tool_name].state = (
                            1 if tool_name in enabled else 0
                        )
        self._update_tool_count()

    def _update_tool_count(self):
        enabled = config.get_enabled_tools()
        total = len(config.load().get("tools", {}))
        for key in self.menu.keys():
            if "Tools:" in str(key):
                self.menu[key].title = f"Tools: {len(enabled)}/{total} enabled"
                break

    def _update_status(self, status: str):
        for key in self.menu.keys():
            if "Status:" in str(key):
                self.menu[key].title = f"Status: {status}"
                break

    def _run_setup(self, _=None):
        if run_setup():
            self._build_menu()
            self._start_bot()

    def _reconfigure(self, _):
        config.set("setup_complete", False)
        self._run_setup()

    # --------------- Telegram Bot ---------------

    def _start_bot(self):
        if self.bot_running:
            return

        token = config.get("telegram_bot_token", "")
        if not token:
            self._update_status("No bot token")
            return

        # Set env vars for the agent to use
        proxy_url = config.get("proxy_url", "")
        if proxy_url:
            os.environ["PROXY_URL"] = proxy_url
            os.environ["DEVICE_ID"] = config.get("device_id", "")
        os.environ["OPENAI_API_KEY"] = config.get("openai_api_key", "")
        os.environ["OPENROUTER_API_KEY"] = config.get("openrouter_api_key", "")
        os.environ["LLM_MODEL"] = config.get("llm_model", "gpt-4o-mini")

        def run():
            self.bot_running = True
            try:
                from bot.telegram import create_bot
                app = create_bot(token)
                print("[bot] Starting Telegram bot...")
                self._update_status("Connected")
                app.run_polling()
            except Exception as e:
                print(f"[bot] Error: {e}")
                self._update_status(f"Error: {e}")
            finally:
                self.bot_running = False

        self.bot_thread = threading.Thread(target=run, daemon=True)
        self.bot_thread.start()

    @rumps.clicked("Quit Protagonist")
    def quit_app(self, _):
        rumps.quit_application()


# --------------- Auto-Update ---------------

def _check_for_updates():
    """Check GitHub Releases for a newer version (runs in background)."""
    try:
        from app.config import APP_VERSION, GITHUB_REPO

        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github.v3+json"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode())

        latest_tag = data.get("tag_name", "")
        # Strip leading 'v' for comparison
        latest_ver = latest_tag.lstrip("v")
        if not latest_ver or latest_ver == APP_VERSION:
            return

        # Simple version comparison (works for semver)
        from packaging.version import Version
        try:
            if Version(latest_ver) <= Version(APP_VERSION):
                return
        except Exception:
            # If packaging not available, do string comparison
            if latest_ver <= APP_VERSION:
                return

        download_url = data.get("html_url", "")
        print(f"[update] New version available: {latest_ver} (current: {APP_VERSION})")

        # Show update dialog on main thread
        def _notify(_):
            resp = rumps.alert(
                title="Update Available",
                message=f"Protagonist {latest_ver} is available (you have {APP_VERSION}).\n\nWould you like to download it?",
                ok="Download",
                cancel="Later",
            )
            if resp == 1 and download_url:
                webbrowser.open(download_url)

        rumps.Timer(_notify, 2).start()

    except Exception as e:
        print(f"[update] Check failed: {e}")


# --------------- Entry Point ---------------

def main():
    print("[protagonist] Starting...")

    cfg = config.load()
    print(f"[protagonist] Device: {cfg.get('device_id', 'unknown')[:8]}...")
    print(f"[protagonist] Setup complete: {config.is_setup_complete()}")

    # Check for updates in background
    threading.Thread(target=_check_for_updates, daemon=True).start()

    app = ProtagonistApp()

    # Auto-start bot if already configured
    if config.is_setup_complete():
        app._start_bot()
    else:
        # Show setup wizard on first launch (with slight delay)
        rumps.Timer(lambda _: app._run_setup(), 1).start()

    app.run()


if __name__ == "__main__":
    main()
