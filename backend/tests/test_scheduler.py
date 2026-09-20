import random
from datetime import datetime, timedelta

from app.incidents import Incident
from app.models import Task
from app.scheduler import decide
from app.starvation import refresh_starvation

NOW = datetime(2026, 9, 19, 8, 0)


def make_task(severity, minutes_ago=0, task_id="T1"):
    return Task(
        id=task_id, patient_id="P1", room="101", incident_type="LOW_SPO2",
        initial_severity=severity, current_severity=severity, peak_severity=severity,
        created_at=NOW - timedelta(minutes=minutes_ago),
        _rng=random.Random(task_id),
    )


def make_incident(severity, minutes_ago=0, incident_id="I1"):
    return Incident(
        incident_id=incident_id, patient_id="P1", room="101", incident_type="LOW_SPO2",
        initial_severity=severity, current_severity=severity, peak_severity=severity,
        first_seen=NOW - timedelta(minutes=minutes_ago), last_seen=NOW,
        _rng=random.Random(incident_id),
    )


def test_fifo_picks_oldest_regardless_of_severity():
    old_low = make_task(severity=2, minutes_ago=100, task_id="old")
    new_high = make_task(severity=9, minutes_ago=1, task_id="new")

    chosen = decide("fifo", [old_low, new_high], NOW)

    assert chosen.id == "old"


def test_greedy_picks_highest_severity_regardless_of_age():
    old_low = make_task(severity=2, minutes_ago=100, task_id="old")
    new_high = make_task(severity=9, minutes_ago=1, task_id="new")

    chosen = decide("greedy", [old_low, new_high], NOW)

    assert chosen.id == "new"


# Starvation is shared infrastructure now (app/starvation.py), not a
# Sentinel-only trick: a plain FIFO/Greedy Task escalates exactly the same
# way a Sentinel Incident does.
def test_greedy_tasks_also_starve_like_incidents():
    task = make_task(severity=2, minutes_ago=0)

    # 20 windows (10 hours) at ~35% escalation odds per window: P(never
    # escalates) < 0.1%, so this is effectively deterministic, not flaky.
    refresh_starvation(task, task.created_at, task.created_at + timedelta(minutes=600))

    assert task.current_severity > 2
    assert task.severity_change_reason == "starvation"


# Sentinel's ACTUAL, sole edge over Greedy: duplicate consolidation. Both
# pickers below make the identical choice given the identical inputs -
# Sentinel wins upstream (app/incidents.py), never here.
def test_sentinel_and_greedy_pick_identically_given_the_same_inputs():
    low_old = make_incident(severity=3, minutes_ago=50, incident_id="low")
    high_new = make_incident(severity=8, minutes_ago=1, incident_id="high")
    low_task = make_task(severity=3, minutes_ago=50, task_id="low")
    high_task = make_task(severity=8, minutes_ago=1, task_id="high")

    sentinel_choice = decide("sentinel", [low_old, high_new], NOW)
    greedy_choice = decide("greedy", [low_task, high_task], NOW)

    assert sentinel_choice.current_severity == greedy_choice.current_severity == 8


def test_sentinel_picks_highest_current_severity_ties_broken_by_age():
    older = make_incident(severity=6, minutes_ago=50, incident_id="older")
    newer_same_severity = make_incident(severity=6, minutes_ago=5, incident_id="newer")

    chosen = decide("sentinel", [older, newer_same_severity], NOW)

    assert chosen.incident_id == "older"


# Every policy is work-conserving: never idles a nurse while eligible work exists.
def test_decide_never_idles_when_eligible_work_exists():
    for mode in ("fifo", "greedy", "sentinel"):
        eligible = [make_task(severity=1)] if mode != "sentinel" else [make_incident(severity=1)]
        assert decide(mode, eligible, NOW) is not None


def test_decide_returns_none_only_when_nothing_eligible():
    for mode in ("fifo", "greedy", "sentinel"):
        assert decide(mode, [], NOW) is None
