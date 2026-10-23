"""Paths and the saved robot config.

data/robot.json holds the robot's LAN token/key once setup succeeds. It is a secret
for this one robot, so data/ stays out of git.
"""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEB = ROOT / "web"
ROBOT_FILE = DATA / "robot.json"
PREFS_FILE = DATA / "prefs.json"
DB_FILE = DATA / "history.db"

# What LAN discovery reported for "Sabag Robot" (Eureka NER 450) on 2026-10-23.
# The IP can change; the link re-finds the robot by device id.
DEFAULT_ROBOT: dict[str, Any] = {
    "device_id": 123456789012345,
    "type": 0xB8,
    "ip_address": "192.168.1.50",
    "port": 6444,
    "model": "320VR900",
    "sn": "0000B854U320VR900000000000000000",
    "protocol": 3,
    "mac": "8076c2000001",
}

DEFAULT_PREFS: dict[str, Any] = {"mode": "arc", "fan": "normal", "water": "low"}


def _read(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        return {**default, **json.loads(path.read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return dict(default)


def _write(path: Path, data: dict[str, Any]) -> None:
    DATA.mkdir(exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_robot() -> dict[str, Any]:
    return _read(ROBOT_FILE, DEFAULT_ROBOT)


def save_robot(cfg: dict[str, Any]) -> None:
    _write(ROBOT_FILE, cfg)


def has_key(cfg: dict[str, Any]) -> bool:
    return bool(cfg.get("token") and cfg.get("key"))


def load_prefs() -> dict[str, Any]:
    prefs = _read(PREFS_FILE, DEFAULT_PREFS)
    if prefs["mode"] == "auto":  # saved before we learned this model rejects "auto"
        prefs["mode"] = "arc"
    return prefs


def save_prefs(prefs: dict[str, Any]) -> None:
    _write(PREFS_FILE, prefs)
