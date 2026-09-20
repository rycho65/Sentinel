from datetime import datetime, timedelta

from app import live
from app.scheduler import pick_sentinel
from app.severity import calculate_severity, classify_incident_type

NOW = datetime(2026, 9, 19, 8, 0)


def make_session(num_nurses=1, total_beds=20, seed=1):
    nurses = [(f"Nurse {i}", "RN") for i in range(num_nurses)]
    return live.LiveSession("SHIFT1", total_beds, nurses, NOW, seed=seed)


def one_nurse_id(session: live.LiveSession) -> str:
    return next(iter(session.nurses))


# Duplicate consolidation still applies to live events, same as batch mode.
def test_live_events_consolidate_same_room_same_type():
    session = make_session()
    e1 = session.new_event("114", NOW, technical=True)
    inc1 = session.finalize_event(e1.id, NOW)

    e2 = session.new_event("114", NOW + timedelta(minutes=1), technical=True)
    inc2 = session.finalize_event(e2.id, NOW + timedelta(minutes=1))

    assert inc1.incident_id == inc2.incident_id
    assert inc2.repeat_count == 2


def test_live_events_different_rooms_do_not_consolidate():
    session = make_session()
    e1 = session.new_event("114", NOW, technical=True)
    inc1 = session.finalize_event(e1.id, NOW)
    e2 = session.new_event("115", NOW, technical=True)
    inc2 = session.finalize_event(e2.id, NOW)

    assert inc1.incident_id != inc2.incident_id


# Auto Mode's "grading" IS calculate_severity/classify_incident_type - not a
# second, separately-invented algorithm.
def test_auto_mode_suggestion_uses_existing_severity_engine():
    session = make_session()
    event = session.new_event("114", NOW)  # not technical -> gets random vitals
    assert event.vitals is not None

    assert event.suggested_severity == calculate_severity(event.vitals)
    assert event.suggested_incident_type == classify_incident_type(event.vitals)


# Manual Mode severity comes from the fixed grade mapping, not the severity engine.
def test_manual_grade_mapping():
    session = make_session()
    event = session.new_event("114", NOW)
    incident = session.finalize_event(event.id, NOW, severity=live.MANUAL_GRADE_SEVERITY["RED"], incident_type="MANUAL_REVIEW")
    assert incident.current_severity == 9
    assert incident.initial_severity == 9


# assign_next must delegate to the SAME picker Sentinel simulation mode
# uses - no second "auto grading"/assignment algorithm.
def test_assign_next_delegates_to_scheduler_pick_sentinel():
    session = make_session(num_nurses=1)
    nurse_id = one_nurse_id(session)

    low = session.finalize_event(session.new_event("114", NOW).id, NOW, severity=2, incident_type="LOW_SPO2")
    high = session.finalize_event(session.new_event("120", NOW).id, NOW, severity=8, incident_type="HIGH_HR")

    expected = pick_sentinel([low, high])
    chosen = session.assign_next(nurse_id, NOW)

    assert chosen.incident_id == expected.incident_id == high.incident_id


# Full lifecycle: queued -> assigned -> in_progress -> completed.
def test_full_task_lifecycle():
    session = make_session(num_nurses=1)
    nurse_id = one_nurse_id(session)

    event = session.new_event("114", NOW, technical=True)
    incident = session.finalize_event(event.id, NOW)
    assert incident.status == "waiting"

    assigned = session.assign_next(nurse_id, NOW)
    assert assigned.incident_id == incident.incident_id
    assert session.nurses[nurse_id].status == "assigned"
    assert session.nurses[nurse_id].current_room is None  # not yet - only START moves the marker

    started = session.start_task(nurse_id, NOW + timedelta(minutes=1))
    assert started.status == "in_progress"
    assert session.nurses[nurse_id].status == "busy"
    assert session.nurses[nurse_id].current_room == "114"
    assert started.service_time is not None  # the "goal minutes"

    done = session.complete_task(nurse_id, NOW + timedelta(minutes=5))
    assert done.status == "resolved"
    assert session.nurses[nurse_id].status == "available"
    assert session.nurses[nurse_id].current_room is None


# A nurse who just went free is immediately re-assigned if work remains -
# work-conserving, matching the existing Sentinel principle.
def test_nurse_reassigned_immediately_after_done_if_work_remains():
    session = make_session(num_nurses=1)
    nurse_id = one_nurse_id(session)

    first = session.finalize_event(session.new_event("114", NOW).id, NOW, severity=3, incident_type="LOW_SPO2")
    second = session.finalize_event(session.new_event("120", NOW).id, NOW, severity=3, incident_type="HIGH_HR")

    session.assign_next(nurse_id, NOW)
    session.start_task(nurse_id, NOW)
    session.complete_task(nurse_id, NOW + timedelta(minutes=5))

    nurse = session.nurses[nurse_id]
    assert nurse.status == "assigned"
    assert nurse.assigned_incident_id in (first.incident_id, second.incident_id)
    assert nurse.assigned_incident_id != first.incident_id  # first is already resolved


def test_tick_never_leaves_a_nurse_idle_while_work_exists():
    session = make_session(num_nurses=1)
    nurse_id = one_nurse_id(session)
    session.finalize_event(session.new_event("114", NOW).id, NOW, severity=3, incident_type="LOW_SPO2")

    session.tick(NOW)

    assert session.nurses[nurse_id].status == "assigned"


# Starvation aging (app/starvation.py, unmodified) still applies to live incidents.
def test_starvation_aging_applies_to_live_incidents():
    session = make_session(num_nurses=0)
    incident = session.finalize_event(session.new_event("114", NOW).id, NOW, severity=2, incident_type="LOW_SPO2")

    session.tick(NOW + timedelta(hours=10))  # 20 windows, P(no escalation) is negligible

    assert incident.current_severity > 2
    assert incident.escalation_count > 0


# Auto-assignment is an Auto Mode exclusive - Manual Mode must never touch a
# nurse's status on its own, whether via tick() or completing a task.
def test_manual_mode_never_auto_assigns_on_tick():
    session = make_session(num_nurses=1)
    session.mode = "manual"
    nurse_id = one_nurse_id(session)
    session.finalize_event(session.new_event("114", NOW).id, NOW, severity=5, incident_type="LOW_SPO2")

    session.tick(NOW)

    assert session.nurses[nurse_id].status == "available"


def test_manual_mode_never_auto_reassigns_after_done():
    session = make_session(num_nurses=1)
    nurse_id = one_nurse_id(session)
    first = session.finalize_event(session.new_event("114", NOW).id, NOW, severity=3, incident_type="LOW_SPO2")
    session.finalize_event(session.new_event("120", NOW).id, NOW, severity=3, incident_type="HIGH_HR")

    # still in auto mode for the first task, so this part works as usual
    session.assign_next(nurse_id, NOW)
    session.start_task(nurse_id, NOW)

    session.mode = "manual"
    session.complete_task(nurse_id, NOW + timedelta(minutes=5))

    assert session.nurses[nurse_id].status == "available"
    assert session.nurses[nurse_id].assigned_incident_id is None


# Manual Mode's actual assignment path: the coordinator explicitly picks nurse+task.
def test_manual_assign_lets_coordinator_pick_the_nurse():
    session = make_session(num_nurses=2)
    session.mode = "manual"
    nurse_ids = list(session.nurses)

    low = session.finalize_event(session.new_event("114", NOW).id, NOW, severity=2, incident_type="LOW_SPO2")
    high = session.finalize_event(session.new_event("120", NOW).id, NOW, severity=9, incident_type="HIGH_HR")

    # deliberately assign the SECOND nurse to the LOWER severity task -
    # something pick_sentinel would never choose on its own, proving this is
    # genuinely human-controlled, not the scheduler in disguise.
    session.manual_assign(nurse_ids[1], low.incident_id, NOW)

    assert session.nurses[nurse_ids[1]].assigned_incident_id == low.incident_id
    assert session.nurses[nurse_ids[0]].status == "available"  # untouched
    assert high.status == "waiting"  # still sitting there, nobody auto-grabbed it


def test_manual_assign_rejects_already_claimed_incident():
    session = make_session(num_nurses=2)
    session.mode = "manual"
    nurse_ids = list(session.nurses)
    incident = session.finalize_event(session.new_event("114", NOW).id, NOW, severity=4, incident_type="LOW_SPO2")

    session.manual_assign(nurse_ids[0], incident.incident_id, NOW)

    try:
        session.manual_assign(nurse_ids[1], incident.incident_id, NOW)
        assert False, "expected a ValueError"
    except ValueError:
        pass
