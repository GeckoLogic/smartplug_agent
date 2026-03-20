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

    Returns (healthy: bool, new_alert: str | None, ongoing_alert: str | None).
    new_alert is set when the issue is new (passes suppression window).
    ongoing_alert is set when the issue exists but is within the suppression window.
    """
    plug_id = plug.device_id

    expected = get_expected_state(plug, now)
    logger.info("Plug '%s' (%s): expected_state='%s'", plug.name, plug_id, expected)

    if expected == "no_rule":
        state_manager.clear_issue(plug_id, "unreachable")
        state_manager.clear_issue(plug_id, "wrong_state")
        return True, None, None

    actual = await client.get_plug_state(plug_id)
    logger.info("Plug '%s' (%s): actual_state='%s'", plug.name, plug_id, actual)

    if actual == "unreachable":
        alert_text = f"'{plug.name}' is unreachable (expected: {expected})"
        if state_manager.should_alert(plug_id, "unreachable", cfg.suppress_repeat_minutes):
            state_manager.record_alert(plug_id, "unreachable")
            return False, alert_text, None
        else:
            logger.info("Plug '%s' unreachable alert suppressed", plug.name)
            return False, None, alert_text

    state_manager.clear_issue(plug_id, "unreachable")

    if actual == expected:
        state_manager.clear_issue(plug_id, "wrong_state")
        logger.info("Plug '%s' (%s): state is correct ('%s')", plug.name, plug_id, actual)
        return True, None, None

    # Wrong state
    logger.warning(
        "Plug '%s' (%s): wrong state (expected '%s', actual '%s')",
        plug.name, plug_id, expected, actual,
    )

    should_fix = resolve_auto_correct(cfg.auto_correct_mode, plug.auto_correct)

    if should_fix and not dry_run:
        logger.info("Auto-correcting plug '%s' to '%s'", plug.name, expected)
        success = await client.set_plug_state(plug_id, expected)
        fix_note = "auto-correction succeeded" if success else "auto-correction failed"
        if not success:
            logger.error("Failed to auto-correct plug '%s'", plug.name)
    elif should_fix and dry_run:
        logger.info("[DRY-RUN] Would auto-correct plug '%s' to '%s'", plug.name, expected)
        fix_note = "dry-run: auto-correction not applied"
    else:
        fix_note = None

    alert_text = f"'{plug.name}' is in wrong state (expected: {expected}, actual: {actual})"
    if fix_note:
        alert_text += f" — {fix_note}"

    if state_manager.should_alert(plug_id, "wrong_state", cfg.suppress_repeat_minutes):
        state_manager.record_alert(plug_id, "wrong_state")
        return False, alert_text, None
    else:
        logger.info("Plug '%s' wrong_state alert suppressed", plug.name)
        return False, None, alert_text


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
    new_alerts = []
    ongoing_alerts = []

    if args.dry_run:
        client = MockMerossClient(args.mock_states)
        for plug in cfg.plugs:
            healthy, new_alert, ongoing_alert = await check_plug(plug, client, state_manager, cfg, now, dry_run=True)
            if not healthy:
                all_healthy = False
            if new_alert:
                new_alerts.append(new_alert)
            if ongoing_alert:
                ongoing_alerts.append(ongoing_alert)
    else:
        try:
            async with MerossClientWrapper(cfg.meross_email, cfg.meross_password) as client:
                for plug in cfg.plugs:
                    healthy, new_alert, ongoing_alert = await check_plug(
                        plug, client, state_manager, cfg, now, dry_run=False
                    )
                    if not healthy:
                        all_healthy = False
                    if new_alert:
                        new_alerts.append(new_alert)
                    if ongoing_alert:
                        ongoing_alerts.append(ongoing_alert)
        except Exception as exc:
            logger.error("Fatal error connecting to Meross cloud: %s", exc)
            if state_manager.should_alert("_cloud", "connection_failed", cfg.suppress_repeat_minutes):
                subject = "[SmartPlugAgent] Cannot reach Meross cloud — checks skipped"
                body = (
                    f"Time: {now.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"The agent could not connect to the Meross cloud. "
                    f"No plug states were checked this run.\n\nError: {exc}"
                )
                await notify(cfg.notifications, subject, body)
                state_manager.record_alert("_cloud", "connection_failed")
            else:
                logger.info("Meross connection failure alert suppressed")
            state_manager.save()
            return 2

    state_manager.clear_issue("_cloud", "connection_failed")

    if new_alerts:
        all_issues = new_alerts + ongoing_alerts
        count = len(all_issues)
        subject = f"[SmartPlugAgent] {count} issue{'s' if count > 1 else ''} detected"
        body_parts = [f"Time: {now.strftime('%Y-%m-%d %H:%M:%S')}\n", "New issues:"]
        body_parts.extend(f"• {a}" for a in new_alerts)
        if ongoing_alerts:
            body_parts.append("\nOngoing issues:")
            body_parts.extend(f"• {a}" for a in ongoing_alerts)
        body = "\n".join(body_parts)
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
