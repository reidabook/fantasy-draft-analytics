"""
Weekly report email: median target, Fake team override status, and the
high-score payout winner. Plain smtplib over Gmail SMTP — auth via an app
password (GMAIL_ADDRESS / GMAIL_APP_PASSWORD in .env), not OAuth, so this
runs unattended with no browser/consent step.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from typing import Dict, Optional


def send_weekly_report(
    week: int,
    scores: Dict[str, float],
    median: float,
    fake_team_name: str,
    override_ok: bool,
    high_scorer: str,
    high_score: float,
    error: Optional[str] = None,
) -> None:
    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("NOTIFY_EMAIL") or gmail_address

    if not gmail_address or not gmail_password:
        raise RuntimeError(
            "GMAIL_ADDRESS / GMAIL_APP_PASSWORD not set in .env — see .env.template."
        )

    msg = EmailMessage()
    msg["From"] = gmail_address
    msg["To"] = recipient

    if override_ok:
        msg["Subject"] = f"Week {week}: median {median:.2f}, {high_scorer} wins high score"
        body = [
            f"Week {week} median (excluding {fake_team_name}): {median:.2f}",
            f"{fake_team_name} score overridden to {median:.2f}.",
            "",
            f"High score payout: {high_scorer} with {high_score:.2f} — Venmo them.",
        ]
    else:
        msg["Subject"] = f"Week {week}: median {median:.2f} — ESPN override FAILED, set it manually"
        body = [
            f"Week {week} median (excluding {fake_team_name}): {median:.2f}",
            f"COULD NOT override {fake_team_name}'s score automatically — set it to "
            f"{median:.2f} by hand in ESPN's commissioner tool.",
            f"Error: {error}" if error else "",
            "",
            f"High score payout (unaffected by the override failure): "
            f"{high_scorer} with {high_score:.2f} — Venmo them.",
        ]

    body.append("")
    body.append("All scores this week:")
    for name, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        body.append(f"  {name}: {score:.2f}")

    msg.set_content("\n".join(line for line in body if line is not None))

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.starttls()
        smtp.login(gmail_address, gmail_password)
        smtp.send_message(msg)
