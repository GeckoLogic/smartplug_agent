"""
tests/test_state.py - Tests for StateManager
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from datetime import datetime, timedelta, timezone

import pytest

from state import StateManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_state(path, data: dict):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _read_state(path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStateManager:

    def test_should_alert_true_when_no_prior_alert(self, tmp_path):
        """should_alert returns True when there is no prior alert record."""
        state_file = str(tmp_path / "state.json")
        sm = StateManager(state_file)
        sm.load()

        assert sm.should_alert("device1", "unreachable", suppress_minutes=60) is True

    def test_should_alert_false_immediately_after_record(self, tmp_path):
        """After record_alert, should_alert returns False (within suppress window)."""
        state_file = str(tmp_path / "state.json")
        sm = StateManager(state_file)
        sm.load()

        sm.record_alert("device1", "unreachable")
        assert sm.should_alert("device1", "unreachable", suppress_minutes=60) is False

    def test_should_alert_true_after_suppress_window_expires(self, tmp_path):
        """should_alert returns True when the last alert timestamp is older than suppress_minutes."""
        state_file = str(tmp_path / "state.json")

        # Pre-populate the state file with a timestamp 2 hours in the past
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
        _write_state(
            state_file,
            {"alerts": {"device1:wrong_state": {"last_alert": old_ts}}},
        )

        sm = StateManager(state_file)
        sm.load()

        assert sm.should_alert("device1", "wrong_state", suppress_minutes=60) is True

    def test_clear_issue_allows_alert_again(self, tmp_path):
        """After clear_issue, should_alert returns True regardless of prior record."""
        state_file = str(tmp_path / "state.json")
        sm = StateManager(state_file)
        sm.load()

        sm.record_alert("device1", "unreachable")
        assert sm.should_alert("device1", "unreachable", suppress_minutes=60) is False

        sm.clear_issue("device1", "unreachable")
        assert sm.should_alert("device1", "unreachable", suppress_minutes=60) is True

    def test_load_missing_file_starts_empty(self, tmp_path):
        """Loading from a non-existent file does not raise and starts with empty state."""
        state_file = str(tmp_path / "nonexistent.json")
        sm = StateManager(state_file)
        sm.load()  # Should not raise

        # No record → should_alert returns True
        assert sm.should_alert("any_device", "any_issue", suppress_minutes=60) is True

    def test_load_corrupt_file_starts_empty(self, tmp_path):
        """Loading from a corrupt JSON file does not raise and starts with empty state."""
        state_file = str(tmp_path / "corrupt.json")
        with open(state_file, "w") as fh:
            fh.write("{this is not valid json !!!")

        sm = StateManager(state_file)
        sm.load()  # Should not raise

        assert sm.should_alert("device1", "unreachable", suppress_minutes=60) is True

    def test_atomic_save_and_reload(self, tmp_path):
        """Data saved to disk can be successfully reloaded in a new StateManager instance."""
        state_file = str(tmp_path / "state.json")
        sm = StateManager(state_file)
        sm.load()

        sm.record_alert("device_abc", "wrong_state")
        sm.save()

        # New instance reloads from disk
        sm2 = StateManager(state_file)
        sm2.load()

        # The alert was recent, so should_alert should return False
        assert sm2.should_alert("device_abc", "wrong_state", suppress_minutes=60) is False

    def test_save_creates_file(self, tmp_path):
        """save() creates the state file even if it didn't exist before."""
        state_file = str(tmp_path / "new_state.json")
        assert not os.path.exists(state_file)

        sm = StateManager(state_file)
        sm.load()
        sm.record_alert("dev1", "unreachable")
        sm.save()

        assert os.path.exists(state_file)
        data = _read_state(state_file)
        assert "alerts" in data
        assert "dev1:unreachable" in data["alerts"]

    def test_clear_issue_on_nonexistent_key_is_noop(self, tmp_path):
        """clear_issue on a key that doesn't exist should not raise."""
        state_file = str(tmp_path / "state.json")
        sm = StateManager(state_file)
        sm.load()

        sm.clear_issue("nonexistent_device", "wrong_state")  # Should not raise

    def test_multiple_plugs_independent(self, tmp_path):
        """Alerts for different plugs/issues are tracked independently."""
        state_file = str(tmp_path / "state.json")
        sm = StateManager(state_file)
        sm.load()

        sm.record_alert("device1", "unreachable")
        sm.record_alert("device2", "wrong_state")

        # device1 unreachable is suppressed
        assert sm.should_alert("device1", "unreachable", suppress_minutes=60) is False
        # device2 wrong_state is suppressed
        assert sm.should_alert("device2", "wrong_state", suppress_minutes=60) is False
        # device1 wrong_state has no record → alert allowed
        assert sm.should_alert("device1", "wrong_state", suppress_minutes=60) is True
        # device2 unreachable has no record → alert allowed
        assert sm.should_alert("device2", "unreachable", suppress_minutes=60) is True
