"""One-time fetch of the robot's LAN token/key from the Midea cloud account that owns it.

The password is used for this login only and is never stored.
"""

import logging
from typing import Any

import aiohttp
from midealocal.cloud import get_midea_cloud

from .robot import RobotLink

_LOG = logging.getLogger("keys")

# Overseas Midea clouds an Eureka/MSmartHome account may live in, most likely first.
CLOUDS = ("SmartHome", "NetHome Plus", "Midea Air")


async def fetch_and_verify(link: RobotLink, email: str, password: str) -> dict[str, Any]:
    """Try each cloud; return {"ok": True, "cloud": ...} once a key passes a read-only query."""
    errors: dict[str, str] = {}
    async with aiohttp.ClientSession() as session:
        for name in CLOUDS:
            cloud = get_midea_cloud(name, session, email, password)
            try:
                if not await cloud.login():
                    errors[name] = "login failed"
                    continue
                keys = await cloud.get_cloud_keys(link.cfg["device_id"])
            except Exception as e:  # noqa: BLE001 - report every cloud's failure to the user
                errors[name] = f"{type(e).__name__}: {e}"
                continue
            if not keys:
                errors[name] = "logged in, but this account does not own the robot"
                continue
            for k in keys.values():
                if await link.try_key(k["token"], k["key"]) is not None:
                    await link.adopt_key(k["token"], k["key"])
                    _LOG.info("key adopted from %s", name)
                    return {"ok": True, "cloud": name}
            errors[name] = "got keys, but the robot rejected them (is it online?)"
    return {"ok": False, "errors": errors}
