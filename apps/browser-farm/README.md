# Browser farm

Persistent Chromium profiles for **platform seats**. Same playbooks as the connector.

Production seats need a **real logged-in Playwright profile** in `apps/browser-farm/profiles/`. Injected payload rows are debug-only. They do not invent wallet money: no `revenue_minor` → no settlement snapshot; DOM scrape confidence stays below 0.9 so auto-confirm keeps the batch in draft.

```
cd backend
python ../apps/browser-farm/worker.py
python ../apps/browser-farm/worker.py --loop --interval 20
```

Celery beat also drains the same queue every minute (`drain_seat_jobs_task`) and enqueues harvest every 6 hours. The farm process is for a host that should keep Playwright profiles warm.

- Platform seats stay `live` after ops log in once.
- User seats wake for `upload` / `harvest` / `relogin`.
- Challenge or expired session marks `needs_challenge` and waits for the creator or ops window.
- Playwright is required for live harvest. Injected rows in job payload are fixtures, not a production money path.
- Navigation is on only when `VIBE_FARM_NAVIGATE=1` **and** Playwright Chromium is in the farm image (`INSTALL_PLAYWRIGHT=true`). `farm_can_navigate()` is the public truth. MFA / login walls mark `needs_challenge` and wait for the extension.
- Harvest waits for playbook `wait_selectors`, clicks export when present, then paginates and merges rows. Zero rows is `selector_broke` (or `needs_challenge` if the session is dead) — never success.
- `remote_login` with `capture_session` reads cookies from this seat's existing Playwright profile and never logs values. It does not fill passwords or solve captchas.

Drain metrics (printed each loop):

- `jobs_ok` / `jobs_fail` — completed vs failed farm jobs
- `rows_ingested` — matched harvest rows this drain
- `seats_needing_challenge` — expired session or challenge
- `handed_to_extension` — farm did not navigate; connector should finish

Per-seat `extra.farm_health` stores the last harvest summary (`rows`, `matched`, `playwright`, `elapsed_ms`, `session_expired`, `selector_broke`).
