import time

from server.store import STALE_RUN_SECONDS, Store


def state(status, battery=90, area=0, work_time=0, online=True):
    return {"online": online, "status": status, "battery": battery, "area": area,
            "work_time": work_time, "mode": "auto", "fan": "normal", "water": "low"}


def test_run_lifecycle(tmp_path):
    s = Store(tmp_path / "h.db")
    t = time.time()
    s.feed(state("charge_finish", 100), t)
    assert s.run_id is None
    s.feed(state("work", 99), t + 1)
    assert s.run_id is not None
    s.feed(state("work", 80, area=12, work_time=20), t + 1200)
    s.feed(state("charge", 70, area=15, work_time=25), t + 1500)  # returning: still the same run
    s.feed(state("charging_on_dock", 69, area=15, work_time=25), t + 1600)
    assert s.run_id is None
    [run] = s.runs()
    assert (run["minutes"], run["area"], run["battery_start"], run["battery_end"]) == (25, 15, 99, 69)
    assert run["end_status"] == "charging_on_dock"


def test_pause_keeps_run_and_offline_closes_it(tmp_path):
    s = Store(tmp_path / "h.db")
    t = time.time()
    s.feed(state("work"), t)
    s.feed(state("pause"), t + 60)
    rid = s.run_id
    s.feed(state("work"), t + 120)
    assert s.run_id == rid
    s.feed(state(None, online=False), t + 130)
    assert s.run_id == rid  # a short drop-out does not end the run
    s.feed(state(None, online=False), t + 130 + STALE_RUN_SECONDS + 1)
    assert s.run_id is None
    assert s.runs()[0]["end_status"] == "offline"


def test_start_that_goes_nowhere_is_dropped(tmp_path):
    s = Store(tmp_path / "h.db")
    t = time.time()
    s.feed(state("work"), t)
    s.feed(state("charge"), t + 20)
    s.feed(state("charging_on_dock"), t + 60)
    assert s.run_id is None
    assert s.runs() == []


def test_returning_to_dock_alone_is_not_a_run(tmp_path):
    s = Store(tmp_path / "h.db")
    s.feed(state("charge"), time.time())
    assert s.run_id is None


def test_open_run_survives_restart(tmp_path):
    s = Store(tmp_path / "h.db")
    s.feed(state("work"), time.time())
    assert Store(tmp_path / "h.db").run_id == s.run_id


def test_consumables_count_run_minutes(tmp_path):
    s = Store(tmp_path / "h.db")
    t = time.time() - 7200
    s.reset_consumable("filter")  # baseline before the run, so the run counts
    s.db.execute("update consumables set reset_ts = ?", (t - 1,))
    s.feed(state("work", work_time=0), t)
    s.feed(state("charging_on_dock", work_time=90), t + 5400)
    brush = next(c for c in s.consumables() if c["name"] == "side_brush")
    assert brush["used_hours"] == 1.5
    s.reset_consumable("side_brush")
    assert next(c for c in s.consumables() if c["name"] == "side_brush")["used_hours"] == 0
