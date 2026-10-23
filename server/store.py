"""SQLite history: every cleaning run, status samples while it runs, and notable events.

The robot keeps no history of its own and the official app shows only the last run,
so everything the user can look back on lives here.
"""

import sqlite3
import time
from pathlib import Path
from typing import Any

# Statuses during which a run is still going (returning to the dock included).
RUN_ACTIVE = {"work", "pause", "relocate", "charge", "charge_pause"}
# Statuses that close a run.
RUN_ENDING = {"charging_on_dock", "charge_finish", "charging_with_wire", "stop", "sleep", "error"}
# A run with no news for this long is closed (robot went offline mid-run).
STALE_RUN_SECONDS = 15 * 60
SAMPLE_EVERY_SECONDS = 60
# Runs shorter than this with nothing cleaned are dropped when they end.
BLIP_SECONDS = 120

# Rated lifetimes in hours of cleaning, typical for this class of robot.
CONSUMABLES = {"main_brush": 300, "side_brush": 200, "filter": 150, "mop": 100}

SCHEMA = """
create table if not exists runs (
  id integer primary key,
  start real not null,
  end real,
  mode text, fan text, water text,
  minutes integer default 0,
  area integer default 0,
  battery_start integer,
  battery_end integer,
  end_status text
);
create table if not exists samples (
  ts real not null, run_id integer, status text, battery integer,
  area integer, work_time integer
);
create table if not exists events (ts real not null, kind text not null, detail text);
create table if not exists consumables (name text primary key, reset_ts real not null);
create index if not exists samples_run on samples(run_id);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        now = time.time()
        for name in CONSUMABLES:
            self.db.execute("insert or ignore into consumables values (?, ?)", (name, now))
        self.db.commit()
        self.run_id: int | None = self._open_run_id()
        self._last_sample = 0.0
        self._last_seen = time.time()

    def _open_run_id(self) -> int | None:
        row = self.db.execute("select id from runs where end is null order by id desc limit 1").fetchone()
        return row["id"] if row else None

    def event(self, kind: str, detail: str = "") -> None:
        self.db.execute("insert into events values (?, ?, ?)", (time.time(), kind, detail))
        self.db.commit()

    def feed(self, state: dict[str, Any], now: float | None = None) -> None:
        """Advance run tracking with the latest robot state."""
        now = now or time.time()
        status = state.get("status")
        if not state.get("online"):
            if self.run_id and now - self._last_seen > STALE_RUN_SECONDS:
                self._close_run(now, "offline", state)
            return
        self._last_seen = now
        if status in RUN_ACTIVE and status != "charge" and self.run_id is None:
            cur = self.db.execute(
                "insert into runs (start, mode, fan, water, battery_start) values (?, ?, ?, ?, ?)",
                (now, state.get("mode"), state.get("fan"), state.get("water"), state.get("battery")),
            )
            self.run_id = cur.lastrowid
            self.db.commit()
        if self.run_id is None:
            return
        self.db.execute(
            "update runs set minutes = max(minutes, ?), area = max(area, ?), battery_end = ? where id = ?",
            (state.get("work_time") or 0, state.get("area") or 0, state.get("battery"), self.run_id),
        )
        if now - self._last_sample >= SAMPLE_EVERY_SECONDS:
            self._last_sample = now
            self.db.execute(
                "insert into samples values (?, ?, ?, ?, ?, ?)",
                (now, self.run_id, status, state.get("battery"), state.get("area"), state.get("work_time")),
            )
        if status in RUN_ENDING:
            self._close_run(now, status, state)
        self.db.commit()

    def _close_run(self, now: float, end_status: str, state: dict[str, Any]) -> None:
        run = self.db.execute("select start, minutes, area from runs where id = ?", (self.run_id,)).fetchone()
        if run and now - run["start"] < BLIP_SECONDS and not run["minutes"] and not run["area"]:
            # A start that went nowhere (refused, or sent straight back) is not a clean worth keeping.
            self.db.execute("delete from samples where run_id = ?", (self.run_id,))
            self.db.execute("delete from runs where id = ?", (self.run_id,))
        else:
            self.db.execute(
                "update runs set end = ?, end_status = ?, battery_end = coalesce(?, battery_end) where id = ?",
                (now, end_status, state.get("battery"), self.run_id),
            )
        self.db.commit()
        self.run_id = None

    def runs(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.execute("select * from runs order by start desc limit ?", (limit,))
        return [dict(r) for r in rows]

    def run_samples(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.db.execute("select * from samples where run_id = ? order by ts", (run_id,))
        return [dict(r) for r in rows]

    def events(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.execute("select * from events order by ts desc limit ?", (limit,))
        return [dict(r) for r in rows]

    def consumables(self) -> list[dict[str, Any]]:
        out = []
        for row in self.db.execute("select * from consumables"):
            used_min = self.db.execute(
                "select coalesce(sum(minutes), 0) from runs where start >= ?", (row["reset_ts"],)
            ).fetchone()[0]
            life_h = CONSUMABLES.get(row["name"], 0)
            left = max(0.0, 1 - used_min / 60 / life_h) if life_h else 0.0
            out.append({"name": row["name"], "used_hours": round(used_min / 60, 1),
                        "life_hours": life_h, "left": round(left, 3), "reset_ts": row["reset_ts"]})
        return out

    def reset_consumable(self, name: str) -> None:
        if name in CONSUMABLES:
            self.db.execute("update consumables set reset_ts = ? where name = ?", (time.time(), name))
            self.db.commit()
            self.event("consumable_reset", name)
