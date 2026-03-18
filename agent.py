"""
agent.py - CLI entry point for Smart Plug Monitoring Agent
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Union

from config import AppConfig, ConfigError, load_config, resolve_auto_correct
from meross_client import MerossClientWrapper, MockMerossClient
from notifier import notify
from scheduler import get_expected_state
from state import StateManager

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smart Plug Monitoring Agent",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="PATH",
        help="Path to the YAML configuration file",
    )
    parser.add_argument(
        "--state",
        default="state.json",
        metavar="PATH",
        help="Path to the JSON state file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use MockMerossClient; device states are read from --mock-states file",
    )
    parser.add_argument(
        "--mock-states",
        default="mock_states.json",
        metavar="PATH",
        help="Path to mock states JSON file (only used with --dry-run)",
    )
    return parser


async def check_plug(
    plug,
    client: Union[MerossClientWrapper, MockMerossClient],
    state_manager: StateManager,
    cfg: AppConfig,
    now: datetime,
    dry_run: bool,
) -> tuple:
    """
    Check a single plug's current state against its schedule.

    Returns (healthy: bool, alert_text: str | None).
    alert_text is set only when an alert should be sent (passes suppression window).
    """
    plug_id = plug.device_id

    expected = get_expected_state(plug, now)
    logger.info("Plug '%s' (%s): expected_state='%s'", plug.name, plug_id, expected)

    if expected == "no_rule":
        state_manager.clear_issue(plug_id, "unreachable")
        state_manager.clear_issue(plug_id, "wrong_state")
        return True, None

    actual = await client.get_plug_state(plug_id)
    logger.info("Plug '%s' (%s): actual_state='%s'", plug.name, plug_id, actual)

    if actual == "unreachable":
        alert_text = None
        if state_manager.should_alert(plug_id, "unreachable", cfg.suppress_repeat_minutes):
            alert_text = (
                f"'{plug.name}' is unreachable (expected: {expected})"
            )
            state_manager.record_alert(plug_id, "unreachable")
        else:
            logger.info("Plug '%s' unreachable alert suppressed", plug.name)
        return False, alert_text

    state_manager.clear_issue(plug_id, "unreachable")

    if actual == expected:
        state_manager.clear_issue(plug_id, "wrong_state")
        logger.info("Plug '%s' (%s): state is correct ('%s')", plug.name, plug_id, actual)
        return True, None

    # Wrong state
    logger.warning(
        "Plug '%s' (%s): wrong state (expected '%s', actual '%s')",
        plug.name, plug_id, expected, actual,
    )

    should_fix = resolve_auto_correct(cfg.auto_correct_mode, plug.auto_correct)

    if should_fix and not dry_run:
        logger.info("Auto-correcting plug '%s' to '%s'", plug.name, expected)
        success = await client.set_plug_state(plug_id, expected)
        fix_note = "auto-correction attempted" if success else "auto-correction failed"
        if not success:
            logger.error("Failed to auto-correct plug '%s'", plug.name)
    elif should_fix and dry_run:
        logger.info("[DRY-RUN] Would auto-correct plug '%s' to '%s'", plug.name, expected)
        fix_note = "dry-run: auto-correction not applied"
    else:
        fix_note = None

    alert_text = None
    if state_manager.should_alert(plug_id, "wrong_state", cfg.suppress_repeat_minutes):
        alert_text = f"'{plug.name}' is in wrong state (expected: {expected}, actual: {actual})"
        if fix_note:
            alert_text += f" — {fix_note}"
        state_manager.record_alert(plug_id, "wrong_state")
    else:
        logger.info("Plug '%s' wrong_state alert suppressed", plug.name)

    return False, alert_text


async def async_main(args: argparse.Namespace) -> int:
    """Main async logic. Returns exit code."""
    # Load configuration
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        # Logging may not be configured yet; print to stderr as fallback
        print(f"FATAL: Configuration error: {exc}", file=sys.stderr)
        return 2

    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    logger.info("Smart Plug Agent starting (dry_run=%s)", args.dry_run)
    logger.info("Loaded config: %d plug(s)", len(cfg.plugs))

    # Initialise state manager
    state_manager = StateManager(args.state)
    state_manager.load()

    now = datetime.now().astimezone()

    all_healthy = True
    alerts = []

    if args.dry_run:
        client = MockMerossClient(args.mock_states)
        for plug in cfg.plugs:
            healthy, alert_text = await check_plug(plug, client, state_manager, cfg, now, dry_run=True)
            if not healthy:
                all_healthy = False
            if alert_text:
                alerts.append(alert_text)
    else:
        try:
            async with MerossClientWrapper(cfg.meross_email, cfg.meross_password) as client:
                for plug in cfg.plugs:
                    healthy, alert_text = await check_plug(
                        plug, client, state_manager, cfg, now, dry_run=False
                    )
                    if not healthy:
                        all_healthy = False
                    if alert_text:
                        alerts.append(alert_text)
        except Exception as exc:
            logger.error("Fatal error connecting to Meross cloud: %s", exc)
            state_manager.save()
            return 2

    if alerts:
        count = len(alerts)
        subject = f"[SmartPlugAgent] {count} issue{'s' if count > 1 else ''} detected"
        body = f"Time: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n" + "\n".join(f"• {a}" for a in alerts)
        await notify(cfg.notifications, subject, body)

    state_manager.save()

    exit_code = 0 if all_healthy else 1
    logger.info("Smart Plug Agent finished with exit code %d", exit_code)
    return exit_code


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    sys.exit(main())
