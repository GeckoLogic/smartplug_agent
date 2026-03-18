"""
state.py - Persistent alert state management for Smart Plug Monitoring Agent
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Dict, Any

logger = logging.getLogger(__name__)

_ALERT_KEY = "alerts"


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso_now() -> str:
    return _now_utc().isoformat()


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string back into a timezone-aware datetime."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class StateManager:
    """
    Manages persistent alert suppression state stored in a JSON file.

    State file structure::

        {
            "alerts": {
                "<device_id>:<issue_type>": {
                    "last_alert": "<ISO 8601 UTC timestamp>"
                }
            }
        }
    """

    def __init__(self, state_file_path: str) -> None:
        self._path = state_file_path
        self._data: Dict[str, Any] = {_ALERT_KEY: {}}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """
        Load state from the JSON file.

        If the file is missing or corrupt, starts with an empty state and logs
        a warning.
        """
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if not isinstance(loaded, dict):
                raise ValueError("State file root is not a JSON object")
            self._data = loaded
            if _ALERT_KEY not in self._data or not isinstance(
                self._data[_ALERT_KEY], dict
            ):
                self._data[_ALERT_KEY] = {}
            logger.debug("State loaded from '%s'", self._path)
        except FileNotFoundError:
            logger.debug(
                "State file '%s' not found; starting with empty state", self._path
            )
            self._data = {_ALERT_KEY: {}}
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            logger.warning(
                "Could not load state from '%s' (%s); starting with empty state",
                self._path,
                exc,
            )
            self._data = {_ALERT_KEY: {}}

    def save(self) -> None:
        """
        Atomically write state to the JSON file using a temp file + os.replace().
        """
        dir_name = os.path.dirname(os.path.abspath(self._path))
        try:
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self._data, fh, indent=2)
                os.replace(tmp_path, self._path)
            except Exception:
                # Clean up temp file if something went wrong
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as exc:
            logger.error("Failed to save state to '%s': %s", self._path, exc)

    # ------------------------------------------------------------------
    # Alert helpers
    # ------------------------------------------------------------------

    def _alert_key(self, plug_id: str, issue_type: str) -> str:
        return f"{plug_id}:{issue_type}"

    def should_alert(
        self, plug_id: str, issue_type: str, suppress_minutes: int
    ) -> bool:
        """
        Return True if an alert should be sent for this plug/issue combination.

        An alert should be sent if:
        - No prior alert has been recorded, OR
        - The last alert is older than suppress_minutes.
        """
        key = self._alert_key(plug_id, issue_type)
        alerts = self._data.get(_ALERT_KEY, {})
        entry = alerts.get(key)

        if entry is None:
            return True

        last_alert_str = entry.get("last_alert")
        if not last_alert_str:
            return True

        try:
            last_alert_dt = _parse_iso(last_alert_str)
        except (ValueError, TypeError):
            # Corrupt timestamp → allow alert
            return True

        elapsed_minutes = (_now_utc() - last_alert_dt).total_seconds() / 60.0
        return elapsed_minutes > suppress_minutes

    def record_alert(self, plug_id: str, issue_type: str) -> None:
        """Record that an alert was sent right now (UTC)."""
        key = self._alert_key(plug_id, issue_type)
        if _ALERT_KEY not in self._data:
            self._data[_ALERT_KEY] = {}
        self._data[_ALERT_KEY][key] = {"last_alert": _iso_now()}

    def clear_issue(self, plug_id: str, issue_type: str) -> None:
        """Remove the alert record for this plug/issue so future checks are fresh."""
        key = self._alert_key(plug_id, issue_type)
        alerts = self._data.get(_ALERT_KEY, {})
        if key in alerts:
            del alerts[key]
            logger.debug("Cleared issue state for '%s'", key)
