#!/usr/bin/env python3
"""
list_imessage_chats.py — One-time helper to find your league group chat's id
for weekly_update.py's text-message notification (src/weekly/imessage.py).

macOS only. Lists every chat in Messages.app with its id, display name (if
set), and participant handles, so you can identify your league's group chat
and copy its id into IMESSAGE_GROUP_CHAT_ID in .env.

Usage:
    python list_imessage_chats.py
"""
from __future__ import annotations

import subprocess

SCRIPT = '''
tell application "Messages"
    set output to ""
    repeat with c in chats
        set chatId to id of c
        set chatName to ""
        try
            set chatName to name of c
        end try
        set participantList to ""
        try
            repeat with p in participants of c
                set participantList to participantList & (handle of p) & ", "
            end repeat
        end try
        set output to output & chatId & " | name=" & chatName & " | participants=" & participantList & linefeed
    end repeat
    return output
end tell
'''


def main() -> None:
    result = subprocess.run(["osascript", "-e", SCRIPT], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Failed to list chats: {result.stderr.strip()}")
        print("Make sure Messages.app has been opened at least once and you've granted")
        print("Terminal/this app permission to control it (System Settings > Privacy & Security > Automation).")
        return
    print(result.stdout)
    print("Find your league's group chat above, then copy its id (before ' | name=')")
    print("into IMESSAGE_GROUP_CHAT_ID in .env")


if __name__ == "__main__":
    main()
