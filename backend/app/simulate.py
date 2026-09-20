"""The tick engine: replays the same seeded RawPing stream through whichever
policy (fifo/greedy/sentinel) is requested and reports what happened.

FIFO and Greedy schedule raw pings 1:1 as independent Tasks - no incident
memory, no consolidation. Sentinel routes pings through IncidentManager first
(app/incidents.py), so repeated pings about the same (patient_id,
incident_type) consolidate into one incident instead of one task each.

Starvation-driven escalation (app/starvation.py) applies to ALL THREE
policies equally - a neglected problem can plausibly worsen no matter who's
scheduling it. Sentinel's actual, sole edge is duplicate consolidation.

Work-conserving for all three: a free nurse with eligible work never idles.
"""

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.incidents import Incident, IncidentManager
from app.models import RawPing, Task, ping_to_task
from app.scheduler import decide
from app.service_time import generate_service_time
from app.starvation import bucket_for, refresh_starvation

TICK_MINUTES = 1
MAX_TICKS = 100_000


@dataclass
class TimelineEntry:
    id: str
    patient_id: str
    room: str
    incident_type: str
    severity: int
    arrival_min: int
    assigned_min: int | None
    finish_min: int | None
    wait_min: float | None
    escalated: bool = False
    repeat_count: int = 1


@dataclass
class RunResult:
    mode: str
    nurses: int
    start: datetime
    total_minutes: int
    timeline: list[TimelineEntry]
    nurse_busy_minutes: list[float]
    max_backlog: int
    raw_pings: int
    nurse_facing_tasks: int
    active_incidents: int | None = None
    duplicates_consolidated: int | None = None
    starvation_escalations: int = 0
    avg_escalation_count: float = 0.0
    escalations_2to4_5to7: int = 0
    escalations_5to7_8to10: int = 0


def run(
    pings: list[RawPing],
    num_nurses: int,
    mode: str,
    seed: int = 0,
    shift_minutes: float | None = None,
) -> RunResult:
    pings = sorted(pings, key=lambda p: p.timestamp)
    if not pings:
        return RunResult(mode, num_nurses, datetime.now(), 0, [], [0.0] * num_nurses, 0, 0, 0)

    start = pings[0].timestamp
    service_rng = random.Random(f"svc:{seed}:{mode}")

    manager = IncidentManager(seed=seed) if mode == "sentinel" else None
    tasks = [] if mode == "sentinel" else [
        ping_to_task(i, p, seed_key=f"{seed}:{mode}") for i, p in enumerate(pings)
    ]
    all_items: list = manager.incidents if manager is not None else tasks  # grows as sentinel opens incidents

    nurse_free_at = [start] * num_nurses
    nurse_busy = [False] * num_nurses
    nurse_room: list[str | None] = [None] * num_nurses
    nurse_item = [None] * num_nurses  # incident/task currently occupying this nurse
    nurse_busy_minutes = [0.0] * num_nurses

    timeline: list[TimelineEntry] = []
    max_backlog = 0
    ping_idx = 0
    current_time = start
    bucket_escalations = {"2-4->5-7": 0, "5-7->8-10": 0}

    def refresh_item(item, start_time: datetime) -> None:
        change = refresh_starvation(item, start_time, current_time)
        if change is None:
            return
        before, after = change
        before_bucket, after_bucket = bucket_for(before), bucket_for(after)
        if before_bucket == "2-4" and after_bucket == "5-7":
            bucket_escalations["2-4->5-7"] += 1
        elif before_bucket == "5-7" and after_bucket == "8-10":
            bucket_escalations["5-7->8-10"] += 1

    for _ in range(MAX_TICKS):
        while ping_idx < len(pings) and pings[ping_idx].timestamp <= current_time:
            p = pings[ping_idx]
            if manager is not None:
                manager.process_ping(p, current_time)
            ping_idx += 1

        if manager is not None:
            for incident in manager.active_waiting():
                refresh_item(incident, incident.first_seen)
        else:
            for t in tasks:
                if t.status == "waiting" and t.created_at <= current_time:
                    refresh_item(t, t.created_at)

        for i in range(num_nurses):
            if nurse_busy[i] and nurse_free_at[i] <= current_time:
                if manager is not None:
                    manager.resolve(nurse_item[i], current_time)
                else:
                    nurse_item[i].status = "resolved"
                nurse_busy[i] = False
                nurse_room[i] = None
                nurse_item[i] = None

        for i in range(num_nurses):
            if nurse_busy[i]:
                continue

            occupied_rooms = {r for r in nurse_room if r is not None}
            if manager is not None:
                eligible = [inc for inc in manager.active_waiting() if inc.room not in occupied_rooms]
            else:
                eligible = [
                    t for t in tasks
                    if t.status == "waiting" and t.created_at <= current_time and t.room not in occupied_rooms
                ]

            chosen = decide(mode, eligible, current_time)
            if chosen is None:
                continue

            if manager is not None:
                manager.dispatch(chosen, current_time)
                duration = chosen.service_time
            else:
                chosen.status = "in_progress"
                duration = generate_service_time(chosen.current_severity, service_rng)
                chosen.service_time = duration

            nurse_busy[i] = True
            nurse_room[i] = chosen.room
            nurse_item[i] = chosen
            nurse_free_at[i] = current_time + timedelta(minutes=duration)
            nurse_busy_minutes[i] += duration

            timeline.append(_entry(chosen, current_time, duration, start))

        if manager is not None:
            backlog_now = len(manager.active_waiting())
        else:
            backlog_now = sum(1 for t in tasks if t.status == "waiting" and t.created_at <= current_time)
        max_backlog = max(max_backlog, backlog_now)

        pending_arrivals = ping_idx < len(pings)
        any_busy = any(nurse_busy)
        remaining_work = backlog_now > 0 or any(
            (i.status == "waiting" for i in manager.incidents) if manager is not None
            else (t.status == "waiting" for t in tasks)
        )

        if not pending_arrivals and not remaining_work and not any_busy:
            break

        current_time += timedelta(minutes=TICK_MINUTES)

    # Anything still waiting when the run ended - still shown, so an
    # under-resourced rush visibly leaves a backlog instead of vanishing.
    if manager is not None:
        for inc in manager.incidents:
            if inc.status == "waiting":
                timeline.append(_entry(inc, None, None, start))
    else:
        for t in tasks:
            if t.status == "waiting":
                timeline.append(_entry(t, None, None, start))

    timeline.sort(key=lambda e: e.arrival_min)
    total_minutes = max((e.finish_min for e in timeline if e.finish_min is not None), default=0)

    escalated_items = [x for x in all_items if x.escalation_count > 0]

    result = RunResult(
        mode=mode,
        nurses=num_nurses,
        start=start,
        total_minutes=total_minutes,
        timeline=timeline,
        nurse_busy_minutes=nurse_busy_minutes,
        max_backlog=max_backlog,
        raw_pings=len(pings),
        nurse_facing_tasks=len(tasks) if manager is None else len(manager.incidents),
        starvation_escalations=len(escalated_items),
        avg_escalation_count=(
            sum(x.escalation_count for x in escalated_items) / len(escalated_items) if escalated_items else 0.0
        ),
        escalations_2to4_5to7=bucket_escalations["2-4->5-7"],
        escalations_5to7_8to10=bucket_escalations["5-7->8-10"],
    )

    if manager is not None:
        result.active_incidents = len(manager.incidents)
        result.duplicates_consolidated = len(pings) - len(manager.incidents)

    return result


def _entry(item, dispatch_time: datetime | None, duration: float | None, start: datetime) -> TimelineEntry:
    is_incident = isinstance(item, Incident)
    arrival = item.first_seen if is_incident else item.created_at
    arrival_min = round((arrival - start).total_seconds() / 60)
    escalated = item.severity_change_reason == "starvation"
    repeat_count = item.repeat_count if is_incident else 1
    item_id = item.incident_id if is_incident else item.id

    if dispatch_time is None:
        return TimelineEntry(
            id=item_id,
            patient_id=item.patient_id,
            room=item.room,
            incident_type=item.incident_type,
            severity=item.current_severity,
            arrival_min=arrival_min,
            assigned_min=None,
            finish_min=None,
            wait_min=None,
            escalated=escalated,
            repeat_count=repeat_count,
        )

    assigned_min = round((dispatch_time - start).total_seconds() / 60)
    finish_min = assigned_min + round(duration)
    wait_min = round((dispatch_time - arrival).total_seconds() / 60, 1)
    return TimelineEntry(
        id=item_id,
        patient_id=item.patient_id,
        room=item.room,
        incident_type=item.incident_type,
        severity=item.current_severity,
        arrival_min=arrival_min,
        assigned_min=assigned_min,
        finish_min=finish_min,
        wait_min=wait_min,
        escalated=escalated,
        repeat_count=repeat_count,
    )


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def compute_metrics(result: RunResult, num_nurses: int, shift_minutes: float | None) -> dict:
    completed = [e for e in result.timeline if e.wait_min is not None]
    backlog = [e for e in result.timeline if e.wait_min is None]

    buckets: dict[str, list[float]] = {"1": [], "2-4": [], "5-7": [], "8-10": []}
    for e in completed:
        buckets[bucket_for(e.severity)].append(e.wait_min)

    def avg(xs: list[float]) -> float | None:
        return sum(xs) / len(xs) if xs else None

    all_waits = [e.wait_min for e in completed]
    utilization = (
        sum(result.nurse_busy_minutes) / (num_nurses * shift_minutes)
        if shift_minutes else None
    )

    metrics = {
        "raw_pings": result.raw_pings,
        "nurse_facing_tasks": result.nurse_facing_tasks,
        "completed": len(completed),
        "remaining_backlog": len(backlog),
        "max_backlog": result.max_backlog,
        "avg_nurse_utilization": utilization,

        "avg_wait": avg(all_waits),
        "worst_wait": max(all_waits) if all_waits else None,
        "sev_1": avg(buckets["1"]),
        "sev_2_4": avg(buckets["2-4"]),
        "sev_5_7": avg(buckets["5-7"]),
        "sev_8_10": avg(buckets["8-10"]),
        "max_wait_sev_1": max(buckets["1"]) if buckets["1"] else None,
        "max_wait_sev_2_4": max(buckets["2-4"]) if buckets["2-4"] else None,

        "starvation_escalations": result.starvation_escalations,
        "avg_escalation_count": result.avg_escalation_count,
        "escalations_2to4_5to7": result.escalations_2to4_5to7,
        "escalations_5to7_8to10": result.escalations_5to7_8to10,
    }

    if result.active_incidents is not None:
        metrics.update({
            "active_incidents": result.active_incidents,
            "duplicates_consolidated": result.duplicates_consolidated,
        })

    return metrics
