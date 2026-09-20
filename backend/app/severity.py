from dataclasses import dataclass


@dataclass
class PatientState:
    patient_id: str
    heart_rate: int             # bpm, normal ~60-100
    oxygen_saturation: float    # %, normal >= 95
    systolic_bp: int            # mmHg, normal ~100-140
    respiratory_rate: int       # breaths/min, normal ~12-20
    deterioration_rate: float   # 0.0 = stable, 1.0 = rapidly worsening


def _oxygen_risk(spo2: float) -> float:
    if spo2 >= 95:
        return 0.0
    if spo2 >= 92:
        return 0.3
    if spo2 >= 88:
        return 0.6
    return 1.0


def _heart_rate_risk(hr: int) -> tuple[float, str]:
    if 60 <= hr <= 100:
        return 0.0, "HIGH_HR"
    direction = "LOW_HR" if hr < 60 else "HIGH_HR"
    if 50 <= hr < 60 or 100 < hr <= 120:
        return 0.3, direction
    if 40 <= hr < 50 or 120 < hr <= 140:
        return 0.6, direction
    return 1.0, direction


def _blood_pressure_risk(systolic: int) -> tuple[float, str]:
    if 100 <= systolic <= 140:
        return 0.0, "HIGH_BP"
    direction = "LOW_BP" if systolic < 100 else "HIGH_BP"
    if 90 <= systolic < 100 or 140 < systolic <= 160:
        return 0.3, direction
    if 80 <= systolic < 90 or 160 < systolic <= 180:
        return 0.6, direction
    return 1.0, direction


def _respiratory_risk(rr: int) -> tuple[float, str]:
    if 12 <= rr <= 20:
        return 0.0, "HIGH_RR"
    direction = "LOW_RR" if rr < 12 else "HIGH_RR"
    if 9 <= rr < 12 or 20 < rr <= 24:
        return 0.3, direction
    if rr < 9 or 24 < rr <= 29:
        return 0.6, direction
    return 1.0, direction


# How much each factor contributes to overall severity. Deterioration gets real
# weight on purpose: a patient worsening quickly should be able to outscore someone
# whose vitals are abnormal but holding steady, not just get a small bonus tacked on.
WEIGHTS = {
    "oxygen": 0.30,
    "heart_rate": 0.20,
    "blood_pressure": 0.15,
    "respiratory": 0.15,
    "deterioration": 0.20,
}


def calculate_severity(state: PatientState) -> int:
    """Simple rule-based severity score, 1 (fine) to 10 (critical).
    Not a clinically validated scoring system - simulation only."""
    risk = (
        WEIGHTS["oxygen"] * _oxygen_risk(state.oxygen_saturation)
        + WEIGHTS["heart_rate"] * _heart_rate_risk(state.heart_rate)[0]
        + WEIGHTS["blood_pressure"] * _blood_pressure_risk(state.systolic_bp)[0]
        + WEIGHTS["respiratory"] * _respiratory_risk(state.respiratory_rate)[0]
        + WEIGHTS["deterioration"] * state.deterioration_rate
    )
    score = 1 + risk * 9
    return max(1, min(10, round(score)))


def classify_incident_type(state: PatientState) -> str:
    """Which vital is actually driving this reading's severity - becomes the
    Sentinel incident's `incident_type`, i.e. the (patient_id, incident_type)
    key duplicate pings get consolidated under. Not clinically validated."""
    hr_risk, hr_dir = _heart_rate_risk(state.heart_rate)
    bp_risk, bp_dir = _blood_pressure_risk(state.systolic_bp)
    rr_risk, rr_dir = _respiratory_risk(state.respiratory_rate)

    contributions = {
        "LOW_SPO2": WEIGHTS["oxygen"] * _oxygen_risk(state.oxygen_saturation),
        hr_dir: WEIGHTS["heart_rate"] * hr_risk,
        bp_dir: WEIGHTS["blood_pressure"] * bp_risk,
        rr_dir: WEIGHTS["respiratory"] * rr_risk,
        "DETERIORATION": WEIGHTS["deterioration"] * state.deterioration_rate,
    }
    incident_type = max(contributions, key=contributions.get)
    if contributions[incident_type] <= 0:
        return "ROUTINE_CHECK"
    return incident_type
