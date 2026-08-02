#!/bin/zsh
# Mirai price test — scheduled data collection.
# Refreshes the readout + tracker so the experiment is always up to date
# without anyone running anything by hand.
#
# Note: no data can be LOST if a run is missed — Shopify order history and
# Search Console are both queryable retroactively. This job keeps the tracker
# fresh; it is not a sampling process.

set -u
cd "$(dirname "$0")" || exit 1

START="2026-07-28"          # day the prices changed
LOG="outputs/collect.log"
mkdir -p outputs

# whole weeks elapsed since the test started, floor 1
ELAPSED=$(python3 -c "
import datetime
d=(datetime.date.today()-datetime.date.fromisoformat('$START')).days
print(max(1, d//7))")

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S')  week ${ELAPSED}"
  python3 organic_test_readout.py --start "$START" --weeks "$ELAPSED" 2>&1
  python3 delivery_exposure.py 2>&1 | tail -8
  python3 test_channel_report.py 2>&1 | tail -4
  python3 google_ads_efficiency.py 2>&1 | tail -5
  python3 build_tracker.py 2>&1 | tail -2
  echo
} >> "$LOG" 2>&1

# keep the log from growing without bound
tail -n 2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
