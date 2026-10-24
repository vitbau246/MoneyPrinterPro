"""Thoat 0 neu da cau hinh token bot Telegram (bien moi truong hoac config.toml), nguoc lai 1."""
import os
import sys
import tomllib
from pathlib import Path

config_path = Path(__file__).resolve().parent.parent / "config.toml"
try:
    with open(config_path, "rb") as file:
        telegram = tomllib.load(file).get("telegram", {})
except (OSError, tomllib.TOMLDecodeError):
    telegram = {}

sys.exit(0 if (os.getenv("TELEGRAM_BOT_TOKEN") or telegram.get("bot_token")) else 1)
