"""
tests/test_scheduler.py - Tests for scheduler.get_expected_state
"""

import sys
import os

# Ensure the project root is on the path when running tests from the tests/ dir
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, time

import pytest

from config import PlugConfig, ScheduleRule
from scheduler import get_expected_state

# ---------------------------------------------------------------------------
# Shared fixture: a plug with two schedule rules
#   Weekdays (mon-fri): 07:00 – 22:00
#   Weekend  (sat-sun): 09:00 – 23:00
# ---------------------------------------------------------------------------

RULES = [
    ScheduleRule(
        days=["mon", "tue", "wed", "thu", "fri"],
        on_time=time(7, 0),
        off_time=time(22, 0),
    ),
    ScheduleRule(
        days=["sat", "sun"],
        on_time=time(9, 0),
        off_time=time(23, 0),
    ),
]


def make_plug(rules=None):
    return PlugConfig(
        name="Test Plug",
        device_id="test001",
        schedule=rules if rules is not None else RULES,
    )


def make_dt(weekday_name: str, hour: int, minute: int = 0) -> datetime:
    """
    Create a datetime on the most recent occurrence of a given weekday.

    weekday_name: "mon", "tue", …, "sun"
    """
    day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    target_wd = day_map[weekday_name]
    # Use a fixed base date that is a known Monday: 2024-01-01 (Monday)
    from datetime import date, timedelta
    base = date(2024, 1, 1)  # Monday
    delta = (target_wd - base.weekday()) % 7
    d = base + timedelta(days=delta)
    return datetime(d.year, d.month, d.day, hour, minute)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestGetExpectedState:

    def test_monday_within_window_returns_on(self):
        """Monday 08:00 is within the 07:00-22:00 weekday window → 'on'."""
        plug = make_plug()
        now = make_dt("mon", 8, 0)
        assert get_expected_state(plug, now) == "on"

    def test_monday_before_on_time_returns_off(self):
        """Monday 06:00 is before 07:00 on_time → 'off'."""
        plug = make_plug()
        now = make_dt("mon", 6, 0)
        assert get_expected_state(plug, now) == "off"

    def test_monday_after_off_time_returns_off(self):
        """Monday 23:00 is after 22:00 off_time → 'off'."""
        plug = make_plug()
        now = make_dt("mon", 23, 0)
        assert get_expected_state(plug, now) == "off"

    def test_sunday_within_window_returns_on(self):
        """Sunday 10:00 is within the 09:00-23:00 weekend window → 'on'."""
        plug = make_plug()
        now = make_dt("sun", 10, 0)
        assert get_expected_state(plug, now) == "on"

    def test_sunday_before_on_time_returns_off(self):
        """Sunday 08:00 is before 09:00 weekend on_time → 'off'."""
        plug = make_plug()
        now = make_dt("sun", 8, 0)
        assert get_expected_state(plug, now) == "off"

    def test_no_rule_for_day_returns_no_rule(self):
        """
        A plug whose schedule only covers weekdays should return 'no_rule'
        when checked on a Saturday.
        """
        weekday_only_rules = [
            ScheduleRule(
                days=["mon", "tue", "wed", "thu", "fri"],
                on_time=time(7, 0),
                off_time=time(22, 0),
            )
        ]
        plug = make_plug(rules=weekday_only_rules)
        # Saturday – not covered by any rule
        now = make_dt("sat", 10, 0)
        assert get_expected_state(plug, now) == "no_rule"

    def test_exact_on_time_boundary_is_on(self):
        """Exactly at on_time (07:00) the plug should be 'on'."""
        plug = make_plug()
        now = make_dt("mon", 7, 0)
        assert get_expected_state(plug, now) == "on"

    def test_exact_off_time_boundary_is_off(self):
        """Exactly at off_time (22:00) the plug should be 'off' (exclusive upper bound)."""
        plug = make_plug()
        now = make_dt("mon", 22, 0)
        assert get_expected_state(plug, now) == "off"

    def test_friday_within_weekday_rule(self):
        """Friday is covered by the weekday rule and at 12:00 should return 'on'."""
        plug = make_plug()
        now = make_dt("fri", 12, 0)
        assert get_expected_state(plug, now) == "on"

    def test_saturday_within_weekend_rule(self):
        """Saturday 21:00 is within the 09:00-23:00 weekend window → 'on'."""
        plug = make_plug()
        now = make_dt("sat", 21, 0)
        assert get_expected_state(plug, now) == "on"
