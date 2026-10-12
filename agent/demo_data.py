"""
Demo data so the AI Agent can be shown even before a video has been processed.
Inserts one realistic 'shift' of alerts (clearly marked as demo in the UI), then lets
the Incident Agent correlate them exactly as it would on live data.
"""
import random
import time

from agent.incident_agent import IncidentAgent

ZONES = ["cash_counter", "stock_room", "entrance"]


def load_demo_shift(db, hours_back=6, seed=7):
    rnd = random.Random(seed)
    now = time.time()
    t = now - hours_back * 3600
    rows = []

    def add(dt, tid, rule, zone, msg, sev):
        nonlocal t
        t += dt
        rows.append((tid, rule, zone, msg, sev, t))

    # quiet morning: a few normal intrusions
    for tid in (1, 2, 4):
        add(rnd.randint(600, 1500), tid, "zone_intrusion", "entrance",
            f"Person #{tid} entered restricted zone 'entrance'", "warning")

    # someone casing the stock room (repeated loitering)
    for _ in range(3):
        add(rnd.randint(90, 160), 7, "zone_intrusion", "stock_room", "Person #7 entered restricted zone 'stock_room'", "warning")
        add(12, 7, "loitering", "stock_room", "Person #7 has been loitering in 'stock_room' for 9s", "critical")

    # a false alarm: running with nothing else around
    add(900, 11, "running", "", "Person #11 moving at high speed (610px/s) — possible fleeing", "critical")

    # theft sequence at the cash counter: loiter -> phone vanishes -> runs
    add(1200, 14, "zone_intrusion", "cash_counter", "Person #14 entered restricted zone 'cash_counter'", "warning")
    add(10, 14, "loitering", "cash_counter", "Person #14 has been loitering in 'cash_counter' for 8s", "critical")
    add(14, 15, "object_removed", "", "Cell phone #15 disappeared from view (a person was nearby) — possible removal", "warning")
    add(6, 14, "running", "", "Person #14 moving at high speed (720px/s) — possible fleeing", "critical")

    # laptop vanishes with nobody near (camera occlusion?)
    add(1500, 21, "object_removed", "", "Laptop #21 disappeared from view (no person was nearby) — possible removal", "critical")

    # group enters stock room
    for tid in (30, 31, 32):
        add(rnd.randint(5, 20), tid, "zone_intrusion", "stock_room", f"Person #{tid} entered restricted zone 'stock_room'", "warning")

    # keep everything in the past
    shift = max(0.0, rows[-1][5] - (now - 60))
    for tid, rule, zone, msg, sev, ts in rows:
        db.insert_event_returning_id(tid, rule, zone, msg, sev, timestamp=ts - shift)

    incidents = IncidentAgent(db).rescan_all()
    return len(rows), len(incidents)
