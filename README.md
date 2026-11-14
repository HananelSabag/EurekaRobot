# EurekaRobot

**A local control app for a Eureka NER 450 robot vacuum-mop (a Midea B8 device), built to replace the vendor app.** A Python server talks to the robot over the home network and serves a Hebrew mobile web app; a small Windows window runs it.

> **Prototype, shelved (October 2026).** Local control works. The rest is listed below as proven, started or not done.

## Status

- **Works:** live status (state, exact battery %, mop, faults) and start, stop and return to dock over the LAN, with no cloud. Run history in SQLite and parts tracking. A mobile web app (Hebrew, RTL) served by the same server, and a Windows window that starts the server and stops it on close.
- **Proven, not wired into the app:** the MSmartHome cloud's `transparent/send` channel carries the same command frames, so control away from home is possible.
- **Started:** `android/` holds a Kotlin port of the LAN protocol (0xAA frames, 5A5A packets, the V3 session) with byte-exact test vectors generated from the Python libraries. It has not been compiled yet.
- **Not done:** maps. This model navigates with a gyro, not a LiDAR, so it doesn't know where it is and can't be sent to a room.

## What I learned about this model

- "Whole home" cleaning is `arc` (0x02). The robot silently rejects `auto` (0x08), which is why "start" first did nothing.
- Return to dock is a toggle: sent while the robot is already heading home, it stops. The app sends it only when the robot isn't on its way.
- The battery reads about 50% on the dock and 20% off it, because of the charging voltage.
- The LAN key comes from the cloud account the robot is paired with. Eureka-app accounts aren't valid on the MSmartHome cloud, so the robot is paired once in the MSmartHome app; pairing it elsewhere again changes the key.
- MSmartHome limits active logins per account (error 65027), so the client always logs in with the same device id.
- The cloud's Lua `control` API replies OK but doesn't move this model; the transparent channel does.

## How it's built

| | |
|---|---|
| Server | Python, aiohttp, midea-local (Midea V3 over TCP 6444), SQLite |
| Cloud | MSmartHome login (midea-beautiful-air), transparent pass-through of the same frames |
| Web app | Plain HTML, CSS and JavaScript: a robot hero with a battery ring, cleaning modes, suction and water levels, history and maintenance tabs |
| Windows | C# WinForms + WebView2 (.NET 10) |
| Android | Kotlin protocol port with test vectors (unfinished) |

```
server/     robot link (discovery, V3 session, commands), cloud client, history store, HTTP API
web/        the mobile web app
tools/      one-time setup (get_key, cloud_login), protocol probes, test-vector generator
launcher/   the Windows window
android/    the Kotlin protocol port
```

## Run it

Windows, Python 3.12+, and the robot paired in the MSmartHome app.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m tools.get_key       # once: finds the robot on 192.168.1.x, logs in, saves its LAN key
.venv\Scripts\python -m tools.cloud_login   # once: keeps the MSmartHome account in Windows Credential Manager
.venv\Scripts\python -m server --host 0.0.0.0
```

Then open `http://<this PC's IP>:8765` on a phone. On another subnet, set `ip_address` in `data/robot.json` to any address on it before `get_key`. Everything in `data/` (the LAN key, history) stays out of git.

The Windows window: `cd launcher` and `dotnet publish -c Release -o publish`.

## License

[MIT](LICENSE) © 2026 Hananel Sabag
