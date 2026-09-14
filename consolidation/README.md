# Mirai service consolidation

Status: prepared, not deployed. Target is the existing management service; its
URLs, Postgres connection, disk, frontend, and dashboard API stay in place.
The old reports service remains available for rollback until validation passes.

## Layout

- Existing Node frontend/gateway and Python dashboard API remain unchanged.
- Standalone reports source is pinned in `automation_reports/` to upstream
  `34826fbc1e385ba69c41358ec558b7eaad52d92f`.
- A separate virtual environment preserves the reports production dependencies.
- The report API listens only on localhost:8081. Its existing paths are available
  under `/automation-reports` when `REPORTS_ENABLED=1`. `/reports-api` retains the
  management application's current behavior.
- `consolidation/supervisor.py` launches the existing dashboard script and optional
  report API/30-minute master loop. Reports process failures restart separately.
- Source `start.sh` launched a master loop AND the API's summary/order background
  jobs. Preserve all three, but never launch a second standalone order monitor.
- Google Ads query transports now close after their paginated results are read,
  including failure and early-return paths. This addresses an observed resource
  lifetime issue; production memory growth still requires measurement.

## Required configuration (secrets are never committed)

`REPORTS_ENABLED=0` by default; no new routes or report jobs run.
`REPORTS_JOBS_ENABLED=0` by default; enables safe API-only staging.
`REPORTS_ENV_FILE` is a mode-0600 JSON map copied from the live reports service.
Keep its credentials separate from the management process environment.
`REPORTS_DATA_DIR` is a reports subdirectory on the existing management disk.
Point Google OAuth/config and any other absolute file paths from the exported
reports environment at securely copied files on that disk. Copy live versions,
not repository defaults. Preserve timezone, store lists, API versions and IDs.

Build: `./build.sh` (delegates to consolidation build; both Python dependency sets are pinned).
Start: `python3 consolidation/supervisor.py`.

## Cutover gates

1. Verify current source commits and deployment settings; save rollback values.
2. Back up both persistent disks and capture permissions, hashes and environment
   configuration through authenticated SSH. Do not place secrets in Git, public
   URLs, application responses, logs or chat.
3. Copy reports configuration, OAuth files, refreshed shipping matrix/weight
   cache and state to the management disk. Preserve management files untouched.
4. Deploy candidate with reports jobs OFF. Verify login/frontend, management
   report and pricing routes, reports API health and unchanged calculations.
   Read-only comparisons must not invoke summary/backfill/send endpoints.
5. Validate process resource use and supervise failure recovery. Require enough
   headroom for reporting peaks on the shared 2GB instance; do not guess success.
6. Quiesce old report writers; take a final consistent state snapshot; suspend
   the source before enabling destination jobs. Hash-verify all four state files:
   `.monitor_seen_orders.json`, `.orders_state.json`,
   `.telegram_seen_orders.json`, `.telegram_summary_state.json`.
7. `cutover-manifest.json` contains `source_suspended: true` and `sha256` mapping
   for those files. First activation checks hashes; later restarts allow state to
   evolve while still requiring files to be present and valid JSON.
8. Enable destination jobs, verify one sender only and no duplicate alerts,
   observe a scheduled report cycle and memory use. Do not send test messages.
9. Preserve old service/disk for rollback. Suspended disk storage remains a
   possible small retained charge. Remove the temporary SSH key when finished.

The old `mirai-reports.onrender.com` URL stops serving when its service is
suspended. User reports no known external consumers; verify configured consumers
before retiring it. Render-owned onrender.com names cannot simply be attached to
a different service. Management's existing URLs remain unchanged.

## Rollback

Disable destination jobs and wait for in-flight work to finish. Copy the latest
alert state BACK to the old reports disk before resuming it, otherwise orders
handled after cutover may be resent. Restore original management start/build
commands and deployed commit. Never run both sets of report jobs concurrently.

## Local validation

- Frontend `npm ci && npm run build` passes.
- `python3 -m unittest discover -s consolidation -p 'test_*.py'`: 11 tests.
- `node consolidation/test-proxy.mjs`: pass-through semantics, disabled routing,
  dashboard route isolation, and upstream error handling.
- Actual destination Linux/Python 3.12 startup smoke test passes with jobs off.
- Staged historical daily report matches original across all 31 fields (2026-09-01).
- Initial reports config/state is staged in an isolated persistent directory.
- Final state handoff and production job cutover remain pending.
