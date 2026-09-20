"""
Playwright automation that drives the ESPN commissioner "Adjust Scoring"
tool to set the Fake team's score for a given week's matchup.

Auth note: cookie-only auth (espn_s2/SWID, used by the read-only ESPN API in
src/data/fetcher.py) is NOT enough to reach this — ESPN's website UI needs a
fully-established login session. This loads a saved browser session from
ESPN_PLAYWRIGHT_STATE_PATH (see save_espn_session.py for a one-time manual
login) and, if that's missing or has expired, automatically logs back in
using ESPN_USERNAME/ESPN_PASSWORD from .env (Disney OneID's iframe login
form) and saves the refreshed session for next time — so a cron job stays
unattended even after the session eventually expires.

Recorded by inspecting the real live league's DOM (see docs/data/fetchers.md).
Key findings baked in below:

- Direct URL to a given week's scoreboard page (no need to click through
  "LM Tools" → "Adjust Scoring" → week dropdown each time):
      https://fantasy.espn.com/football/league/scoreboard?leagueId={league_id}&matchupPeriodId={week}
- ESPN's field is an ADJUSTMENT added on top of the team's already-computed
  score, not an absolute value (e.g. team already at 95, want 110 final →
  type "15", no leading "+" — the numeric input rejects one).
  override_fake_team_score() takes absolute current/target scores and does
  this subtraction itself.
- Each matchup renders as a `div.matchup-score` containing both teams' info
  (each team as an `<a href=".../team?...&teamId=N...">`) and that same
  matchup's own "Adjust Scoring" toggle (`a.adjust_scoring_link`) — so the
  Fake team's matchup can be found directly by filtering for the container
  whose href contains its team id, with no need to iterate/guess across
  matchups or rely on visible team-name text (which includes a changing
  record/rank suffix).
- Clicking the toggle reveals `input.ScoreCell__Score__Input[data-team="N"]`
  — the actual adjustment amount field. There's a same-looking but DISABLED
  "leave a note" reason textarea nearby (id="adjustment_reason_<home|away>")
  which is NOT the field we want.
"""
from __future__ import annotations

import os
from typing import Callable, Optional


class NoSavedSessionError(RuntimeError):
    """Raised when there's no usable ESPN session and no ESPN_USERNAME/ESPN_PASSWORD to auto-relogin with."""


class NotConfiguredError(RuntimeError):
    """Raised when the Fake team's matchup/adjustment field can't be found on the scoreboard page."""


class OverrideVerificationError(RuntimeError):
    """Raised when an override was submitted but the re-fetched score doesn't match."""


SCORE_OVERRIDE_URL = (
    "https://fantasy.espn.com/football/league/scoreboard"
    "?leagueId={league_id}&matchupPeriodId={week}"
)


def _is_login_page(page) -> bool:
    # The login form is usually an inline iframe embedded on the SAME url
    # (not a redirect), so the URL check alone misses it — only kept as a
    # fallback in case a fully-expired session does redirect outright. The
    # iframe itself is present in the DOM even when already authenticated
    # (just hidden), so visibility — not mere presence — is what matters.
    if "oneid" in page.url.lower() or "registerdisney" in page.url.lower():
        return True
    login_iframe = page.locator('iframe[name="oneid-iframe"]')
    return login_iframe.count() > 0 and login_iframe.first.is_visible()


def _login_and_save_session(context, page, state_path: str) -> None:
    """Log in through ESPN's Disney OneID iframe using stored credentials, then save the session."""
    username = os.environ["ESPN_USERNAME"]
    password = os.environ["ESPN_PASSWORD"]

    frame = page.locator('iframe[name="oneid-iframe"]').content_frame
    frame.get_by_test_id("InputIdentityFlowValue").click()
    frame.get_by_test_id("InputIdentityFlowValue").fill(username)
    frame.get_by_test_id("BtnSubmit").click()
    frame.get_by_test_id("InputPassword").click()
    frame.get_by_test_id("InputPassword").fill(password)
    frame.get_by_test_id("BtnSubmit").click()
    page.wait_for_load_state("domcontentloaded")

    context.storage_state(path=state_path)
    os.chmod(state_path, 0o600)


def override_fake_team_score(
    league_id: int,
    season: int,
    fake_team_name: str,
    fake_team_id: int,
    current_score: float,
    target_score: float,
    week: int,
    dry_run: bool = False,
    verify_fn: Optional[Callable[[], float]] = None,
) -> bool:
    """
    Using a saved ESPN browser session (see save_espn_session.py), set the
    Fake team's score for `week` to `target_score` via the commissioner
    "Adjust Scoring" tool.

    ESPN's adjustment field is added on top of the team's already-computed
    score, not an absolute value — what actually gets typed in is
    `target_score - current_score` (e.g. median 110, fake team already at
    95 → type 15 to land on 110). Callers only need to think in absolute
    scores; this function does the subtraction.

    dry_run=True fills the adjustment field but never clicks submit — safe
    to run against the real league to sanity-check the flow before trusting
    it unattended.

    verify_fn, if given, is called after a real (non-dry-run) submit and
    should return the freshly re-fetched score for the fake team; raises
    OverrideVerificationError if it doesn't match target_score, so a bad
    write is never reported as a silent success.

    Returns True on a verified (or dry-run) success.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError(
            "playwright not installed. Run: pip install playwright && playwright install chromium"
        )

    adjustment = round(target_score - current_score, 2)
    headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() != "false"

    state_path = os.getenv("ESPN_PLAYWRIGHT_STATE_PATH", ".espn_session.json")
    can_auto_relogin = bool(os.getenv("ESPN_USERNAME")) and bool(os.getenv("ESPN_PASSWORD"))
    if not os.path.exists(state_path) and not can_auto_relogin:
        raise NoSavedSessionError(
            f"No saved ESPN browser session at {state_path!r}, and ESPN_USERNAME/"
            f"ESPN_PASSWORD aren't set in .env to auto-relogin. Either run `python "
            f"save_espn_session.py` once to log in manually, or set those two "
            f"variables so this can log back in on its own."
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = (
            browser.new_context(storage_state=state_path)
            if os.path.exists(state_path)
            else browser.new_context()
        )
        page = context.new_page()
        try:
            page.goto(SCORE_OVERRIDE_URL.format(league_id=league_id, season=season, week=week))
            page.wait_for_timeout(1000)  # give an inline login iframe time to mount, if present

            if _is_login_page(page):
                if not can_auto_relogin:
                    raise NoSavedSessionError(
                        f"ESPN redirected to a login page — the saved session at "
                        f"{state_path!r} has expired, and ESPN_USERNAME/ESPN_PASSWORD "
                        f"aren't set in .env to auto-relogin. Run `python "
                        f"save_espn_session.py` again, or set those two variables."
                    )
                _login_and_save_session(context, page, state_path)
                page.goto(SCORE_OVERRIDE_URL.format(league_id=league_id, season=season, week=week))
                if _is_login_page(page):
                    raise NoSavedSessionError(
                        "Logged in with ESPN_USERNAME/ESPN_PASSWORD but still landed "
                        "on a login page — check those credentials in .env."
                    )

            page.locator("div.matchup-score").first.wait_for(state="visible", timeout=20000)

            matchup = page.locator("div.matchup-score").filter(
                has=page.locator(f'a[href*="teamId={fake_team_id}"]')
            )
            if matchup.count() == 0:
                debug_dir = os.getenv("PLAYWRIGHT_DEBUG_DIR", "logs")
                os.makedirs(debug_dir, exist_ok=True)
                screenshot_path = os.path.join(debug_dir, f"week{week}_matchup_not_found.png")
                page.screenshot(path=screenshot_path, full_page=True)
                raise NotConfiguredError(
                    f"Could not find a matchup containing teamId={fake_team_id} "
                    f"({fake_team_name!r}) on the week {week} scoreboard. Landed on: "
                    f"{page.url!r}, page title: {page.title()!r}. Screenshot saved to "
                    f"{screenshot_path}. Confirm FAKE_TEAM_ID is correct, or ESPN's page "
                    f"structure may have changed (see module docstring)."
                )

            matchup.first.locator("a.adjust_scoring_link").click()

            field = page.locator(f'input.ScoreCell__Score__Input[data-team="{fake_team_id}"]')
            field.first.wait_for(state="visible", timeout=10000)

            field.first.click()
            field.first.fill(f"{adjustment:.2f}")

            if dry_run:
                if not headless:
                    input(
                        f"[dry-run] Filled the adjustment field with {adjustment:.2f} "
                        f"for {fake_team_name!r} — check the browser window, then press "
                        f"Enter here to close it... "
                    )
                return True

            matchup.first.get_by_role("button", name="Submit").click()

            if not headless:
                input(
                    f"Submitted adjustment {adjustment:.2f} for {fake_team_name!r} — "
                    f"check the browser to confirm it actually applied, then press "
                    f"Enter here to continue (this will re-fetch and verify)... "
                )

            if verify_fn is not None:
                page.wait_for_timeout(2000)  # give ESPN's backend a moment to recompute
                actual = verify_fn()
                if round(actual, 2) != round(target_score, 2):
                    raise OverrideVerificationError(
                        f"Submitted adjustment {adjustment:.2f} for {fake_team_name!r} "
                        f"(expected final {target_score}), but re-fetched score is "
                        f"{actual} — not verified."
                    )
            return True
        finally:
            browser.close()
