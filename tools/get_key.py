"""One-time setup after pairing in MSmartHome: find the robot on the LAN, log in, save its LAN key.

Run from the project folder:  .venv\\Scripts\\python -m tools.get_key
You type the email and password; the password is used for this login only and never saved.
"""

import asyncio
import getpass

from server import config
from server.keys import fetch_and_verify
from server.robot import RobotLink, find_robot


async def main() -> None:
    print("Looking for the robot on the home network...")
    cfg = config.load_robot()
    dev = None
    for _ in range(3):
        dev = await find_robot(cfg["device_id"], cfg["ip_address"], cfg.get("mac"))
        if dev:
            break
    if not dev:
        print("The robot did not answer on 192.168.1.x. Is it paired in MSmartHome and docked?")
        return
    print(f"Found it at {dev['ip_address']} (device id {dev['device_id']}, protocol {dev['protocol']}).")
    cfg.update(device_id=dev["device_id"], ip_address=dev["ip_address"], port=dev["port"],
               protocol=dev["protocol"], model=dev["model"], sn=dev["sn"], mac=dev["mac"])
    cfg.pop("token", None)
    cfg.pop("key", None)
    config.save_robot(cfg)

    email = input("MSmartHome email: ").strip()
    password = getpass.getpass("MSmartHome password (hidden): ")
    link = RobotLink(lambda _state: None)
    result = await fetch_and_verify(link, email, password)
    del password
    if result["ok"]:
        print(f"Key saved (from the {result['cloud']} cloud). The robot answers locally now.")
    else:
        print("Could not get a working key:")
        for cloud, err in result["errors"].items():
            print(f"  {cloud}: {err}")
    await link.stop()


asyncio.run(main())
