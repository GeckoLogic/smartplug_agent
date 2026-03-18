"""
tests/test_config.py - Tests for load_config and resolve_auto_correct
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import time

import pytest
import yaml

from config import ConfigError, load_config, resolve_auto_correct


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_yaml(path, data: dict) -> str:
    """Serialise data as YAML and write to path. Returns path as string."""
    file_path = str(path)
    with open(file_path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh)
    return file_path


VALID_CONFIG = {
    "meross": {
        "email": "user@example.com",
        "password": "secret",
    },
    "auto_correct": "per_plug",
    "plugs": [
        {
            "name": "Office Lamp",
            "device_id": "abc123",
            "auto_correct": False,
            "schedule": [
                {
                    "days": ["mon", "tue", "wed", "thu", "fri"],
                    "on_time": "07:00",
                    "off_time": "22:00",
                },
                {
                    "days": ["sat", "sun"],
                    "on_time": "09:00",
                    "off_time": "23:00",
                },
            ],
        },
        {
            "name": "Living Room Fan",
            "device_id": "def456",
            "schedule": [
                {
                    "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                    "on_time": "08:00",
                    "off_time": "23:00",
                }
            ],
        },
    ],
    "notifications": {
        "email": {
            "enabled": True,
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "user@gmail.com",
            "smtp_password": "apppassword",
            "to": ["recipient@example.com"],
        },
        "telegram": {
            "enabled": True,
            "bot_token": "123456:ABC-DEF",
            "chat_id": "789012",
        },
    },
    "alerts": {
        "suppress_repeat_minutes": 60,
    },
}


# ---------------------------------------------------------------------------
# load_config tests
# ---------------------------------------------------------------------------

class TestLoadConfig:

    def test_valid_config_loads_correctly(self, tmp_path):
        """A fully valid config file should load without errors."""
        cfg_path = write_yaml(tmp_path / "config.yaml", VALID_CONFIG)
        cfg = load_config(cfg_path)

        assert cfg.meross_email == "user@example.com"
        assert cfg.meross_password == "secret"
        assert cfg.auto_correct_mode == "per_plug"
        assert len(cfg.plugs) == 2

        office_lamp = cfg.plugs[0]
        assert office_lamp.name == "Office Lamp"
        assert office_lamp.device_id == "abc123"
        assert office_lamp.auto_correct is False
        assert len(office_lamp.schedule) == 2

        rule0 = office_lamp.schedule[0]
        assert rule0.on_time == time(7, 0)
        assert rule0.off_time == time(22, 0)
        assert "mon" in rule0.days
        assert "fri" in rule0.days

        assert cfg.notifications.email is not None
        assert cfg.notifications.email.smtp_host == "smtp.gmail.com"
        assert cfg.notifications.telegram is not None
        assert cfg.notifications.telegram.chat_id == "789012"
        assert cfg.suppress_repeat_minutes == 60

    def test_missing_meross_email_raises_config_error(self, tmp_path):
        """Missing meross.email should raise ConfigError."""
        data = dict(VALID_CONFIG)
        data["meross"] = {"password": "secret"}
        cfg_path = write_yaml(tmp_path / "config.yaml", data)

        with pytest.raises(ConfigError, match="email"):
            load_config(cfg_path)

    def test_off_time_lte_on_time_raises_config_error(self, tmp_path):
        """off_time <= on_time should raise ConfigError."""
        import copy
        data = copy.deepcopy(VALID_CONFIG)
        # Set off_time to equal on_time
        data["plugs"][0]["schedule"][0]["off_time"] = "07:00"
        cfg_path = write_yaml(tmp_path / "config.yaml", data)

        with pytest.raises(ConfigError, match="off_time"):
            load_config(cfg_path)

    def test_duplicate_device_id_raises_config_error(self, tmp_path):
        """Duplicate device_id values should raise ConfigError."""
        import copy
        data = copy.deepcopy(VALID_CONFIG)
        data["plugs"][1]["device_id"] = "abc123"  # same as plug 0
        cfg_path = write_yaml(tmp_path / "config.yaml", data)

        with pytest.raises(ConfigError, match="[Dd]uplicate"):
            load_config(cfg_path)

    def test_invalid_global_auto_correct_raises_config_error(self, tmp_path):
        """An invalid global auto_correct value should raise ConfigError."""
        import copy
        data = copy.deepcopy(VALID_CONFIG)
        data["auto_correct"] = "sometimes"  # not valid
        cfg_path = write_yaml(tmp_path / "config.yaml", data)

        with pytest.raises(ConfigError, match="auto_correct"):
            load_config(cfg_path)

    def test_per_plug_auto_correct_defaults_to_false(self, tmp_path):
        """Per-plug auto_correct should default to False when omitted."""
        import copy
        data = copy.deepcopy(VALID_CONFIG)
        # Remove auto_correct from plug 1 (Living Room Fan already lacks it)
        del data["plugs"][0]["auto_correct"]
        cfg_path = write_yaml(tmp_path / "config.yaml", data)

        cfg = load_config(cfg_path)
        assert cfg.plugs[0].auto_correct is False
        assert cfg.plugs[1].auto_correct is False

    def test_global_auto_correct_defaults_to_per_plug(self, tmp_path):
        """Global auto_correct should default to 'per_plug' when omitted."""
        import copy
        data = copy.deepcopy(VALID_CONFIG)
        del data["auto_correct"]
        cfg_path = write_yaml(tmp_path / "config.yaml", data)

        cfg = load_config(cfg_path)
        assert cfg.auto_correct_mode == "per_plug"

    def test_off_time_earlier_than_on_time_raises_config_error(self, tmp_path):
        """off_time earlier than on_time should raise ConfigError."""
        import copy
        data = copy.deepcopy(VALID_CONFIG)
        data["plugs"][0]["schedule"][0]["on_time"] = "22:00"
        data["plugs"][0]["schedule"][0]["off_time"] = "07:00"
        cfg_path = write_yaml(tmp_path / "config.yaml", data)

        with pytest.raises(ConfigError):
            load_config(cfg_path)

    def test_overlapping_rules_for_same_day_raises_config_error(self, tmp_path):
        """Schedule rules that overlap on the same day should raise ConfigError."""
        import copy
        data = copy.deepcopy(VALID_CONFIG)
        # Add a second rule that also covers "mon"
        data["plugs"][0]["schedule"].append({
            "days": ["mon"],
            "on_time": "10:00",
            "off_time": "20:00",
        })
        cfg_path = write_yaml(tmp_path / "config.yaml", data)

        with pytest.raises(ConfigError, match="[Oo]verlap"):
            load_config(cfg_path)

    def test_all_global_auto_correct_loads(self, tmp_path):
        """Global auto_correct = 'all' is a valid value."""
        import copy
        data = copy.deepcopy(VALID_CONFIG)
        data["auto_correct"] = "all"
        cfg_path = write_yaml(tmp_path / "config.yaml", data)

        cfg = load_config(cfg_path)
        assert cfg.auto_correct_mode == "all"

    def test_none_global_auto_correct_loads(self, tmp_path):
        """Global auto_correct = 'none' is a valid value."""
        import copy
        data = copy.deepcopy(VALID_CONFIG)
        data["auto_correct"] = "none"
        cfg_path = write_yaml(tmp_path / "config.yaml", data)

        cfg = load_config(cfg_path)
        assert cfg.auto_correct_mode == "none"


# ---------------------------------------------------------------------------
# resolve_auto_correct tests
# ---------------------------------------------------------------------------

class TestResolveAutoCorrect:

    def test_all_mode_returns_true_regardless_of_plug_flag(self):
        """'all' mode always returns True."""
        assert resolve_auto_correct("all", False) is True
        assert resolve_auto_correct("all", True) is True

    def test_none_mode_returns_false_regardless_of_plug_flag(self):
        """'none' mode always returns False."""
        assert resolve_auto_correct("none", True) is False
        assert resolve_auto_correct("none", False) is False

    def test_per_plug_mode_returns_true_when_plug_flag_true(self):
        """'per_plug' mode returns True when plug_flag is True."""
        assert resolve_auto_correct("per_plug", True) is True

    def test_per_plug_mode_returns_false_when_plug_flag_false(self):
        """'per_plug' mode returns False when plug_flag is False."""
        assert resolve_auto_correct("per_plug", False) is False
