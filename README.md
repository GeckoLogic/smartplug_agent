# Smart Plug Monitoring Agent

A lightweight Python agent that monitors Meross smart plugs on a schedule and sends alerts when plugs are unreachable or in the wrong on/off state. All problems detected in a single run are reported in one combined notification.

---

## Problem / Solution

**Problem:** Meross smart plugs occasionally go offline or get switched manually and stay in the wrong state. There is no built-in way to receive alerts or automatically restore a plug to its scheduled state.

**Solution:** A small agent that runs every 30 minutes, checks each plug against its expected schedule, and sends a single alert listing all problems. Alert spam is suppressed with a configurable cooldown window; state is persisted across runs so you only get notified once per incident.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Scheduler (every 30 min)                                │
│                                                         │
│  agent.py ──► config.py      (load & validate YAML)     │
│           ──► scheduler.py   (expected on/off/no_rule)  │
│           ──► meross_client.py ──► Meross Cloud API     │
│           ──► state.py       (alert suppression)        │
│           ──► notifier.py ──► Email (SMTP)              │
│                          └──► Telegram (Bot API)        │
└─────────────────────────────────────────────────────────┘
```

Each run is stateless from the OS's perspective — a `state.json` file carries alert history between invocations so repeated occurrences within a configurable window are suppressed.

### Core logic per plug

```
get_expected_state()
  ├── "no_rule"      → clear prior issues, skip
  ├── get actual state from Meross API
  │     ├── "unreachable" → add to alert list (if outside suppress window)
  │     ├── matches expected → clear prior issues, all good
  │     └── wrong state → optionally auto-correct; add to alert list
  └── send one combined notification if any alerts, then save state.json
```

Exit codes: `0` = all healthy, `1` = issues found, `2` = fatal (bad config or login failure).

---

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Meross API | [`meross_iot`](https://github.com/albertogeniola/MerossIot) 0.4.10.4 |
| Config | PyYAML |
| Telegram notifications | `httpx` (async HTTP) |
| Email notifications | `smtplib` (stdlib, STARTTLS) |
| Scheduling (Windows) | Windows Task Scheduler via `setup_task_scheduler.ps1` |
| Scheduling (Mac/Linux) | systemd/cron or `launchd` |

---

## Project Structure

```
smartplug_agent/
├── agent.py                   # Entry point — CLI, async orchestrator, exit codes
├── config.py                  # YAML loading, dataclasses, validation
├── scheduler.py               # Per-plug expected state (on / off / no_rule)
├── meross_client.py           # Meross Cloud API async wrapper + MockMerossClient
├── notifier.py                # Email (smtplib) + Telegram (httpx) dispatch
├── state.py                   # JSON state file, alert suppression, atomic saves
├── list_devices.py            # One-time helper: lists all Meross devices and IDs
├── run_agent.vbs              # Windows launcher: starts run_agent.ps1 with no visible window
├── run_agent.ps1              # Windows wrapper: runs agent, logs to run.log
├── setup_task_scheduler.ps1   # One-time setup: registers Windows Scheduled Task
├── smartplug_agent.service     # systemd service unit (Mac/Linux)
├── smartplug_agent.timer       # systemd timer — every 30 min (Mac/Linux)
├── config.yaml                # Your credentials & schedule (not committed)
├── config.yaml.example        # Safe annotated template
├── requirements.txt
└── tests/
    ├── test_scheduler.py      # Boundary time tests for get_expected_state()
    ├── test_state.py          # Alert suppression, clear, atomic save
    └── test_config.py         # Config validation, resolve_auto_correct()
```

---

## Setup

### 1. Install Python 3.11+

Download from [python.org](https://www.python.org/downloads/).

### 2. Clone and install dependencies

```
git clone <repo>
cd smartplug_agent
python -m venv venv
```

Activate the virtual environment:

- **Windows:** `venv\Scripts\activate`
- **Mac/Linux:** `source venv/bin/activate`

Then install dependencies:

```
pip install -r requirements.txt
```

### 3. Create your config

Copy the example and fill in your credentials:

```
cp config.yaml.example config.yaml        # Mac/Linux
copy config.yaml.example config.yaml      # Windows
```

See the [Configuration](#configuration) section below for all options.

### 4. Find your device IDs

Run the helper script to list all devices registered to your Meross account:

```
python list_devices.py
```

Copy the device IDs into `config.yaml`.

### 5. Test a single run

```
python agent.py --config config.yaml --state state.json
```

Exit code `0` = all plugs healthy.

### 6. Schedule (runs every 30 minutes)

**Windows** — run once to register a Scheduled Task:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned   # one-time, if needed
.\setup_task_scheduler.ps1
```

The task runs every 30 minutes with no visible window. It uses `run_agent.vbs` to launch PowerShell via `wscript.exe`, which keeps the process fully hidden in the background. Output is appended to `run.log` (rotated at 1 MB) and missed runs are caught up on after reboot.

```powershell
Start-ScheduledTask -TaskName SmartPlugAgent          # trigger immediately
Get-Content run.log -Tail 50 -Wait                    # follow the log
Unregister-ScheduledTask -TaskName SmartPlugAgent -Confirm:$false  # remove
```

**Mac/Linux** — install the included systemd timer:

```bash
sudo cp smartplug_agent.service smartplug_agent.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now smartplug_agent.timer
journalctl -u smartplug_agent -f
```

---

## Configuration

```yaml
meross:
  email: "user@example.com"
  password: "your-meross-password"

# Auto-correct behaviour:
#   "all"      - correct every plug regardless of per-plug setting
#   "none"     - never auto-correct any plug
#   "per_plug" - respect each plug's own auto_correct flag (default)
auto_correct: "per_plug"

plugs:
  - name: "Office Lamp"
    device_id: "abc123"          # from list_devices.py
    auto_correct: false
    schedule:
      - days: ["mon", "tue", "wed", "thu", "fri"]
        on_time: "07:00"
        off_time: "22:00"
      - days: ["sat", "sun"]
        on_time: "09:00"
        off_time: "23:00"

notifications:
  email:
    enabled: true
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    smtp_user: "you@gmail.com"
    smtp_password: "your-16-character-app-password"  # Gmail App Password
    to: ["recipient@example.com"]
  telegram:
    enabled: true
    bot_token: "123456:ABC-DEF..."  # from @BotFather
    chat_id: "789012"               # from @userinfobot

alerts:
  suppress_repeat_minutes: 60
```

**Notes:**
- Schedule times use your machine's local timezone.
- Overnight spans (e.g. `on_time: "22:00"` / `off_time: "06:00"`) are not supported — use two rules instead.
- Days with no matching schedule rule → plug is ignored (no alert, no action).
- For Gmail, generate an [App Password](https://support.google.com/accounts/answer/185833) rather than using your account password.

---

## Alert Suppression

Alert history is persisted in `state.json` keyed by `device_id:issue_type`. Once an alert fires, it will not fire again for the same plug and issue until `suppress_repeat_minutes` has elapsed. When a plug recovers, its history is cleared so the next failure alerts immediately.

| Event | Behaviour |
|---|---|
| Plug unreachable | Alert once; suppress repeats for `suppress_repeat_minutes` |
| Plug in wrong state | Alert once; suppress repeats |
| Plug recovers | History cleared — next failure alerts immediately |
| No schedule for today | History cleared; plug is ignored |

All issues detected in a single run are combined into one notification.

---

## Notifications

**Email** — uses STARTTLS on port 587.

**Telegram** — create a bot via [@BotFather](https://t.me/BotFather), start a conversation with it, then get your `chat_id` from [@userinfobot](https://t.me/userinfobot).

Both channels operate independently — a failure in one does not block the other.

---

## Dry Run

Simulate device states without connecting to Meross. Create `mock_states.json`:

```json
{
  "abc123": "off",
  "def456": "on"
}
```

```
python agent.py --dry-run --mock-states mock_states.json
```

---

## Tests

```
pytest tests/ -v
```
