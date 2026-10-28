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
   payout winner) with the prefilled Venmo pay link the script printed, if any. Don't just paste raw script output — summarize it.
4. weekly_update.py never sends the league group texts itself — it stages a
   plain recap draft at logs/pending_group_text.txt and the site link at
   logs/pending_group_link.txt, and prints both (unless `--dry-run` was
   passed, which skips them entirely). Don't send the recap draft as-is.
   Use it only for the week's numbers, and write a new group text:
   - **Text 1 — narrative recap.** Read the published league site (the local
     render at `../ticerado-bowl/index.html`, especially its "Last Week" and
     "This week" sections) and write a short story of the week, not a list of
     stats. Lead with the high scorer (they get the $5 payout), then the
     week's best storylines: heartbreak losses, close games, wins scored under
     the median, luck ratings, how FAKE TEAM's median did, and a teaser for
     next week's biggest matchup. The whole league reads it, so keep the
     teasing friendly. Every number and claim must come from the site or the
     script output. Point out any claim you inferred instead of reading
     directly (e.g. a record going into the week).
   - **Text 2 — the site link alone**, already staged in
     logs/pending_group_link.txt. Leave it as is.
   Show the user both texts verbatim and ask them to approve before anything
   goes out to the whole group.
5. Only if the user approves, write Text 1 to logs/pending_group_text.txt,
   then run:
   ```
   .venv/bin/python send_group_text.py
   ```
   It sends the recap, then the link, as two separate messages, and deletes
   each file once it's sent. If they want changes instead, do NOT send. Ask
   what to change, revise, and show both texts again.
