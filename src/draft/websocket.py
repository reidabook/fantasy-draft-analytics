"""
Sleeper WebSocket live draft sync.
Connects to Sleeper's draft WebSocket and marks picks automatically.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Callable, Optional

SLEEPER_WS_BASE = "wss://live.sleeper.app/ws/nfl/draft"


class SleeperDraftSync:
    """
    WebSocket client for live Sleeper draft sync.
    Runs in a background thread so it doesn't block Streamlit.
    """

    def __init__(
        self,
        draft_id: str,
        on_pick: Callable[[dict], None],
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.draft_id = draft_id
        self.on_pick = on_pick
        self.on_error = on_error
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.connected = False

    def start(self) -> None:
        """Start background WebSocket thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the background thread to stop."""
        self._stop.set()
        self.connected = False

    def _run(self) -> None:
        """Background thread: connect and process messages with auto-reconnect."""
        import time
        backoff = 1
        while not self._stop.is_set():
            try:
                asyncio.run(self._connect())
                backoff = 1  # reset on successful connection
            except Exception as e:
                if self._stop.is_set():
                    break
                if self.on_error:
                    self.on_error(f"WS error: {e}. Reconnecting in {backoff}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _connect(self) -> None:
        try:
            import websockets
        except ImportError:
            raise ImportError("websockets package not installed. Run: pip install websockets")

        url = f"{SLEEPER_WS_BASE}/{self.draft_id}"
        async with websockets.connect(url, ping_interval=30) as ws:
            self.connected = True
            async for message in ws:
                if self._stop.is_set():
                    break
                try:
                    data = json.loads(message)
                    if isinstance(data, dict) and data.get("type") == "picked":
                        self.on_pick(data.get("payload", {}))
                except (json.JSONDecodeError, KeyError):
                    pass
        self.connected = False


def parse_sleeper_pick(payload: dict) -> dict:
    """
    Convert a Sleeper WebSocket pick payload to our internal format.
    Returns a dict suitable for DraftBoard.mark_pick().
    """
    return {
        "player_id": str(payload.get("player_id", "")),
        "pick_number": payload.get("pick_no", 0),
        "round_number": payload.get("round", 0),
        "pick_in_round": payload.get("draft_slot", 0),
        "team_number": payload.get("roster_id", 0),
    }
