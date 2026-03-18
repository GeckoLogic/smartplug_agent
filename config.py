"""
config.py - Configuration loading and validation for Smart Plug Monitoring Agent
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import time
from typing import List, Optional

import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid."""
    pass


@dataclass
class ScheduleRule:
    days: List[str]
    on_time: time
    off_time: time


@dataclass
class EmailConfig:
    enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    to: List[str]


@dataclass
class TelegramConfig:
    enabled: bool
    bot_token: str
    chat_id: str


@dataclass
class NotificationConfig:
    email: Optional[EmailConfig] = None
    telegram: Optional[TelegramConfig] = None


@dataclass
class AlertConfig:
    suppress_repeat_minutes: int = 60


@dataclass
class PlugConfig:
    name: str
    device_id: str
    schedule: List[ScheduleRule]
    auto_correct: bool = False


@dataclass
class AppConfig:
    meross_email: str
    meross_password: str
    plugs: List[PlugConfig]
    auto_correct_mode: str = "per_plug"
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    suppress_repeat_minutes: int = 60


VALID_DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
VALID_AUTO_CORRECT_MODES = {"all", "none", "per_plug"}


def _parse_time(value: str, context: str) -> time:
    """Parse a time string like '07:00' into a datetime.time object."""
    if isinstance(value, time):
        return value
    try:
        parts = str(value).strip().split(":")
        if len(parts) != 2:
            raise ValueError("Expected HH:MM format")
        return time(int(parts[0]), int(parts[1]))
    except (ValueError, AttributeError) as exc:
        raise ConfigError(f"Invalid time value '{value}' in {context}: {exc}") from exc


def _parse_schedule_rule(rule_data: dict, plug_name: str) -> ScheduleRule:
    """Parse a single schedule rule dict into a ScheduleRule."""
    if "days" not in rule_data:
        raise ConfigError(f"Schedule rule for plug '{plug_name}' is missing 'days'")
    if "on_time" not in rule_data:
        raise ConfigError(f"Schedule rule for plug '{plug_name}' is missing 'on_time'")
    if "off_time" not in rule_data:
        raise ConfigError(f"Schedule rule for plug '{plug_name}' is missing 'off_time'")

    days = rule_data["days"]
    if not isinstance(days, list) or len(days) == 0:
        raise ConfigError(f"'days' for plug '{plug_name}' must be a non-empty list")

    for d in days:
        if d not in VALID_DAYS:
            raise ConfigError(
                f"Invalid day '{d}' in schedule for plug '{plug_name}'. "
                f"Valid values: {sorted(VALID_DAYS)}"
            )

    on_time = _parse_time(rule_data["on_time"], f"plug '{plug_name}' on_time")
    off_time = _parse_time(rule_data["off_time"], f"plug '{plug_name}' off_time")

    if off_time <= on_time:
        raise ConfigError(
            f"off_time ({off_time}) must be greater than on_time ({on_time}) "
            f"for plug '{plug_name}'. Overnight spans are not supported."
        )

    return ScheduleRule(days=days, on_time=on_time, off_time=off_time)


def _check_overlapping_rules(rules: List[ScheduleRule], plug_name: str) -> None:
    """Raise ConfigError if any two rules cover the same day."""
    day_seen: dict = {}
    for rule in rules:
        for day in rule.days:
            if day in day_seen:
                raise ConfigError(
                    f"Plug '{plug_name}' has overlapping schedule rules for day '{day}'"
                )
            day_seen[day] = rule


def _parse_email_config(data: dict) -> EmailConfig:
    required = ["smtp_host", "smtp_user", "smtp_password", "to"]
    for field_name in required:
        if field_name not in data:
            raise ConfigError(f"Email config is missing required field '{field_name}'")
    return EmailConfig(
        enabled=data.get("enabled", False),
        smtp_host=data["smtp_host"],
        smtp_port=data.get("smtp_port", 587),
        smtp_user=data["smtp_user"],
        smtp_password=data["smtp_password"],
        to=data["to"],
    )


def _parse_telegram_config(data: dict) -> TelegramConfig:
    required = ["bot_token", "chat_id"]
    for field_name in required:
        if field_name not in data:
            raise ConfigError(f"Telegram config is missing required field '{field_name}'")
    return TelegramConfig(
        enabled=data.get("enabled", False),
        bot_token=data["bot_token"],
        chat_id=str(data["chat_id"]),
    )


def load_config(path: str) -> AppConfig:
    """Load and validate configuration from a YAML file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except FileNotFoundError:
        raise ConfigError(f"Configuration file not found: {path}")
    except yaml.YAMLError as exc:
        raise ConfigError(f"Failed to parse YAML configuration: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError("Configuration must be a YAML mapping at the top level")

    # --- meross credentials ---
    meross = data.get("meross")
    if not isinstance(meross, dict):
        raise ConfigError("Missing required 'meross' section in configuration")

    meross_email = meross.get("email")
    if not meross_email:
        raise ConfigError("Missing required field 'meross.email'")

    meross_password = meross.get("password")
    if not meross_password:
        raise ConfigError("Missing required field 'meross.password'")

    # --- global auto_correct mode ---
    auto_correct_mode = data.get("auto_correct", "per_plug")
    if auto_correct_mode not in VALID_AUTO_CORRECT_MODES:
        raise ConfigError(
            f"Invalid global 'auto_correct' value '{auto_correct_mode}'. "
            f"Must be one of: {sorted(VALID_AUTO_CORRECT_MODES)}"
        )

    # --- plugs ---
    plugs_data = data.get("plugs")
    if not plugs_data or not isinstance(plugs_data, list):
        raise ConfigError("Configuration must include a non-empty 'plugs' list")

    plugs: List[PlugConfig] = []
    seen_device_ids: set = set()

    for plug_data in plugs_data:
        if not isinstance(plug_data, dict):
            raise ConfigError("Each plug entry must be a YAML mapping")

        plug_name = plug_data.get("name")
        if not plug_name:
            raise ConfigError("Each plug must have a 'name' field")

        device_id = plug_data.get("device_id")
        if not device_id:
            raise ConfigError(f"Plug '{plug_name}' is missing 'device_id'")

        if device_id in seen_device_ids:
            raise ConfigError(f"Duplicate device_id '{device_id}' found in configuration")
        seen_device_ids.add(device_id)

        schedule_data = plug_data.get("schedule")
        if not schedule_data or not isinstance(schedule_data, list):
            raise ConfigError(f"Plug '{plug_name}' must have a non-empty 'schedule' list")

        rules: List[ScheduleRule] = []
        for rule_data in schedule_data:
            rules.append(_parse_schedule_rule(rule_data, plug_name))

        _check_overlapping_rules(rules, plug_name)

        plug_auto_correct = plug_data.get("auto_correct", False)
        if not isinstance(plug_auto_correct, bool):
            raise ConfigError(
                f"Per-plug 'auto_correct' for '{plug_name}' must be a boolean (true/false)"
            )

        plugs.append(PlugConfig(
            name=plug_name,
            device_id=device_id,
            schedule=rules,
            auto_correct=plug_auto_correct,
        ))

    # --- notifications ---
    notifications_data = data.get("notifications", {}) or {}
    email_cfg: Optional[EmailConfig] = None
    telegram_cfg: Optional[TelegramConfig] = None

    if "email" in notifications_data:
        email_cfg = _parse_email_config(notifications_data["email"])
    if "telegram" in notifications_data:
        telegram_cfg = _parse_telegram_config(notifications_data["telegram"])

    notifications = NotificationConfig(email=email_cfg, telegram=telegram_cfg)

    # --- alerts ---
    alerts_data = data.get("alerts", {}) or {}
    suppress_repeat_minutes = alerts_data.get("suppress_repeat_minutes", 60)

    return AppConfig(
        meross_email=meross_email,
        meross_password=meross_password,
        auto_correct_mode=auto_correct_mode,
        plugs=plugs,
        notifications=notifications,
        suppress_repeat_minutes=suppress_repeat_minutes,
    )


def resolve_auto_correct(global_mode: str, plug_flag: bool) -> bool:
    """
    Determine whether auto-correction should be applied for a plug.

    - "all"      → always True
    - "none"     → always False
    - "per_plug" → use plug_flag
    """
    if global_mode == "all":
        return True
    if global_mode == "none":
        return False
    # "per_plug"
    return plug_flag
