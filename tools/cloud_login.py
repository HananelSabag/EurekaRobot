"""Save the MSmartHome account in Windows Credential Manager and check it can see the robot.

Run from the project folder:  .venv\\Scripts\\python -m tools.cloud_login
You type the email and password; they go straight to the Windows credential vault.
"""

import asyncio
import getpass

from server import config
from server.cloud import CloudControl, save_account


async def main() -> None:
    email = input("MSmartHome email: ").strip()
    password = getpass.getpass("MSmartHome password (hidden): ")
    save_account(email, password)
    del password
    print("Saved in Windows Credential Manager. Checking the robot through the cloud...")
    cloud = CloudControl(config.load_robot()["device_id"])
    try:
        status = await cloud.query()
        if status:
            print(f"OK: cloud sees the robot - work_status={status.get('work_status')}, "
                  f"battery={status.get('battery_percent')}%")
        else:
            print("Logged in, but the cloud returned no status for the robot.")
    except Exception as e:  # noqa: BLE001 - shown to the user as is
        print(f"Cloud check failed: {e}")
    finally:
        await cloud.close()


asyncio.run(main())
