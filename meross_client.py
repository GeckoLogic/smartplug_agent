"""
meross_client.py - Meross smart plug client wrappers for Smart Plug Monitoring Agent
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

logger = logging.getLogger(__name__)

_TIMEOUT = 30  # seconds for device operations


class MerossClientWrapper:
    """
    Async context manager that manages a Meross HTTP + Manager session.

    Usage::

        async with MerossClientWrapper(email, password) as client:
            state = await client.get_plug_state("device_id")
    """

    def __init__(self, email: str, password: str, device_uuids: list = None) -> None:
        self._email = email
        self._password = password
        self._device_uuids = device_uuids
        self._http_client = None
        self._manager = None

    async def __aenter__(self) -> "MerossClientWrapper":
        try:
            from meross_iot.http_api import MerossHttpClient
            from meross_iot.manager import MerossManager

            self._http_client = await MerossHttpClient.async_from_user_password(
                api_base_url="https://iotx-us.meross.com",
                email=self._email,
                password=self._password,
            )
            self._manager = MerossManager(http_client=self._http_client)
            await self._manager.async_init()
            await self._manager.async_device_discovery()
        except Exception as exc:
            logger.error("Failed to initialise Meross client: %s", exc)
            await self.__aexit__(type(exc), exc, None)
            raise
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._manager is not None:
            try:
                self._manager.close()
            except Exception as exc:
                logger.warning("Error closing Meross manager: %s", exc)
            self._manager = None
        if self._http_client is not None:
            try:
                await self._http_client.async_logout()
            except Exception as exc:
                logger.warning("Error closing Meross HTTP client: %s", exc)
            self._http_client = None

    async def _get_device(self, device_id: str):
        """Retrieve a device from the manager by its UUID."""
        if self._manager is None:
            raise RuntimeError("Meross manager is not initialised")
        devices = self._manager.find_devices(device_uuids=[device_id])
        if not devices:
            raise LookupError(f"Device '{device_id}' not found in Meross account")
        return devices[0]

    async def get_plug_state(
        self, device_id: str
    ) -> Literal["on", "off", "unreachable"]:
        """
        Return the current power state of a plug.

        Returns "unreachable" if the device cannot be contacted or an error occurs.
        """
        try:
            async def _fetch():
                device = await self._get_device(device_id)
                await device.async_update()
                return device.is_on(channel=0)

            is_on = await asyncio.wait_for(_fetch(), timeout=_TIMEOUT)
            return "on" if is_on else "off"
        except asyncio.TimeoutError:
            logger.warning("Timeout fetching state for device '%s'", device_id)
            return "unreachable"
        except Exception as exc:
            logger.warning("Error fetching state for device '%s': %s", device_id, exc)
            return "unreachable"

    async def set_plug_state(
        self, device_id: str, target: Literal["on", "off"]
    ) -> bool:
        """
        Set the power state of a plug.

        Returns True on success, False on failure.
        """
        try:
            async def _set():
                device = await self._get_device(device_id)
                if target == "on":
                    await device.async_turn_on(channel=0)
                else:
                    await device.async_turn_off(channel=0)

            await asyncio.wait_for(_set(), timeout=_TIMEOUT)
            logger.info("Successfully set device '%s' to '%s'", device_id, target)
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "Timeout setting state for device '%s' to '%s'", device_id, target
            )
            return False
        except Exception as exc:
            logger.warning(
                "Error setting state for device '%s' to '%s': %s",
                device_id,
                target,
                exc,
            )
            return False


class MockMerossClient:
    """
    Mock Meross client for dry-run mode.

    Reads device states from a JSON file mapping device_id → "on"/"off"/"unreachable".
    All set_plug_state calls succeed (logged only).
    """

    def __init__(self, mock_file_path: str) -> None:
        self._mock_file_path = mock_file_path
        self._states: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._mock_file_path, "r", encoding="utf-8") as fh:
                self._states = json.load(fh)
            logger.info(
                "MockMerossClient loaded %d device states from '%s'",
                len(self._states),
                self._mock_file_path,
            )
        except FileNotFoundError:
            logger.warning(
                "Mock states file '%s' not found; all devices will be 'unreachable'",
                self._mock_file_path,
            )
            self._states = {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to load mock states from '%s': %s; all devices will be 'unreachable'",
                self._mock_file_path,
                exc,
            )
            self._states = {}

    async def get_plug_state(
        self, device_id: str
    ) -> Literal["on", "off", "unreachable"]:
        state = self._states.get(device_id, "unreachable")
        logger.debug("MockMerossClient: get_plug_state('%s') → '%s'", device_id, state)
        return state

    async def set_plug_state(
        self, device_id: str, target: Literal["on", "off"]
    ) -> bool:
        logger.info(
            "MockMerossClient [DRY-RUN]: would set device '%s' to '%s'",
            device_id,
            target,
        )
        # Update in-memory state so subsequent reads reflect the change
        self._states[device_id] = target
        return True
