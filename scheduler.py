"""
scheduler.py - Schedule evaluation logic for Smart Plug Monitoring Agent
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from config import PlugConfig

# Maps datetime.weekday() integer → abbreviated day name
WEEKDAY_MAP = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def get_expected_state(
    plug: PlugConfig, now: datetime
) -> Literal["on", "off", "no_rule"]:
    """
    Return the expected state of a plug at the given datetime.

    Returns:
        "on"      - a schedule rule covers this day and the current time falls
                    within [on_time, off_time)
        "off"     - a schedule rule covers this day but the current time is
                    outside the on window
        "no_rule" - no schedule rule covers the current day at all
    """
    current_day = WEEKDAY_MAP[now.weekday()]
    current_time = now.time()

    for rule in plug.schedule:
        if current_day in rule.days:
            # A rule covers today
            if rule.on_time <= current_time < rule.off_time:
                return "on"
            else:
                return "off"

    return "no_rule"
