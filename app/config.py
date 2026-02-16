"""Protagonist configuration management.

Stores all config in ~/.protagonist/config.json.
Replaces .env files — everything in one place.
"""
from __future__ import annotations

import os
import json
import uuid

APP_VERSION = "0.1.0"
PROXY_URL_DEFAULT = "https://proxy.protagonist.app/v1"
GITHUB_REPO = "felixwulei/protagonist"

CONFIG_DIR = os.path.expanduser("~/.protagonist")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DB_PATH = os.path.join(CONFIG_DIR, "protagonist.db")

# Default tool states — all enabled by default
DEFAULT_TOOLS = {
    "read_emails": True,
    "search_emails": True,
    "send_email": True,
    "capture_screen": True,
    "check_wechat": True,
    "run_claude_code": True,
    "find_files": True,
    "read_file": True,
    "open_app": True,
    "quit_app": True,
    "run_command": True,
    "get_calendar_events": True,
    "create_reminder": True,
    "music_play": True,
    "music_pause": True,
    "music_next": True,
    "music_previous": True,
    "music_now_playing": True,
    "music_search_play": True,
    "create_document": True,
}

_config: dict | None = None


def _ensure_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load() -> dict:
    """Load config from disk, or return defaults."""
    global _config
    if _config is not None:
        return _config

    _ensure_dir()
    try:
        with open(CONFIG_PATH, "r") as f:
            _config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _config = {}

    # Fill in defaults
    _config.setdefault("device_id", str(uuid.uuid4()))
    _config.setdefault("telegram_bot_token", "")
    _config.setdefault("proxy_url", PROXY_URL_DEFAULT)
    _config.setdefault("openai_api_key", "")  # Direct OpenAI key (fallback)
    _config.setdefault("openrouter_api_key", "")
    _config.setdefault("llm_model", "gpt-4o-mini")
    _config.setdefault("tools", DEFAULT_TOOLS.copy())
    _config.setdefault("setup_complete", False)

    save()
    return _config


def save():
    """Save config to disk."""
    global _config
    if _config is None:
        return
    _ensure_dir()
    with open(CONFIG_PATH, "w") as f:
        json.dump(_config, f, indent=2, ensure_ascii=False)


def get(key: str, default=None):
    """Get a config value."""
    return load().get(key, default)


def set(key: str, value):
    """Set a config value and save."""
    load()[key] = value
    save()


def is_setup_complete() -> bool:
    """Check if initial setup has been done."""
    cfg = load()
    return bool(cfg.get("setup_complete")) and bool(cfg.get("telegram_bot_token"))


def get_enabled_tools() -> list[str]:
    """Get list of enabled tool names."""
    tools = load().get("tools", {})
    return [name for name, enabled in tools.items() if enabled]


def set_tool_enabled(name: str, enabled: bool):
    """Toggle a specific tool."""
    load().setdefault("tools", {})[name] = enabled
    save()
