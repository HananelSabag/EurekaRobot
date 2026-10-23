"""Send one appliance frame to the robot through Midea's cloud pass-through (transparent send).

The same 0xAA frame that works on the LAN, wrapped the way midea-beautiful-air does for the cloud.
Usage (project folder):  .venv\\Scripts\\python -m tools.cloud_passthrough <query|start|dock|stop>
"""

import hashlib
import sys
from datetime import datetime
from secrets import token_hex

from midea_beautiful import connect_to_cloud
from midea_beautiful.cloud import _decode_from_csv, _encode_as_csv
from midealocal.security import CloudSecurity

from server import config
from server.cloud import saved_account

SIGN_KEY = b"xhdiwjnchekd4d512chdjx5d8e4c394D2D7S"

# Frames copied from data/frames.jsonl: these exact bytes worked over the LAN on 2026-10-23.
FRAMES = {
    "query": "aa0cb800000000000103320105",
    "start": None,  # filled from the log below (arc / normal / low)
    "dock": None,
    "stop": None,
}


def frame_from_log(body_hex: str) -> str:
    import json
    for line in reversed((config.DATA / "frames.jsonl").read_text(encoding="utf-8").splitlines()):
        f = json.loads(line)
        if f["dir"] == "out" and f["body"] == body_hex:
            return f["frame"]
    raise SystemExit(f"no logged frame with body {body_hex}")


def cloud_packet(appliance_id: int, frame: bytes) -> bytes:
    now = datetime.now()
    packet = bytearray(b"\x5a\x5a\x01\x11\x00\x00\x20\x00" + bytes(4))
    packet += bytes([now.microsecond // 10000, now.second, now.minute, now.hour,
                     now.day, now.month, now.year % 100, now.year // 100])
    packet += appliance_id.to_bytes(8, "little") + bytes(12)
    packet += frame  # the cloud channel carries the frame unencrypted
    packet[4:6] = (len(packet) + 16).to_bytes(2, "little")
    return bytes(packet + hashlib.md5(packet + SIGN_KEY).digest())


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "query"
    bodies = {"start": "2202020202014600000000000000", "dock": "22010000", "stop": "22030000"}
    frame_hex = FRAMES["query"] if action == "query" else frame_from_log(bodies[action])
    account = saved_account()
    if not account:
        raise SystemExit("no saved MSmartHome account (run tools.cloud_login)")
    # Reuse midea-local's login device id: each new id takes one of the account's few login slots.
    cloud = connect_to_cloud(*account, appname="MSmartHome", device_id=CloudSecurity.get_deviceid(account[0]))
    appliance_id = config.load_robot()["device_id"]
    print(f"-> {action}: frame {frame_hex}")
    # MSmartHome's v5 API names the field applianceCode (midea-beautiful-air sends the legacy applianceId).
    order = cloud._security.aes_encrypt_string(_encode_as_csv(cloud_packet(appliance_id, bytes.fromhex(frame_hex))))
    # Passing reqId keeps midea-beautiful-air from adding app-version fields this endpoint rejects.
    response = cloud.api_request("/v1/appliance/transparent/send",
                                 {"order": order, "funId": "0000", "applianceCode": str(appliance_id),
                                  "reqId": token_hex(16), "uid": cloud._uid or ""})
    print("<- response keys:", sorted(response) if isinstance(response, dict) else type(response).__name__)
    if isinstance(response, dict) and response.get("reply"):
        reply = _decode_from_csv(cloud._security.aes_decrypt_string(response["reply"]))
        print("<- reply", reply.hex())


main()
