"""
Send the weekly report as a text into an existing iMessage group chat, via
AppleScript driving Messages.app. macOS only, no external service/account
needed — the tradeoff is it only works while running on this Mac with
Messages.app signed in.

Find your group chat's id with list_imessage_chats.py (run once), then set
IMESSAGE_GROUP_CHAT_ID in .env.
"""
from __future__ import annotations

import subprocess
from typing import Optional


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _as_applescript_string(text: str) -> str:
    """
    Build an AppleScript string expression that preserves newlines.
    A raw newline embedded inside a quoted literal is unreliable to pass
    through osascript -e, so each line is quoted separately and rejoined
    with AppleScript's `return` (carriage return) constant.
    """
    lines = text.split("\n")
    return " & return & ".join(f'"{_escape(line)}"' for line in lines)


def send_group_message(chat_id: str, text: str) -> None:
    """Send `text` (newlines preserved) to the Messages.app chat identified by `chat_id`."""
    script = (
        f"tell application \"Messages\" to send ({_as_applescript_string(text)}) "
        f'to chat id "{_escape(chat_id)}"'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to send iMessage: {result.stderr.strip()}")


def send_direct_message(handle: str, text: str) -> None:
    """Send `text` directly to a phone number/email (not an existing group
    chat) — used for testing message content without posting to the league."""
    script = (
        'tell application "Messages"\n'
        "    set targetService to 1st service whose service type = iMessage\n"
        f"    send ({_as_applescript_string(text)}) to buddy \"{_escape(handle)}\" of targetService\n"
        "end tell"
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to send iMessage: {result.stderr.strip()}")


def build_group_text(
    week: int,
    median: float,
    fake_team_name: str,
    override_ok: bool,
    high_scorer: str,
    high_score: float,
    scores: dict,
    fake_opponent: Optional[str] = None,
    fake_opponent_score: Optional[float] = None,
    team_to_manager: Optional[dict] = None,
) -> str:
    """
    Build the snarky league group-text summary: congratulate the week's high
    scorer, roast whoever played the Fake team if they didn't beat the
    median, and toss in extra flavor when the numbers make it easy.

    Each topic is its own paragraph (blank line between them), except when
    the high scorer and the Fake team's opponent are the same team — then
    it's folded into one paragraph instead of two templated statements about
    the same team back to back.

    `team_to_manager` (team_name -> manager label, from
    espn_get_team_managers) swaps team names for the manager's name in the
    displayed text — team names get renamed week to week, managers don't.
    All name comparisons/lookups below stay keyed by team name; only the
    text that gets rendered is relabeled.
    """
    team_to_manager = team_to_manager or {}
    label = lambda name: team_to_manager.get(name, name)

    blocks = []
    same_team = fake_opponent is not None and fake_opponent == high_scorer

    if same_team:
        blocks.append(
            f"Week {week}: {label(high_scorer)} takes the top score with {high_score:.2f} — and casually "
            f"cleared {fake_team_name}'s median ({median:.2f}) too. Overkill much?"
        )
    else:
        top_block = [f"Week {week}: {label(high_scorer)} takes the top score with {high_score:.2f} — congrats."]
        others = sorted((s for name, s in scores.items() if name != high_scorer), reverse=True)
        if others and high_score - others[0] >= 25:
            top_block.append(f"Nobody else was within {high_score - others[0]:.0f} points. Not exactly a nail-biter.")
        blocks.append("\n".join(top_block))

        if fake_opponent is not None and fake_opponent_score is not None:
            fake_block = []
            if fake_opponent_score <= median:
                margin = median - fake_opponent_score
                fake_block.append(
                    f"{label(fake_opponent)} needed to beat {fake_team_name}'s median ({median:.2f}) and scored "
                    f"{fake_opponent_score:.2f} instead — lost to a team that doesn't exist, by {margin:.2f}."
                )
                if margin >= 20:
                    fake_block.append("That's not a loss, that's a cry for help.")
            else:
                fake_block.append(
                    f"{label(fake_opponent)} cleared {fake_team_name}'s median ({median:.2f}) with "
                    f"{fake_opponent_score:.2f}. No shame there."
                )
            blocks.append("\n".join(fake_block))

    if not override_ok:
        blocks.append(f"(Commissioner note: {fake_team_name}'s score needs a manual fix this week.)")

    return "\n\n".join(blocks)
