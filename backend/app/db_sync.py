"""Best-effort, write-through Supabase persistence for the live product.

Every function here does exactly one thing: mirror an in-memory object
(app/live.py's LiveSession/NurseState/PendingEvent, or app/incidents.py's
Incident) into its matching Supabase row (see backend/supabase/schema.sql).
Nothing in this file makes a scheduling decision - it only observes state
that app/live.py and app/incidents.py already computed and writes it down.

The in-memory `_sessions` dict in app/live.py remains the actual source of
truth the scheduler runs on. Supabase is a durable mirror of it, not a
replacement - if Supabase is slow, misconfigured, or unreachable, the live
product must keep working exactly as it did before this file existed. Every
write here is caught and swallowed for that reason.

Scope note: this is write-through persistence only. It does NOT reconstruct
a LiveSession from Supabase after a server restart - that would mean
correctly resuming IncidentManager's internal id counter, each Incident's
per-incident RNG, etc., and getting that subtly wrong is worse than not
having it. Rows survive a restart in Supabase; the live in-memory session
does not, same as before this change.

Set SENTINEL_DB_SYNC=0 to disable entirely (tests do this via conftest.py,
so the test suite never touches the network or a real project).
"""

import os
import traceback

from app.database import get_supabase

_ENABLED = os.getenv("SENTINEL_DB_SYNC", "1") != "0"


def _safe(label: str, fn) -> None:
    if not _ENABLED:
        return
    try:
        fn()
    except Exception:
        print(f"[db_sync] {label} failed (continuing without it):")
        traceback.print_exc()


def sync_shift(session) -> None:
    def _write():
        get_supabase().table("shifts").upsert({
            "shift_id": session.shift_id,
            "total_beds": session.total_beds,
            "status": session.status,
            "mode": session.mode,
            "seed": session.manager.seed,
            "started_at": session.started_at.isoformat(),
        }, on_conflict="shift_id").execute()
    _safe(f"sync_shift({session.shift_id})", _write)


def sync_nurse(session, nurse) -> None:
    def _write():
        get_supabase().table("nurses").upsert({
            "nurse_id": nurse.id,
            "shift_id": session.shift_id,
            "name": nurse.name,
            "role": nurse.role,
            "status": nurse.status,
            "current_room": nurse.current_room,
            "assigned_incident_id": nurse.assigned_incident_id,
        }, on_conflict="nurse_id").execute()
    _safe(f"sync_nurse({nurse.id})", _write)


def sync_pending_event(session, event) -> None:
    def _write():
        vitals = None
        if event.vitals is not None:
            vitals = {
                "heart_rate": event.vitals.heart_rate,
                "oxygen_saturation": event.vitals.oxygen_saturation,
                "systolic_bp": event.vitals.systolic_bp,
                "respiratory_rate": event.vitals.respiratory_rate,
                "deterioration_rate": event.vitals.deterioration_rate,
            }
        get_supabase().table("pending_events").upsert({
            "event_id": event.id,
            "shift_id": session.shift_id,
            "room": event.room,
            "patient_id": event.patient_id,
            "technical": event.technical,
            "vitals": vitals,
            "suggested_incident_type": event.suggested_incident_type,
            "suggested_severity": event.suggested_severity,
            "status": event.status,
            "created_at": event.created_at.isoformat(),
        }, on_conflict="event_id").execute()
    _safe(f"sync_pending_event({event.id})", _write)


def sync_incident(session, incident) -> None:
    def _write():
        get_supabase().table("incidents").upsert({
            "incident_id": incident.incident_id,
            "shift_id": session.shift_id,
            "patient_id": incident.patient_id,
            "room": incident.room,
            "incident_type": incident.incident_type,
            "initial_severity": incident.initial_severity,
            "current_severity": incident.current_severity,
            "peak_severity": incident.peak_severity,
            "first_seen": incident.first_seen.isoformat(),
            "last_seen": incident.last_seen.isoformat(),
            "repeat_count": incident.repeat_count,
            "status": incident.status,
            "service_time": incident.service_time,
            "severity_change_reason": incident.severity_change_reason,
            "escalation_count": incident.escalation_count,
            "escalation_windows_checked": incident._windows_checked,
            "dispatched_at": incident.dispatched_at.isoformat() if incident.dispatched_at else None,
            "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        }, on_conflict="shift_id,incident_id").execute()
    _safe(f"sync_incident({incident.incident_id})", _write)
