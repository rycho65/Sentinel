from datetime import datetime, timedelta

from app.incidents import MAX_SEVERITY, IncidentManager
from app.models import RawPing

NOW = datetime(2026, 9, 19, 8, 0)


def ping(patient_id="P1", incident_type="LOW_SPO2", severity=4, minutes=0, technical=False):
    return RawPing(
        patient_id=patient_id, room="101", incident_type=incident_type,
        severity=severity, timestamp=NOW + timedelta(minutes=minutes), technical=technical,
    )


# 1. Same patient + same reason within the repeat window merges.
def test_same_patient_same_reason_merges():
    mgr = IncidentManager(seed=1)
    mgr.process_ping(ping(minutes=0), NOW)
    mgr.process_ping(ping(minutes=1), NOW + timedelta(minutes=1))
    mgr.process_ping(ping(minutes=2), NOW + timedelta(minutes=2))

    assert len(mgr.incidents) == 1
    incident = mgr.incidents[0]
    assert incident.repeat_count == 3


# 2. Same patient + different reason does not merge.
def test_same_patient_different_reason_does_not_merge():
    mgr = IncidentManager(seed=1)
    a = mgr.process_ping(ping(incident_type="LOW_SPO2"), NOW)
    b = mgr.process_ping(ping(incident_type="LOW_BP"), NOW)

    assert a.incident_id != b.incident_id
    assert len(mgr.incidents) == 2


# 3. Different patients do not merge.
def test_different_patients_do_not_merge():
    mgr = IncidentManager(seed=1)
    a = mgr.process_ping(ping(patient_id="P1"), NOW)
    b = mgr.process_ping(ping(patient_id="P2"), NOW)

    assert a.incident_id != b.incident_id
    assert len(mgr.incidents) == 2


# 4. A resolved incident recurring later creates a new incident.
def test_resolved_incident_recurring_creates_new_incident():
    mgr = IncidentManager(seed=1)
    first = mgr.process_ping(ping(minutes=0), NOW)
    mgr.dispatch(first, NOW + timedelta(minutes=5))
    mgr.resolve(first, NOW + timedelta(minutes=10))

    second = mgr.process_ping(ping(minutes=60), NOW + timedelta(minutes=60))

    assert second.incident_id != first.incident_id
    assert len(mgr.incidents) == 2


# 5. Severity-1 technical noise almost never starvation-escalates.
def test_severity_1_rarely_escalates():
    escalated = 0
    trials = 300
    for i in range(trials):
        mgr = IncidentManager(seed=i)
        incident = mgr.process_ping(
            RawPing(patient_id=f"P{i}", room="101", incident_type="SENSOR_DISCONNECT",
                     severity=1, timestamp=NOW, technical=True),
            NOW,
        )
        mgr.refresh_all(NOW + timedelta(minutes=300))  # 10 starvation windows
        if incident.escalation_count > 0:
            escalated += 1

    assert escalated / trials < 0.15  # "very rarely", not "never" and not "often"


# 6. Severity 2-10 CAN starvation-escalate while unresolved. Escalation is
#    deliberately gentle and stochastic (roughly a 1/3 chance of +1 and a
#    1/20 chance of +3 per 30-minute window, else no change) - so give it
#    many windows rather than asserting an exact value after just a couple.
def test_clinical_severity_can_starvation_escalate():
    mgr = IncidentManager(seed=1)
    incident = mgr.process_ping(ping(severity=2), NOW)

    mgr.refresh_all(NOW + timedelta(hours=10))  # 20 windows, P(no escalation) < 0.1%

    assert incident.current_severity > 2
    assert incident.severity_change_reason == "starvation"
    assert incident.escalation_count > 0


# 7. Severity never exceeds 10.
def test_severity_capped_at_ten():
    mgr = IncidentManager(seed=1)
    incident = mgr.process_ping(ping(severity=9), NOW)

    mgr.refresh_all(NOW + timedelta(hours=20))  # absurdly long wait

    assert incident.current_severity == MAX_SEVERITY


# 8. Starvation prevents an unresolved clinical incident from waiting forever
#    at the bottom of the queue - severity never DEcreases while waiting, and
#    a long enough wait eventually moves it, rather than it staying put.
def test_starvation_keeps_raising_priority_over_time():
    mgr = IncidentManager(seed=1)
    incident = mgr.process_ping(ping(severity=2), NOW)

    severities = []
    for minutes in (0, 60, 120, 180, 600):
        mgr.refresh_all(NOW + timedelta(minutes=minutes))
        severities.append(incident.current_severity)

    assert severities == sorted(severities)  # monotonic non-decreasing
    assert severities[-1] > severities[0]    # and it did eventually move


# 10. Physiological deterioration can independently increase severity (no
#     waiting time needed at all).
def test_physiology_can_increase_severity_immediately():
    mgr = IncidentManager(seed=1)
    incident = mgr.process_ping(ping(severity=3, minutes=0), NOW)

    worse = mgr.process_ping(ping(severity=7, minutes=0), NOW)  # same tick, no wait

    assert worse.incident_id == incident.incident_id
    assert incident.current_severity == 7
    assert incident.severity_change_reason == "physiology"


# 11. A starvation-escalated incident uses its NEW current-severity
#     service-time band when finally dispatched.
def test_dispatch_uses_current_severity_for_service_time(monkeypatch):
    mgr = IncidentManager(seed=1)
    incident = mgr.process_ping(ping(severity=2), NOW)
    mgr.refresh_all(NOW + timedelta(hours=10))  # escalates well past 2, P(none) < 0.1%
    escalated_severity = incident.current_severity
    assert escalated_severity > 2

    seen_severity = {}

    def fake_generate_service_time(severity, rng):
        seen_severity["value"] = severity
        return 42.0

    monkeypatch.setattr("app.incidents.generate_service_time", fake_generate_service_time)
    mgr.dispatch(incident, NOW + timedelta(hours=10))

    assert seen_severity["value"] == escalated_severity  # not the original severity of 2
    assert incident.service_time == 42.0
