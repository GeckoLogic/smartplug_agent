#!/usr/bin/env bash
# setup_systemd.sh
# Installs the Smart Plug Agent as a systemd timer (Linux).
# Reads interval_minutes from config.yaml and applies it automatically.
# Re-run any time you change interval_minutes in config.yaml.
#
# Usage:
#   bash setup_systemd.sh

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

CURRENT_USER=$(id -un)

echo "Installing SmartPlugAgent systemd timer (every ${INTERVAL} minute(s), running as ${CURRENT_USER}) ..."

# ── Write service file ─────────────────────────────────────────────────────────

cat > /tmp/smartplug_agent.service << EOF
[Unit]
Description=Smart Plug Monitoring Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${CURRENT_USER}
WorkingDirectory=${SCRIPT_DIR}
ExecStart=${PYTHON} ${SCRIPT_DIR}/agent.py --config ${SCRIPT_DIR}/config.yaml --state ${SCRIPT_DIR}/state.json
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# ── Write timer file ───────────────────────────────────────────────────────────

cat > /tmp/smartplug_agent.timer << EOF
[Unit]
Description=Run Smart Plug Monitoring Agent every ${INTERVAL} minute(s)
Requires=smartplug_agent.service

[Timer]
OnBootSec=1min
OnUnitActiveSec=${INTERVAL}min
Persistent=true

[Install]
WantedBy=timers.target
EOF

# ── Install and start ──────────────────────────────────────────────────────────

sudo cp /tmp/smartplug_agent.service /tmp/smartplug_agent.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smartplug_agent.timer

echo ""
echo "Installed — runs every ${INTERVAL} minute(s)."
echo ""
echo "Useful commands:"
echo "  Run now:      sudo systemctl start smartplug_agent.service"
echo "  View logs:    journalctl -u smartplug_agent -f"
echo "  Timer status: systemctl status smartplug_agent.timer"
echo "  Remove:       sudo systemctl disable --now smartplug_agent.timer && sudo rm /etc/systemd/system/smartplug_agent.*"
