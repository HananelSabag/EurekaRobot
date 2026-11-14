"""Talking to the robot: the real LAN link (midea-local, Midea V3 on port 6444) and a simulator.

Both expose the same small surface: `state`, `start()`, `stop()`, `command()`, and a
listener callback that fires whenever the state changes.

Protocol caveat (B8 v1): every "set" frame carries work=0x02, so sending suction or
water settings to a docked robot would start a clean. Settings therefore travel only
inside the start command, or while the robot is already cleaning.
"""

import asyncio
import ipaddress
import json
import logging
import random
import socket
import time
from collections.abc import Callable
from typing import Any

from midealocal.cloud import DEFAULT_KEYS
from midealocal.devices import device_selector
from midealocal.devices.b8 import DeviceAttributes as A
from midealocal.devices.b8.message import B8CleanMode, B8FanLevel, B8WaterLevel, B8WorkMode, MessageSet
from midealocal.discover import BROADCAST_MSG, _parse_discover_response
from midealocal.message import MessageType

from . import config
from .cloud import CloudControl, action_to_control

_LOG = logging.getLogger("robot")

# "arc" is this model's whole-home zigzag (what the official app sends); it rejects "auto" (0x08).
# edge and screw (spiral spot) are not verified on the robot yet.
MODES = ("arc", "edge", "screw")
FANS = ("soft", "normal", "high")
WATERS = ("low", "normal", "high")
ACTIONS = ("start", "pause", "stop", "dock")
DOCK_STATES = {"charge", "charging_on_dock", "charge_finish", "charging_with_wire"}

Listener = Callable[[dict[str, Any]], None]


FRAMES_FILE = config.DATA / "frames.jsonl"


def log_frame(direction: str, frame: bytes) -> None:
    """Append one 0xAA appliance frame to data/frames.jsonl (type at byte 9, body = bytes 10..-1)."""
    frame = bytes(frame)
    entry = {"ts": round(time.time(), 3), "dir": direction,
             "type": frame[9] if len(frame) > 9 else None,
             "body": frame[10:-1].hex() if len(frame) > 11 else "", "frame": frame.hex()}
    with FRAMES_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_frames(since: float = 0, limit: int = 200) -> list[dict[str, Any]]:
    try:
        lines = FRAMES_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = [json.loads(line) for line in lines[-2000:]]
    return [f for f in out if f["ts"] > since][-limit:]


def blank_state() -> dict[str, Any]:
    return {
        "online": False, "link": "starting", "ip": None, "status": None, "battery": None,
        "area": None, "work_time": None, "mode": None, "fan": None, "water": None,
        "mop": None, "error_type": None, "error_desc": None, "updated": None,
    }


def state_from_attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": attrs.get(A.work_status),
        "battery": attrs.get(A.battery_percent),
        "area": attrs.get(A.area),
        "work_time": attrs.get(A.work_time),
        "mode": attrs.get(A.clean_mode),
        "fan": attrs.get(A.fan_level),
        "water": attrs.get(A.water_level),
        "mop": attrs.get(A.mop),
        "error_type": attrs.get(A.error_type),
        "error_desc": attrs.get(A.error_desc),
    }


async def find_robot(device_id: int, near_ip: str, mac: str | None = None,
                     timeout: float = 4.0) -> dict[str, Any] | None:
    """Unicast Midea discovery to every host in near_ip's /24 and return this robot's entry.

    Matches on device id or MAC (the id can change when the robot is paired again). With
    neither known (first setup), the first B8 robot vacuum that answers is the one.
    Unicast rather than broadcast: Windows' firewall drops replies to a broadcast.
    """
    loop = asyncio.get_running_loop()
    net = ipaddress.ip_network(f"{near_ip}/24", strict=False)
    found: dict[int, dict[str, Any]] = {}
    want_mac = (mac or "").lower().replace(":", "")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setblocking(False)
        for host in net.hosts():
            for port in (6445, 20086):
                try:
                    await loop.sock_sendto(sock, BROADCAST_MSG, (str(host), port))
                except OSError:
                    pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                dev_id, dev = await _parse_discover_response(loop, sock, found)
            except ConnectionResetError:
                # Windows reports another host's "port unreachable" on the next recv; skip it.
                continue
            except (TimeoutError, OSError, ValueError, UnicodeDecodeError):
                break
            if dev:
                found[dev_id] = dev
                dev_mac = (dev.get("mac") or "").lower().replace(":", "")
                first_setup = not device_id and not want_mac and dev.get("type") == 0xB8
                if dev_id == device_id or (want_mac and dev_mac == want_mac) or first_setup:
                    return dev
    return None


class RobotLink:
    """Keeps a midea-local device connected and turns its updates into app state."""

    def __init__(self, on_change: Listener) -> None:
        self.cfg = config.load_robot()
        self.state = blank_state()
        self.state["ip"] = self.cfg["ip_address"]
        self._on_change = on_change
        self._dev = None
        self._watchdog: asyncio.Task | None = None
        self._last_ok = 0.0
        self.cloud = CloudControl(self.cfg["device_id"])

    def _set(self, **changes: Any) -> None:
        self.state.update(changes, updated=time.time())
        self._on_change(self.state)

    def _make_device(self, token: str, key: str):
        c = self.cfg
        return device_selector(
            name="robot", device_id=c["device_id"], device_type=c["type"],
            ip_address=c["ip_address"], port=c["port"], token=token, key=key,
            device_protocol=c["protocol"], model=c["model"], subtype=0, customize="",
            mac=c.get("mac"), serial_number=c.get("sn"),
        )

    async def start(self) -> None:
        self._watchdog = asyncio.create_task(self._watch())

    async def stop(self) -> None:
        if self._watchdog:
            self._watchdog.cancel()
        if self._dev:
            await self._dev.close()
        await self.cloud.close()

    async def try_key(self, token: str, key: str) -> dict[str, Any] | None:
        """Connect with a candidate key and run one read-only status query."""
        dev = self._make_device(token, key)
        try:
            if await dev.connect():
                await dev.refresh_status(True)
                return dict(dev.attributes)
        except Exception as e:  # noqa: BLE001 - any failure means "not this key"
            _LOG.info("key rejected: %s", type(e).__name__)
        finally:
            try:
                await dev.close_socket()
            except Exception:  # noqa: BLE001
                pass
        return None

    async def adopt_key(self, token: str, key: str) -> None:
        self.cfg.update(token=token, key=key)
        config.save_robot(self.cfg)
        await self._open_device()

    async def _open_device(self) -> None:
        if self._dev:
            await self._dev.close()
        self._dev = self._make_device(self.cfg["token"], self.cfg["key"])
        self._log_frames(self._dev)
        self._dev.register_update(self._on_device_update)
        self._dev.set_refresh_interval(15)
        await self._dev.open()
        self._set(link="connecting")

    @staticmethod
    def _log_frames(dev) -> None:
        """Record every frame both ways, including ones midea-local doesn't parse."""
        process, build_send = dev.process_message, dev.build_send

        def logged_process(msg: bytes) -> dict[str, Any]:
            log_frame("in", msg)
            return process(msg)

        def logged_send(cmd) -> None:
            log_frame("out", cmd.serialize())
            build_send(cmd)

        dev.process_message, dev.build_send = logged_process, logged_send

    def send_raw(self, msg_type: int, body: bytes) -> None:
        """Send one raw appliance frame body (body[0] is the body type). For protocol exploration."""
        if self._dev is None or not self.state["online"]:
            raise RuntimeError("robot not connected")
        self._dev.send_command(MessageType(msg_type), bytearray(body))

    def _on_device_update(self, status: dict[str, Any]) -> None:
        if "available" in status:
            self._set(online=bool(status["available"]), link="ok" if status["available"] else "lost")
        if self._dev is not None and any(k != "available" for k in status):
            self._last_ok = time.time()
            self._set(online=True, link="ok", **state_from_attributes(self._dev.attributes))

    async def _locate(self) -> bool:
        dev = await find_robot(self.cfg["device_id"], self.cfg["ip_address"], self.cfg.get("mac"))
        if not dev:
            return False
        if dev["ip_address"] != self.cfg["ip_address"]:
            _LOG.info("robot moved to %s", dev["ip_address"])
            self.cfg["ip_address"] = dev["ip_address"]
            config.save_robot(self.cfg)
            if self._dev:
                await self._dev.set_ip_address(dev["ip_address"])
        self.state["ip"] = dev["ip_address"]
        return True

    async def _watch(self) -> None:
        tried_default = False
        while True:
            try:
                if not config.has_key(self.cfg):
                    seen = await self._locate()
                    self._set(online=False, link="no_key" if seen else "no_key_offline")
                    if seen and not tried_default:
                        tried_default = True
                        for k in DEFAULT_KEYS.values():
                            if await self.try_key(k["token"], k["key"]) is not None:
                                _LOG.info("library default key works")
                                await self.adopt_key(k["token"], k["key"])
                                break
                elif self._dev is None:
                    await self._open_device()
                elif not self.state["online"] and time.time() - self._last_ok > 90:
                    found = await self._locate()
                    self._set(link="lost" if found else "offline")
            except Exception:
                _LOG.exception("watchdog")
            await asyncio.sleep(30)

    async def command(self, action: str, prefs: dict[str, Any]) -> None:
        if self._dev is None or not self.state["online"]:
            if CloudControl.available():
                await self.cloud.control(action_to_control(action, prefs))
                return
            raise RuntimeError("robot not connected")
        dev = self._dev
        if action == "start":
            # One set frame carries mode, suction and water together (and starts the clean).
            msg = MessageSet(dev._message_protocol_version)
            msg.clean_mode = B8CleanMode[prefs["mode"].upper()]
            msg.fan_level = B8FanLevel[prefs["fan"].upper()]
            msg.water_level = B8WaterLevel[prefs["water"].upper()]
            msg.voice_volume = dev.attributes.get(A.voice_volume) or 0
            dev.build_send(msg)
        elif action == "pause":
            dev.set_work_mode(B8WorkMode.PAUSE)
        elif action == "stop":
            dev.set_work_mode(B8WorkMode.STOP)
        elif action == "dock":
            # The charge command toggles: sent while already heading home, it stops the robot.
            if self.state["status"] in DOCK_STATES:
                return
            dev.set_work_mode(B8WorkMode.CHARGE)
        else:
            raise ValueError(action)


class SimRobot:
    """A pretend robot for building and testing the UI without the real one."""

    def __init__(self, on_change: Listener) -> None:
        self.state = blank_state()
        self.state.update(online=True, link="ok", ip="sim", status="charge_finish", battery=100,
                          area=0, work_time=0, mode="arc", fan="normal", water="low",
                          mop="off", error_type="no", error_desc="no")
        self._on_change = on_change
        self._task: asyncio.Task | None = None
        self._returning = False

    async def start(self) -> None:
        self._task = asyncio.create_task(self._tick())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def try_key(self, token: str, key: str) -> None:
        return None

    async def adopt_key(self, token: str, key: str) -> None:
        return None

    def send_raw(self, msg_type: int, body: bytes) -> None:
        raise RuntimeError("raw frames need the real robot")

    def _set(self, **changes: Any) -> None:
        self.state.update(changes, updated=time.time())
        self._on_change(self.state)

    async def command(self, action: str, prefs: dict[str, Any]) -> None:
        if action == "start":
            self._returning = False
            fresh = self.state["status"] not in ("pause",)
            self._set(status="work", mode=prefs["mode"], fan=prefs["fan"], water=prefs["water"],
                      **({"area": 0, "work_time": 0} if fresh else {}))
        elif action == "pause":
            self._set(status="pause")
        elif action == "stop":
            self._set(status="stop")
        elif action == "dock":
            self._returning = True
            self._set(status="charge")

    async def _tick(self) -> None:
        sub = 0
        while True:
            await asyncio.sleep(2)  # 1 tick = 1 simulated minute
            s = self.state
            if s["status"] == "work":
                sub += 1
                area = s["area"] + random.choice((0, 1, 1, 2))
                self._set(work_time=s["work_time"] + 1, area=area, battery=max(5, s["battery"] - 1))
                if s["battery"] <= 15 or s["work_time"] >= 40:
                    self._returning = True
                    self._set(status="charge")
            elif s["status"] == "charge" and self._returning:
                self._returning = False
                self._set(status="charging_on_dock")
            elif s["status"] in ("charging_on_dock",):
                b = min(100, s["battery"] + 3)
                self._set(battery=b, status="charge_finish" if b == 100 else "charging_on_dock")
