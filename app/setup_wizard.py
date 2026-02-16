"""First-launch setup wizard using rumps dialogs."""
from __future__ import annotations

import webbrowser
import urllib.request
import json
import rumps

from app import config

BOTFATHER_URL = "https://t.me/BotFather"


def _register_device(device_id: str, proxy_url: str):
    """Register device with the proxy server (best-effort)."""
    if not proxy_url:
        return
    try:
        # Strip /v1 suffix to get base, then add /v1/register
        base = proxy_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        url = f"{base}/v1/register"

        data = json.dumps({"device_id": device_id}).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # Best-effort — proxy may not be up yet


def run_setup() -> bool:
    """Run the setup wizard. Returns True if setup completed successfully."""

    # Step 1: Welcome
    resp = rumps.alert(
        title="Welcome to Protagonist",
        message=(
            "Let's set up your personal AI friend in Telegram.\n\n"
            "You'll need to:\n"
            "1. Create a Telegram bot (takes 1 minute)\n"
            "2. Paste the bot token here\n\n"
            "Ready?"
        ),
        ok="Let's go",
        cancel="Later",
    )
    if resp != 1:
        return False

    # Step 2: Open BotFather and get token
    webbrowser.open(BOTFATHER_URL)
    resp = rumps.alert(
        title="Create Your Bot",
        message=(
            "I've opened BotFather in Telegram.\n\n"
            "1. Send /newbot\n"
            "2. Pick a name (e.g. 'My AI Friend')\n"
            "3. Pick a username (e.g. 'myaifriend_bot')\n"
            "4. Copy the token BotFather gives you\n\n"
            "Click 'Paste Token' when ready."
        ),
        ok="Paste Token",
        cancel="Cancel",
    )
    if resp != 1:
        return False

    # Step 3: Get the token
    win = rumps.Window(
        title="Paste Bot Token",
        message="Paste the token from BotFather:",
        default_text="",
        ok="Verify",
        cancel="Cancel",
        dimensions=(400, 24),
    )
    response = win.run()
    if not response.clicked:
        return False

    token = response.text.strip()
    if not token or ":" not in token:
        rumps.alert(
            title="Invalid Token",
            message="That doesn't look like a valid bot token.\nIt should look like: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz",
            ok="OK",
        )
        return False

    # Step 4: Register device with proxy
    device_id = config.get("device_id", "")
    if device_id:
        _register_device(device_id, config.get("proxy_url", ""))

    # Step 5: Save config
    config.set("telegram_bot_token", token)
    config.set("setup_complete", True)
    config.save()

    rumps.alert(
        title="All Set!",
        message=(
            "Your AI friend is ready.\n\n"
            "Go to Telegram and find your bot.\n"
            "Send it a message to start chatting!"
        ),
        ok="Done",
    )
    return True
