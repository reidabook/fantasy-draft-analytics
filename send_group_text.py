#!/usr/bin/env python3
"""
send_group_text.py — Send the group text that weekly_update.py staged for
approval (logs/pending_group_text.txt) to the league's iMessage group chat.

weekly_update.py never sends the group text itself — it only builds and
saves it, so you (or whoever's reviewing it, e.g. via the /weekly-update
Claude Code command) can read it first and decide whether it's fine to post
to everyone. Run this only after approving that text.

Usage:
    python send_group_text.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

from src.weekly.imessage import send_group_message

PENDING_GROUP_TEXT_PATH = "logs/pending_group_text.txt"


def main() -> None:
    if not os.path.exists(PENDING_GROUP_TEXT_PATH):
        print(f"No pending group text at {PENDING_GROUP_TEXT_PATH} — run weekly_update.py first.")
        sys.exit(1)

    with open(PENDING_GROUP_TEXT_PATH) as f:
        text = f.read()

    chat_id = os.environ["IMESSAGE_GROUP_CHAT_ID"]
    print("Sending:")
    print("-" * 60)
    print(text)
    print("-" * 60)
    send_group_message(chat_id, text)
    print("Sent.")

    os.remove(PENDING_GROUP_TEXT_PATH)


if __name__ == "__main__":
    main()
