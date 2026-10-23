"""Web server: the phone UI plus a small JSON API and a live event stream."""

import asyncio
import json
import logging
import time
from typing import Any

from aiohttp import web

from . import config
from .keys import fetch_and_verify
from .robot import ACTIONS, FANS, MODES, WATERS, RobotLink, SimRobot, read_frames
from .store import Store

_LOG = logging.getLogger("app")


class App:
    def __init__(self, sim: bool) -> None:
        self.store = Store(config.DB_FILE if not sim else config.DATA / "sim.db")
        self.prefs = config.load_prefs()
        self.subscribers: set[asyncio.Queue] = set()
        self.robot = (SimRobot if sim else RobotLink)(self._on_change)
        self._last_error = None
        self._was_online = None

    def _on_change(self, state: dict[str, Any]) -> None:
        self.store.feed(state)
        if state.get("online") != self._was_online and self._was_online is not None:
            self.store.event("online" if state.get("online") else "offline", state.get("ip") or "")
        self._was_online = state.get("online")
        err = state.get("error_desc")
        if err and err != "no" and err != self._last_error:
            self.store.event("error", f"{state.get('error_type')}:{err}")
        self._last_error = err
        payload = json.dumps(self.snapshot())
        for q in list(self.subscribers):
            if q.full():
                q.get_nowait()
            q.put_nowait(payload)

    def snapshot(self) -> dict[str, Any]:
        return {"state": self.robot.state, "prefs": self.prefs, "run_id": self.store.run_id, "now": time.time()}

    # --- handlers ---

    async def index(self, _req: web.Request) -> web.StreamResponse:
        return web.FileResponse(config.WEB / "index.html")

    async def get_state(self, _req: web.Request) -> web.Response:
        return web.json_response(self.snapshot())

    async def post_command(self, req: web.Request) -> web.Response:
        body = await req.json()
        action = body.get("action")
        if action not in ACTIONS:
            return web.json_response({"error": "unknown action"}, status=400)
        try:
            await self.robot.command(action, self.prefs)
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            return web.json_response({"error": str(e)}, status=409)
        self.store.event("command", action)
        return web.json_response({"ok": True})

    async def post_prefs(self, req: web.Request) -> web.Response:
        body = await req.json()
        allowed = {"mode": MODES, "fan": FANS, "water": WATERS}
        for k, options in allowed.items():
            if body.get(k) in options:
                self.prefs[k] = body[k]
        config.save_prefs(self.prefs)
        return web.json_response(self.prefs)

    async def get_history(self, _req: web.Request) -> web.Response:
        return web.json_response({
            "runs": self.store.runs(),
            "events": self.store.events(),
            "consumables": self.store.consumables(),
        })

    async def get_run(self, req: web.Request) -> web.Response:
        return web.json_response(self.store.run_samples(int(req.match_info["id"])))

    async def post_consumable_reset(self, req: web.Request) -> web.Response:
        self.store.reset_consumable(req.match_info["name"])
        return web.json_response(self.store.consumables())

    async def post_setup(self, req: web.Request) -> web.Response:
        body = await req.json()
        email, password = (body.get("email") or "").strip(), body.get("password") or ""
        if not email or not password:
            return web.json_response({"ok": False, "errors": {"form": "email and password required"}})
        result = await fetch_and_verify(self.robot, email, password)
        self.store.event("setup", "ok" if result["ok"] else "failed")
        return web.json_response(result)

    async def post_raw(self, req: web.Request) -> web.Response:
        """Protocol exploration: {"type": 3, "body": "3201"} sends one raw frame body."""
        body = await req.json()
        try:
            self.robot.send_raw(int(body["type"]), bytes.fromhex(body["body"]))
        except Exception as e:  # noqa: BLE001 - surfaced to the caller
            return web.json_response({"error": str(e)}, status=409)
        self.store.event("raw", f"{body['type']}:{body['body']}")
        return web.json_response({"ok": True})

    async def get_frames(self, req: web.Request) -> web.Response:
        since = float(req.query.get("since", 0))
        return web.json_response(read_frames(since, int(req.query.get("limit", 200))))

    async def events(self, req: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await resp.prepare(req)
        q: asyncio.Queue = asyncio.Queue(maxsize=5)
        self.subscribers.add(q)
        try:
            await resp.write(f"data: {json.dumps(self.snapshot())}\n\n".encode())
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=20)
                    await resp.write(f"data: {msg}\n\n".encode())
                except TimeoutError:
                    await resp.write(b": ping\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self.subscribers.discard(q)
        return resp

    def build(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self.index)
        app.router.add_get("/api/state", self.get_state)
        app.router.add_post("/api/command", self.post_command)
        app.router.add_post("/api/prefs", self.post_prefs)
        app.router.add_get("/api/history", self.get_history)
        app.router.add_get("/api/runs/{id}", self.get_run)
        app.router.add_post("/api/consumables/{name}/reset", self.post_consumable_reset)
        app.router.add_post("/api/setup", self.post_setup)
        app.router.add_get("/api/events", self.events)
        app.router.add_post("/api/raw", self.post_raw)
        app.router.add_get("/api/frames", self.get_frames)
        app.router.add_static("/static/", config.WEB)

        async def on_startup(_app: web.Application) -> None:
            await self.robot.start()

        async def on_cleanup(_app: web.Application) -> None:
            await self.robot.stop()

        app.on_startup.append(on_startup)
        app.on_cleanup.append(on_cleanup)
        return app
