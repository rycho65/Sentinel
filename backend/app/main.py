from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles

from app.simulate import compute_metrics, run
from app.workload import generate_workload

app = FastAPI(title="Sentinel")

SCENARIO_SEED = 100  # fixed so every mode/knob combination replays the same underlying patients


@app.get("/api/simulation")
def get_simulation(
    mode: Literal["fifo", "greedy", "sentinel"] = "sentinel",
    nurses: int = Query(default=5, ge=1, le=20),
    rooms: int = Query(default=100, ge=5, le=300),
    shift_hours: float = Query(default=5, ge=1, le=12),
    pings_min: int = Query(default=20, ge=1, le=200),
    pings_max: int = Query(default=30, ge=1, le=200),
):
    """Generates the shared seeded raw-ping workload (app/workload.py) and
    replays it through the requested policy (app/simulate.py). All three
    modes start from the exact same pings, at the exact same timestamps -
    every knob here changes WORKLOAD or CAPACITY, never the scheduling
    policy. FIFO/Greedy schedule raw pings 1:1; Sentinel routes them through
    its incident table first (consolidation + starvation protection) before
    ever reaching the scheduler.
    """
    pings_lo, pings_hi = sorted((pings_min, pings_max))
    shift_minutes = shift_hours * 60

    pings, all_rooms = generate_workload(
        seed=SCENARIO_SEED,
        num_beds=rooms,
        shift_hours=shift_hours,
        pings_per_hour_range=(pings_lo, pings_hi),
    )

    result = run(pings, nurses, mode=mode, seed=SCENARIO_SEED, shift_minutes=shift_minutes)
    metrics = compute_metrics(result, nurses, shift_minutes)

    timeline = [asdict(e) for e in result.timeline]
    for entry in timeline:
        entry["alert_type"] = entry.pop("incident_type")
        entry["interrupted"] = False  # kept for frontend compat; no hard-interrupt concept anymore

    room_ids = sorted(all_rooms.values(), key=lambda r: int(r))

    return {
        "mode": mode,
        "nurses": nurses,
        "rooms": room_ids,
        "shift_hours": shift_hours,
        "total_minutes": result.total_minutes,
        "alerts": timeline,
        "metrics": metrics,
    }


app.mount("/", StaticFiles(directory="static", html=True), name="static")
