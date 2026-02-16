"""py2app build script for Protagonist."""
from setuptools import setup

APP = ["app/main.py"]
APP_NAME = "Protagonist"

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": "com.protagonist.app",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSUIElement": True,  # Menu bar app — no dock icon
        "NSAppleEventsUsageDescription": "Protagonist needs AppleScript access to control apps on your behalf.",
        "NSCalendarsUsageDescription": "Protagonist needs calendar access to read your events.",
        "NSRemindersUsageDescription": "Protagonist needs reminders access to create reminders for you.",
    },
    "packages": ["openai", "telegram", "httpcore", "httpx", "anyio", "certifi"],
    "includes": [
        "app", "app.config", "app.setup_wizard",
        "bot", "bot.telegram",
        "core", "core.agent", "core.state",
        "menubar", "menubar.tools",
    ],
    "excludes": [
        "backend", "frontend", "imessage",
        "matplotlib", "numpy", "scipy", "pandas",
        "tkinter", "test", "unittest",
    ],
}

setup(
    name=APP_NAME,
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
