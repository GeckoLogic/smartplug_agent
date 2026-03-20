#!/usr/bin/env bash
# setup_cron.sh
# Installs the Smart Plug Agent as a cron job (macOS, or any Linux without systemd).
# Reads interval_minutes from config.yaml and applies it automatically.
# Re-run any time you change interval_minutes in config.yaml.
#
# Note: cron intervals must divide evenly into 60 for predictable timing.
# Common values: 10, 15, 20, 30, 60.
#
# Usage:
#   bash setup_cron.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${SCRIPT_DIR}/venv/bin/python3"

# ── Prerequisite checks ────────────────────────────────────────────────────────

if [[ ! -f "$PYTHON" ]]; then
    echo "Error: venv not found. Run:"
    echo "  python3 -m venv venv"
    echo "  venv/bin/pip install -r requirements.txt"
    exit 1
fi

if [[ ! -f "${SCRIPT_DIR}/config.yaml" ]]; then
    echo "Error: config.yaml not found."
    echo "  cp config.yaml.example config.yaml"
    exit 1
fi

# ── Read interval from config.yaml ────────────────────────────────────────────

INTERVAL=$("$PYTHON" -c "
import yaml
d = yaml.safe_load(open('${SCRIPT_DIR}/config.yaml'))
print(max(1, int(d.get('interval_minutes', 30))))
")

# ── Build and install cron entry ───────────────────────────────────────────────

CRON_MARKER="# SmartPlugAgent"
CRON_ENTRY="*/${INTERVAL} * * * * cd \"${SCRIPT_DIR}\" && \"${PYTHON}\" agent.py >> \"${SCRIPT_DIR}/run.log\" 2>&1 ${CRON_MARKER}"

# Remove any existing SmartPlugAgent entry, then append the new one
(crontab -l 2>/dev/null | grep -v "${CRON_MARKER}"; echo "${CRON_ENTRY}") | crontab -

echo ""
echo "Installed SmartPlugAgent cron job — runs every ${INTERVAL} minute(s)."
echo ""
echo "Useful commands:"
echo "  View crontab: crontab -l"
echo "  View logs:    tail -f \"${SCRIPT_DIR}/run.log\""
echo "  Remove:       crontab -l | grep -v '${CRON_MARKER}' | crontab -"
