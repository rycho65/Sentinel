import random
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RawPing:
    """One raw patient-monitoring ping, straight off the synthetic vitals
    stream - the same event every policy (FIFO/Greedy/Sentinel) starts from."""
    patient_id: str
    room: str
    incident_type: str   # reason, e.g. "LOW_SPO2", "SENSOR_DISCONNECT"
    severity: int         # 1-10, from physiology at the moment of this ping
    timestamp: datetime
    technical: bool = False  # True for nuisance/sensor noise, not real physiology


@dataclass
class Task:
    """A nurse-facing unit of work for FIFO/Greedy: one raw ping, un-merged -
    unlike a Sentinel Incident, a Task never consolidates with another ping
    about the same patient/reason. It DOES still starve like an Incident does
    (see app/starvation.py) - prolonged neglect can worsen a real problem no
    matter which policy is watching it. That's not a Sentinel-only trick;
    Sentinel's actual edge is duplicate consolidation."""
    id: str
    patient_id: str
    room: str
    incident_type: str

    initial_severity: int
    current_severity: int
    peak_severity: int

    created_at: datetime
    status: str = "waiting"    # waiting | in_progress | resolved
    service_time: float | None = None

    severity_change_reason: str = "none"   # "physiology" | "starvation" | "none"
    escalation_count: int = 0

    _windows_checked: int = field(default=0, repr=False)
    _rng: random.Random = field(default=None, repr=False)

    @property
    def severity(self) -> int:
        """Back-compat alias - a Task's severity IS its current_severity."""
        return self.current_severity

    def waiting_minutes(self, current_time: datetime) -> float:
        return (current_time - self.created_at).total_seconds() / 60


def ping_to_task(index: int, ping: RawPing, seed_key: str = "0") -> Task:
    task = Task(
        id=f"T{index + 1}",
        patient_id=ping.patient_id,
        room=ping.room,
        incident_type=ping.incident_type,
        initial_severity=ping.severity,
        current_severity=ping.severity,
        peak_severity=ping.severity,
        created_at=ping.timestamp,
    )
    task._rng = random.Random(f"{seed_key}:{task.id}")
    return task
