"""HTTP surface for the live product (login->shift setup->command center->
nurse POV). Thin request/response glue over app/live.py; no scheduling
logic lives here. In-memory sessions only - see app/live.py for why."""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app import live
from app.incidents import Incident
from app.starvation import bucket_for

router = APIRouter(prefix="/api/live", tags=["live"])

INCIDENT_DESCRIPTIONS = {
    "LOW_SPO2": "Assess desaturation",
    "HIGH_HR": "Assess tachycardia",
    "LOW_HR": "Assess bradycardia",
    "HIGH_BP": "Assess hypertension",
    "LOW_BP": "Assess hypotension",
    "HIGH_RR": "Assess respiratory distress",
    "LOW_RR": "Assess respiratory depression",
    "DETERIORATION": "Assess clinical deterioration",
    "SENSOR_DISCONNECT": "Check disconnected sensor",
    "ROUTINE_CHECK": "Routine check",
}

_BUCKET_GRADE = {"1": "GREEN", "2-4": "YELLOW", "5-7": "ORANGE", "8-10": "RED"}


def _grade_for_severity(severity: int) -> str:
    return _BUCKET_GRADE[bucket_for(severity)]


def _description_for(incident_type: str) -> str:
    return INCIDENT_DESCRIPTIONS.get(incident_type, incident_type.replace("_", " ").title())


# ---- request bodies ----

class NurseIn(BaseModel):
    name: str
    role: str


class ShiftCreateRequest(BaseModel):
    total_beds: int
    nurses: list[NurseIn]


class EventCreateRequest(BaseModel):
    room: str
    technical: bool = False


class EventConfirmRequest(BaseModel):
    severity_grade: str | None = None  # "GREEN"|"YELLOW"|"ORANGE"|"RED" - override (auto) or required (manual)


class ModeRequest(BaseModel):
    mode: str  # "manual" | "auto"


class AssignRequest(BaseModel):
    incident_id: str


# ---- helpers ----

def _get_session(shift_id: str) -> live.LiveSession:
    try:
        return live.get_session(shift_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown shift_id")


def _incident_dict(incident: Incident, nurse_id: str | None = None) -> dict:
    return {
        "id": incident.incident_id,
        "room": incident.room,
        "patient_id": incident.patient_id,
        "incident_type": incident.incident_type,
        "description": _description_for(incident.incident_type),
        "severity": incident.current_severity,
        "grade": _grade_for_severity(incident.current_severity),
        "status": incident.status,
        "repeat_count": incident.repeat_count,
        "escalated": incident.severity_change_reason == "starvation",
        "goal_minutes": round(incident.service_time, 1) if incident.service_time is not None else None,
        "first_seen": incident.first_seen.isoformat(),
        "dispatched_at": incident.dispatched_at.isoformat() if incident.dispatched_at else None,
        "nurse_id": nurse_id,
    }


def _event_dict(event: live.PendingEvent) -> dict:
    vitals = None
    if event.vitals is not None:
        vitals = {
            "heart_rate": event.vitals.heart_rate,
            "oxygen_saturation": event.vitals.oxygen_saturation,
            "systolic_bp": event.vitals.systolic_bp,
            "respiratory_rate": event.vitals.respiratory_rate,
        }
    return {
        "id": event.id,
        "room": event.room,
        "technical": event.technical,
        "vitals": vitals,
        "suggested_incident_type": event.suggested_incident_type,
        "suggested_description": _description_for(event.suggested_incident_type) if event.suggested_incident_type else None,
        "suggested_severity": event.suggested_severity,
        "suggested_grade": _grade_for_severity(event.suggested_severity) if event.suggested_severity else None,
        "status": event.status,
        "created_at": event.created_at.isoformat(),
    }


def _nurse_dict(nurse: live.NurseState, session: live.LiveSession) -> dict:
    task = None
    if nurse.assigned_incident_id:
        try:
            task = _incident_dict(session.get_incident(nurse.assigned_incident_id), nurse.id)
        except KeyError:
            task = None
    return {
        "id": nurse.id,
        "name": nurse.name,
        "role": nurse.role,
        "status": nurse.status,
        "current_room": nurse.current_room,
        "task": task,
    }


# ---- routes ----

@router.post("/shift")
def create_shift(body: ShiftCreateRequest):
    if body.total_beds < 1 or not body.nurses:
        raise HTTPException(status_code=400, detail="need at least 1 bed and 1 nurse")
    now = datetime.now()
    session = live.create_session(
        total_beds=body.total_beds,
        nurses=[(n.name, n.role) for n in body.nurses],
        now=now,
    )
    return {
        "shift_id": session.shift_id,
        "total_beds": session.total_beds,
        "mode": session.mode,
        "nurses": [_nurse_dict(n, session) for n in session.nurses.values()],
    }


@router.get("/state")
def get_state(shift_id: str = Query(...)):
    session = _get_session(shift_id)
    now = datetime.now()

    session.tick(now)

    claimed = session.claimed_incident_ids()
    active_tasks = [_incident_dict(i) for i in session.manager.active_waiting() if i.incident_id not in claimed]
    for nurse in session.nurses.values():
        if nurse.assigned_incident_id:
            active_tasks.append(_incident_dict(session.get_incident(nurse.assigned_incident_id), nurse.id))

    return {
        "shift_id": session.shift_id,
        "total_beds": session.total_beds,
        "mode": session.mode,
        "status": session.status,
        "nurses": [_nurse_dict(n, session) for n in session.nurses.values()],
        "pending_events": [_event_dict(e) for e in session.pending.values() if e.status == "pending"],
        "queue": active_tasks,
        "completed_count": sum(1 for i in session.manager.incidents if i.status == "resolved"),
        "raw_pings_total": sum(i.repeat_count for i in session.manager.incidents),
        "active_incidents_total": len(session.manager.incidents),
    }


@router.post("/events")
def create_event(body: EventCreateRequest, shift_id: str = Query(...)):
    session = _get_session(shift_id)
    event = session.new_event(body.room, datetime.now(), technical=body.technical)
    return _event_dict(event)


@router.post("/events/{event_id}/confirm")
def confirm_event(event_id: str, body: EventConfirmRequest, shift_id: str = Query(...)):
    session = _get_session(shift_id)
    if event_id not in session.pending:
        raise HTTPException(status_code=404, detail="unknown event_id")

    severity = None
    incident_type = None
    if body.severity_grade is not None:
        if body.severity_grade not in live.MANUAL_GRADE_SEVERITY:
            raise HTTPException(status_code=400, detail="severity_grade must be GREEN|YELLOW|ORANGE|RED")
        severity = live.MANUAL_GRADE_SEVERITY[body.severity_grade]
        event = session.pending[event_id]
        # A human-picked grade always carries its own incident_type too, so
        # a manual RED on a room with an existing YELLOW incident still
        # consolidates under the same (patient, type) key rather than
        # silently keeping the old type.
        incident_type = event.suggested_incident_type or "MANUAL_REVIEW"
    elif session.mode == "manual":
        raise HTTPException(status_code=400, detail="manual mode requires severity_grade")

    incident = session.finalize_event(event_id, datetime.now(), severity=severity, incident_type=incident_type)
    session.tick(datetime.now())
    return _incident_dict(incident)


@router.post("/nurses/{nurse_id}/assign")
def assign_task(nurse_id: str, body: AssignRequest, shift_id: str = Query(...)):
    """Manual Mode's assignment action - the coordinator explicitly assigns
    a specific nurse to a specific waiting task. Auto Mode never calls this;
    it assigns via the scheduler automatically instead (see LiveSession.tick)."""
    session = _get_session(shift_id)
    if nurse_id not in session.nurses:
        raise HTTPException(status_code=404, detail="unknown nurse_id")
    try:
        incident = session.manual_assign(nurse_id, body.incident_id, datetime.now())
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _incident_dict(incident, nurse_id)


@router.post("/nurses/{nurse_id}/start")
def start_task(nurse_id: str, shift_id: str = Query(...)):
    session = _get_session(shift_id)
    if nurse_id not in session.nurses:
        raise HTTPException(status_code=404, detail="unknown nurse_id")
    try:
        incident = session.start_task(nurse_id, datetime.now())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _incident_dict(incident, nurse_id)


@router.post("/nurses/{nurse_id}/done")
def complete_task(nurse_id: str, shift_id: str = Query(...)):
    session = _get_session(shift_id)
    if nurse_id not in session.nurses:
        raise HTTPException(status_code=404, detail="unknown nurse_id")
    try:
        incident = session.complete_task(nurse_id, datetime.now())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _incident_dict(incident, nurse_id)


@router.get("/nurses/{nurse_id}")
def get_nurse(nurse_id: str, shift_id: str = Query(...)):
    session = _get_session(shift_id)
    if nurse_id not in session.nurses:
        raise HTTPException(status_code=404, detail="unknown nurse_id")

    session.tick(datetime.now())
    nurse = session.nurses[nurse_id]
    up_next = session.peek_next()
    return {
        "nurse": _nurse_dict(nurse, session),
        "up_next": _incident_dict(up_next) if up_next else None,
    }


@router.post("/mode")
def set_mode(body: ModeRequest, shift_id: str = Query(...)):
    session = _get_session(shift_id)
    if body.mode not in ("manual", "auto"):
        raise HTTPException(status_code=400, detail="mode must be manual|auto")
    session.mode = body.mode
    return {"mode": session.mode}
