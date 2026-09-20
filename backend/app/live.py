"""Live product session layer: shift setup, nurses, incoming events, task
lifecycle. Pure orchestration - every piece of actual scheduling
intelligence (severity, duplicate consolidation, starvation aging,
highest-severity dispatch) is the existing Sentinel backend
(app/incidents.py, app/scheduler.py, app/starvation.py, app/severity.py).
Nothing in this file reimplements any of that; Auto Mode IS that backend,
just driven by one event at a time instead of a replayed batch.

In-memory only for now - Supabase persistence is intentionally deferred
until this shape has stabilized (see app/database.py)."""

import random
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.incidents import Incident, IncidentManager
from app.models import RawPing
from app.scheduler import pick_sentinel
from app.severity import PatientState, calculate_severity, classify_incident_type
from app.workload import acute_blip_reading, chronic_mild_reading, deteriorating_reading, stable_reading

# GREEN/YELLOW/ORANGE/RED -> severity, matching the same bucket/color
# convention already used by severityClass()/bucketFor() in app.js:
# 1 / 2-4 / 5-7 / 8-10.
MANUAL_GRADE_SEVERITY = {"GREEN": 1, "YELLOW": 3, "ORANGE": 6, "RED": 9}


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _random_vitals(rng: random.Random, patient_id: str) -> PatientState:
    roll = rng.random()
    if roll < 0.5:
        state = acute_blip_reading(rng)
    elif roll < 0.75:
        state = chronic_mild_reading(rng)
    elif roll < 0.9:
        state = deteriorating_reading(rng, rng.uniform(0.3, 0.9))
    else:
        state = stable_reading(rng)
    state.patient_id = patient_id
    return state


@dataclass
class NurseState:
    id: str
    name: str
    role: str
    status: str = "available"       # available | assigned | busy
    current_room: str | None = None
    assigned_incident_id: str | None = None


@dataclass
class PendingEvent:
    id: str
    room: str
    patient_id: str
    vitals: PatientState | None
    technical: bool
    created_at: datetime
    suggested_incident_type: str | None = None
    suggested_severity: int | None = None
    status: str = "pending"   # pending | resolved


class LiveSession:
    def __init__(
        self,
        shift_id: str,
        total_beds: int,
        nurses: list[tuple[str, str]],
        started_at: datetime,
        seed: int = 0,
    ):
        self.shift_id = shift_id
        self.total_beds = total_beds
        self.started_at = started_at
        self.status = "active"
        self.mode = "auto"   # "manual" | "auto"

        self.manager = IncidentManager(seed=seed)
        self.nurses: dict[str, NurseState] = {}
        for name, role in nurses:
            nid = _new_id("N")
            self.nurses[nid] = NurseState(id=nid, name=name, role=role)

        self.pending: dict[str, PendingEvent] = {}
        self._rng = random.Random(seed)

    # ---- incoming events ----

    def new_event(
        self, room: str, now: datetime, vitals: PatientState | None = None, technical: bool = False,
    ) -> PendingEvent:
        patient_id = room  # no separate patient tracking - room IS the identity here (no location tracking)
        if vitals is None and not technical:
            vitals = _random_vitals(self._rng, patient_id)

        event = PendingEvent(
            id=_new_id("EVT"), room=room, patient_id=patient_id,
            vitals=vitals, technical=technical, created_at=now,
        )

        if technical:
            event.suggested_incident_type = "SENSOR_DISCONNECT"
            event.suggested_severity = 1
        elif vitals is not None:
            # This IS Auto Mode's "grading" - the same severity engine used
            # by Simulation Mode's workload generator, nothing new.
            event.suggested_incident_type = classify_incident_type(vitals)
            event.suggested_severity = calculate_severity(vitals)

        self.pending[event.id] = event
        return event

    def finalize_event(
        self, event_id: str, now: datetime, severity: int | None = None, incident_type: str | None = None,
    ) -> Incident:
        """Turns a PendingEvent into a real Sentinel Incident. In Auto Mode,
        omitting severity/incident_type accepts Sentinel's own suggestion
        (CONFIRM); passing them is the OVERRIDE / Manual-Mode path - either
        way it lands in the exact same IncidentManager.process_ping() call,
        so duplicate consolidation applies identically regardless of mode."""
        event = self.pending[event_id]
        final_severity = severity if severity is not None else event.suggested_severity
        final_type = incident_type if incident_type is not None else event.suggested_incident_type
        if final_severity is None or final_type is None:
            raise ValueError("event has no severity/incident_type yet - grade it first")

        ping = RawPing(
            patient_id=event.patient_id, room=event.room, incident_type=final_type,
            severity=final_severity, timestamp=now, technical=event.technical,
        )
        incident = self.manager.process_ping(ping, now)
        event.status = "resolved"
        return incident

    # ---- assignment / task lifecycle ----

    def _claimed_incident_ids(self) -> set[str]:
        return {n.assigned_incident_id for n in self.nurses.values() if n.assigned_incident_id}

    claimed_incident_ids = _claimed_incident_ids  # internal alias used within this class

    def _eligible_incidents(self) -> list[Incident]:
        claimed = self._claimed_incident_ids()
        return [i for i in self.manager.active_waiting() if i.incident_id not in claimed]

    def peek_next(self) -> Incident | None:
        """Read-only preview of what WOULD be assigned next, system-wide -
        used for a nurse's "up next" card. Does not claim anything."""
        eligible = self._eligible_incidents()
        return pick_sentinel(eligible) if eligible else None

    def assign_next(self, nurse_id: str, now: datetime) -> Incident | None:
        """Auto Mode ONLY - the coordinator never calls this directly. Manual
        Mode assigns exclusively via manual_assign(), so the coordinator
        keeps full control over which nurse goes where."""
        nurse = self.nurses[nurse_id]
        if nurse.status != "available":
            return None
        eligible = self._eligible_incidents()
        if not eligible:
            return None
        chosen = pick_sentinel(eligible)  # the SAME picker Sentinel simulation mode dispatches with
        nurse.status = "assigned"
        nurse.assigned_incident_id = chosen.incident_id
        return chosen

    def manual_assign(self, nurse_id: str, incident_id: str, now: datetime) -> Incident:
        """Manual Mode's assignment path - the coordinator explicitly picks
        which nurse takes which task. No scheduler picker involved at all;
        this is the human doing the job Sentinel does automatically in Auto
        Mode."""
        nurse = self.nurses[nurse_id]
        if nurse.status != "available":
            raise ValueError(f"nurse {nurse_id} is not available")
        incident = self.get_incident(incident_id)
        if incident.status != "waiting":
            raise ValueError(f"incident {incident_id} is not waiting to be assigned")
        if incident.incident_id in self.claimed_incident_ids():
            raise ValueError(f"incident {incident_id} is already assigned to another nurse")

        nurse.status = "assigned"
        nurse.assigned_incident_id = incident.incident_id
        return incident

    def start_task(self, nurse_id: str, now: datetime) -> Incident:
        nurse = self.nurses[nurse_id]
        if nurse.status != "assigned" or nurse.assigned_incident_id is None:
            raise ValueError(f"nurse {nurse_id} has no assigned task to start")
        incident = self._incident(nurse.assigned_incident_id)
        self.manager.dispatch(incident, now)   # unmodified - also generates service_time ("goal minutes")
        nurse.status = "busy"
        nurse.current_room = incident.room
        return incident

    def complete_task(self, nurse_id: str, now: datetime) -> Incident:
        nurse = self.nurses[nurse_id]
        if nurse.status != "busy" or nurse.assigned_incident_id is None:
            raise ValueError(f"nurse {nurse_id} has no in-progress task to complete")
        incident = self._incident(nurse.assigned_incident_id)
        self.manager.resolve(incident, now)   # unmodified
        nurse.status = "available"
        nurse.current_room = None
        nurse.assigned_incident_id = None
        if self.mode == "auto":
            self.assign_next(nurse_id, now)    # work-conserving - Auto Mode only
        return incident

    def tick(self, now: datetime) -> None:
        self.manager.refresh_all(now)   # starvation aging - unmodified, runs regardless of mode
        if self.mode == "auto":
            for nurse_id in list(self.nurses):
                self.assign_next(nurse_id, now)

    def get_incident(self, incident_id: str) -> Incident:
        for i in self.manager.incidents:
            if i.incident_id == incident_id:
                return i
        raise KeyError(incident_id)

    _incident = get_incident  # internal alias used within this class


_sessions: dict[str, LiveSession] = {}


def create_session(
    total_beds: int, nurses: list[tuple[str, str]], now: datetime, seed: int | None = None,
) -> LiveSession:
    shift_id = _new_id("SHIFT")
    session = LiveSession(
        shift_id, total_beds, nurses, now,
        seed=seed if seed is not None else random.randint(0, 1_000_000),
    )
    _sessions[shift_id] = session
    return session


def get_session(shift_id: str) -> LiveSession:
    if shift_id not in _sessions:
        raise KeyError(shift_id)
    return _sessions[shift_id]
