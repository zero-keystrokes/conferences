#!/usr/bin/env bash
# Nightly rebuild + publish for the Streaming & Data Events page.
# Invoked by the Hermes cron job; safe to run by hand.
set -uo pipefail

REPO="$HOME/.hermes/workspace/conferences"
LOG_DIR="$HOME/.hermes/logs"
LOG="$LOG_DIR/conferences-nightly.log"
PY="${PYTHON:-/usr/local/bin/python3}"

mkdir -p "$LOG_DIR"
cd "$REPO" || exit 1

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') nightly refresh ==="
  "$PY" generator/build.py --publish
  status=$?
  echo "exit=$status"
} >>"$LOG" 2>&1

# keep the log from growing without bound
if [ -f "$LOG" ] && [ "$(wc -l <"$LOG")" -gt 4000 ]; then
  tail -n 1500 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

exit 0
