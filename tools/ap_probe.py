"""Read-only look at the robot while the PC sits on the robot's own AP (robot_b8_xxxx).

Scans a few ports on the AP address, runs Midea discovery, and tries the library's
default key with a single status query. Sends no commands. Usage: ap_probe.py <robot_ip> <out.json>
"""

import asyncio
import json
import socket
import sys
import time

from midealocal.cloud import DEFAULT_KEYS
from midealocal.devices import device_selector
from midealocal.discover import BROADCAST_MSG, _parse_discover_response

ip, out_path = sys.argv[1], sys.argv[2]
result: dict = {"ip": ip, "time": time.strftime("%Y-%m-%d %H:%M:%S")}


async def port_open(port: int) -> bool:
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(ip, port), 2)
        w.close()
        return True
    except Exception:  # noqa: BLE001
        return False


async def discover() -> dict | None:
    loop = asyncio.get_running_loop()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setblocking(False)
        for target in (ip, "255.255.255.255"):
            for port in (6445, 20086):
                try:
                    await loop.sock_sendto(sock, BROADCAST_MSG, (target, port))
                except OSError:
                    pass
        try:
            _, dev = await _parse_discover_response(loop, sock, {})
            return dev
        except Exception as e:  # noqa: BLE001
            result["discover_error"] = f"{type(e).__name__}: {e}"
            return None


async def main() -> None:
    ports = [80, 443, 6444, 6445, 8080, 8443, 9000, 10000, 20086]
    result["open_ports"] = [p for p in ports if await port_open(p)]
    dev = await discover()
    result["discovery"] = dev
    if dev or 6444 in result["open_ports"]:
        info = dev or {"device_id": 123456789012345, "type": 0xB8, "port": 6444,
                       "protocol": 3, "model": "320VR900", "sn": "", "mac": "8076c2000001"}
        for name, k in DEFAULT_KEYS.items():
            d = device_selector(
                name="robot", device_id=info["device_id"], device_type=info["type"],
                ip_address=ip, port=info["port"], token=k["token"], key=k["key"],
                device_protocol=info["protocol"], model=info["model"], subtype=0,
                customize="", mac=info.get("mac"), serial_number=info.get("sn") or None,
            )
            try:
                ok = await asyncio.wait_for(d.connect(), 10)
                result[f"default_key_{name}_auth"] = ok
                if ok:
                    await asyncio.wait_for(d.refresh_status(True), 10)
                    result[f"default_key_{name}_status"] = dict(d.attributes)
            except Exception as e:  # noqa: BLE001
                result[f"default_key_{name}_error"] = f"{type(e).__name__}: {e}"
            finally:
                try:
                    await d.close_socket()
                except Exception:  # noqa: BLE001
                    pass


try:
    asyncio.run(asyncio.wait_for(main(), 60))
except Exception as e:  # noqa: BLE001
    result["fatal"] = f"{type(e).__name__}: {e}"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f, default=str, indent=1, ensure_ascii=False)
print(json.dumps(result, default=str, indent=1, ensure_ascii=False))
