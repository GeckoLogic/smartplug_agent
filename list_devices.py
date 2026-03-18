"""
list_devices.py - List all Meross devices and their IDs.
Run this to find the device_id values to put in config.yaml.

Usage:
    venv\Scripts\python list_devices.py
"""

import asyncio
import sys


async def _list():
    from meross_iot.http_api import MerossHttpClient
    from meross_iot.manager import MerossManager

    email = input("Meross email: ").strip()
    password = input("Meross password: ").strip()

    print("\nConnecting…")
    http_client = await MerossHttpClient.async_from_user_password(
        api_base_url="https://iotx-us.meross.com",
        email=email,
        password=password,
    )
    manager = MerossManager(http_client=http_client)
    await manager.async_init()
    await manager.async_device_discovery()

    devices = manager.find_devices()
    if not devices:
        print("No devices found.")
    else:
        print(f"\n{'Name':<30} {'Device ID':<36} {'Type'}")
        print("-" * 75)
        for d in devices:
            print(f"{d.name:<30} {d.uuid:<36} {d.type}")

    manager.close()
    await http_client.async_logout()


if __name__ == "__main__":
    asyncio.run(_list())
