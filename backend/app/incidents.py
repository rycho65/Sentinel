import random
from dataclasses import dataclass, field
from datetime import datetime

from app.models import RawPing
from app.service_time import generate_service_time
from app.starvation import refresh_starvation

# Re-exported for convenience/back-compat - the actual constant lives with
# the shared starvation logic in app/starvation.py.
from app.starvation import MAX_SEVERITY  # noqa: F401


@dataclass
class Incident:
    """One evolving patient problem, keyed by (patient_id, incident_type).
    Any number of raw pings can feed into the same Incident while it's open -
    that's Sentinel's duplicate consolidation. There is exactly one
    `current_severity`: it can rise because physiology genuinely worsened, or
    because the incident has simply been waiting too long (starvation
    protection - see app/starvation.py, shared with plain FIFO/Greedy Tasks).
    `severity_change_reason` records which one moved it last, so the two
    mechanisms stay easy to tell apart in the demo/metrics."""

    incident_id: str
    patient_id: str
    room: str
    incident_type: str

    initial_severity: int
    current_severity: int
    peak_severity: int

    first_seen: datetime
    last_seen: datetime
    repeat_count: int = 1

    status: str = "waiting"     # waiting | in_progress | resolved
    service_time: float | None = None

    severity_change_reason: str = "none"   # "physiology" | "starvation" | "none"
    escalation_count: int = 0              # total severity points added by starvation

    dispatched_at: datetime | None = None
    resolved_at: datetime | None = None

    _windows_checked: int = field(default=0, repr=False)
    _rng: random.Random = field(default=None, repr=False)

    def apply_ping(self, ping: RawPing, now: datetime) -> None:
        """Merge a duplicate/follow-up ping into this still-open incident
        instead of creating another nurse-facing task."""
        self.repeat_count += 1
        self.last_seen = now
        if ping.severity > self.current_severity:
            self.current_severity = ping.severity
            self.severity_change_reason = "physiology"
            self.peak_severity = max(self.peak_severity, self.current_severity)

    def refresh_starvation(self, now: datetime) -> tuple[int, int] | None:
        return refresh_starvation(self, self.first_seen, now)


class IncidentManager:
    """Maintains Sentinel's active incident table, keyed by
    (patient_id, incident_type). Starvation-driven escalation itself is
    shared with FIFO/Greedy (app/starvation.py) - what's actually special
    here is duplicate consolidation and persistent incident memory."""

    def __init__(self, seed: int = 0):
        self.seed = seed
        self._active: dict[tuple[str, str], Incident] = {}
        self.incidents: list[Incident] = []  # every incident ever opened

        self._next_id = 1
        self._service_rng = random.Random(f"svc:{seed}")

    def process_ping(self, ping: RawPing, now: datetime) -> Incident:
        key = (ping.patient_id, ping.incident_type)
        incident = self._active.get(key)
        if incident is not None:
            incident.apply_ping(ping, now)
            return incident

        incident = Incident(
            incident_id=f"INC{self._next_id}",
            patient_id=ping.patient_id,
            room=ping.room,
            incident_type=ping.incident_type,
            initial_severity=ping.severity,
            current_severity=ping.severity,
            peak_severity=ping.severity,
            first_seen=now,
            last_seen=now,
        )
        incident._rng = random.Random(f"{self.seed}:{incident.incident_id}")
        self._next_id += 1
        self._active[key] = incident
        self.incidents.append(incident)
        return incident

    def active_waiting(self) -> list[Incident]:
        return [i for i in self._active.values() if i.status == "waiting"]

    def refresh_all(self, now: datetime) -> list[Incident]:
        """Advances starvation aging for every active incident. Returns
        whichever ones actually escalated this call (most calls: none) -
        purely observational, callers that ignore the return value (as every
        caller did before this) behave identically to before."""
        changed = []
        for incident in list(self._active.values()):
            if incident.refresh_starvation(now) is not None:
                changed.append(incident)
        return changed

    def dispatch(self, incident: Incident, now: datetime) -> None:
        incident.status = "in_progress"
        incident.dispatched_at = now
        incident.service_time = generate_service_time(incident.current_severity, self._service_rng)

    def resolve(self, incident: Incident, now: datetime) -> None:
        incident.status = "resolved"
        incident.resolved_at = now
        key = (incident.patient_id, incident.incident_type)
        if self._active.get(key) is incident:
            del self._active[key]
