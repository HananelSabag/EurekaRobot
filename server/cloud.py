"""Robot commands through Midea's MSmartHome cloud, which translates them for this exact model.

Status stays local (robot.py); only start / stop / dock (with suction and water) go through here.
Request shapes follow github.com/ndgmedia/homey-midea-vacuum (MIT): `control` must always carry
`work_status`, and the robot's current cloud status is sent alongside it.

The account lives in Windows Credential Manager (saved by tools/cloud_login.py), never in a file.
"""

import logging
from typing import Any

import aiohttp
import keyring
from midealocal.cloud import get_midea_cloud

SERVICE = "EurekaRobot-MSmartHome"
_EMAIL_KEY = "__email__"
_LOG = logging.getLogger("cloud")

# Fields the status echo must not carry back (per the Homey implementation).
_STATUS_DROP = {"sn8", "version", "query_type"}


def saved_account() -> tuple[str, str] | None:
    email = keyring.get_password(SERVICE, _EMAIL_KEY)
    password = keyring.get_password(SERVICE, email) if email else None
    return (email, password) if email and password else None


def save_account(email: str, password: str) -> None:
    keyring.set_password(SERVICE, _EMAIL_KEY, email)
    keyring.set_password(SERVICE, email, password)


class CloudControl:
    def __init__(self, appliance_id: int) -> None:
        self.appliance_id = appliance_id
        self._session: aiohttp.ClientSession | None = None
        self._cloud = None

    @staticmethod
    def available() -> bool:
        return saved_account() is not None

    async def _login(self) -> None:
        account = saved_account()
        if not account:
            raise RuntimeError("no MSmartHome account saved (run tools.cloud_login)")
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        self._cloud = get_midea_cloud("SmartHome", self._session, *account)
        if not await self._cloud.login():
            self._cloud = None
            raise RuntimeError("MSmartHome login failed")

    async def _request(self, endpoint: str, command: dict[str, Any]) -> dict[str, Any] | None:
        for attempt in (1, 2):
            if self._cloud is None:
                await self._login()
            data = self._cloud._make_general_data()
            data.update(applianceCode=str(self.appliance_id), command=command)
            try:
                return await self._cloud._api_request(endpoint, data, raise_for_error=True)
            except Exception as e:  # noqa: BLE001 - classified by the cloud's error code
                text = str(e)
                if "1306" in text:  # async reply timed out; the command was most likely delivered
                    return None
                if attempt == 1 and ("40002" in text or "login" in text.lower()):
                    _LOG.info("cloud session expired, logging in again")
                    self._cloud = None
                    continue
                raise
        return None

    async def query(self) -> dict[str, Any] | None:
        return await self._request("/v1/device/status/lua/get", {"query": {}})

    async def control(self, control: dict[str, Any]) -> dict[str, Any] | None:
        status = await self.query() or {}
        status = {k: v for k, v in status.items() if k not in _STATUS_DROP}
        return await self._request("/v1/device/lua/control", {"control": control, "status": status})

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


def action_to_control(action: str, prefs: dict[str, Any]) -> dict[str, Any]:
    if action == "start":
        return {"work_status": "work", "work_mode": prefs["mode"],
                "fan_level": prefs["fan"], "water_level": prefs["water"]}
    if action in ("pause", "stop"):
        return {"work_status": "stop"}
    if action == "dock":
        return {"work_status": "charge"}
    raise ValueError(action)
