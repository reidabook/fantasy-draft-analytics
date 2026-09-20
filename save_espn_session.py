#!/usr/bin/env python3
"""
save_espn_session.py — One-time (or periodic) interactive ESPN login for
weekly_update.py's Playwright automation.

Cookie-only auth (espn_s2/SWID) is enough for the read-only ESPN API
(src/data/fetcher.py), but not for driving the actual ESPN *website's*
commissioner "Adjust Scoring" tool — that needs a fully-established login
session, which only comes from actually logging in through the browser.

Run this whenever weekly_update.py's override step reports a login
redirect (session expired). It opens a real browser, you log in by hand,
and it saves the resulting session (all cookies + storage) to
ESPN_PLAYWRIGHT_STATE_PATH (default: .espn_session.json, gitignored) for
weekly_update.py to reuse non-interactively.

Usage:
    python save_espn_session.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

load_dotenv()

STATE_PATH = os.getenv("ESPN_PLAYWRIGHT_STATE_PATH", ".espn_session.json")


def main() -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://fantasy.espn.com/football/")
        print("A browser window has opened. Log into ESPN there.")
        input("Press Enter here once you're logged in and see your fantasy home page... ")
        context.storage_state(path=STATE_PATH)
        browser.close()

    os.chmod(STATE_PATH, 0o600)
    print(f"Saved session to {STATE_PATH} (gitignored — contains live login credentials).")


if __name__ == "__main__":
    main()
