#!/usr/bin/env python3
"""
send_group_text.py — Send the group texts that weekly_update.py staged for
approval to the league's iMessage group chat, as two separate messages:

  1. logs/pending_group_text.txt  — the weekly recap
  2. logs/pending_group_link.txt  — the league site link, on its own

weekly_update.py never sends the group text itself — it only builds and
saves it, so you (or whoever's reviewing it, e.g. via the /weekly-update
Claude Code command) can read it first and decide whether it's fine to post
to everyone. Run this only after approving that text.

Each file is sent verbatim and deleted once it's sent, so a re-run after a
failure only sends what hasn't gone out yet. A missing file is skipped.

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
PENDING_GROUP_LINK_PATH = "logs/pending_group_link.txt"


def main() -> None:
    paths = [p for p in (PENDING_GROUP_TEXT_PATH, PENDING_GROUP_LINK_PATH) if os.path.exists(p)]
    if not paths:
        print(f"No pending group text at {PENDING_GROUP_TEXT_PATH} or {PENDING_GROUP_LINK_PATH} — run weekly_update.py first.")
        sys.exit(1)

    chat_id = os.environ["IMESSAGE_GROUP_CHAT_ID"]
    for path in paths:
        with open(path) as f:
            text = f.read()
        print("Sending:")
        print("-" * 60)
        print(text)
        print("-" * 60)
        send_group_message(chat_id, text)
        print("Sent.")
        os.remove(path)


if __name__ == "__main__":
    main()
