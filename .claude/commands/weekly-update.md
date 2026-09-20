---
description: Run the weekly ESPN median-score override + high-score payout report
---

Run the weekly median-score override + payout report for this fantasy league.

1. From the project root, run:
   ```
   .venv/bin/python weekly_update.py $ARGUMENTS
   ```
   (`$ARGUMENTS` is empty by default — defaults to the most recently completed
   week and does a real run. Pass `--week N` to target a specific week, or
   `--dry-run` to fill the ESPN form without submitting or emailing.)
2. If the output says the saved ESPN session expired (`NoSavedSessionError`),
   tell the user to run `.venv/bin/python save_espn_session.py` to log back
   in, then re-run step 1.
3. Report back concisely: the computed median, the Fake team's override
   status (succeeded/failed and why), and the week's high scorer (the Venmo
   payout winner). Don't just paste raw script output — summarize it.
4. weekly_update.py never sends the league group text itself — it stages it
   at logs/pending_group_text.txt and prints it (unless `--dry-run` was
   passed, which skips it entirely). If a group text was staged, show the
   user its exact contents verbatim and ask them to approve it before it
   goes out to the whole group.
5. Only if the user approves it, run:
   ```
   .venv/bin/python send_group_text.py
   ```
   to actually send it. If they want changes instead, do NOT send — ask what
   to change, and note that re-running weekly_update.py will regenerate
   logs/pending_group_text.txt (editing it by hand also works, since
   send_group_text.py just sends whatever's in that file verbatim).
