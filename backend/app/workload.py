"""Generates the single shared, seeded raw-ping stream all three policies
replay. Nothing here is policy-specific and nothing here is clinically
validated - it's synthetic vitals in, synthetic pings out.

    N beds, seeded stochastic physiology
            v
    calculate_severity() / classify_incident_type()   (app/severity.py)
            v
    basic hysteresis/debounce (below threshold -> no ping)
            v
    list[RawPing], identical for FIFO, Greedy, and Sentinel
"""

import random
from datetime import datetime, timedelta

from app.models import RawPing
from app.severity import PatientState, calculate_severity, classify_incident_type

NOW = datetime(2026, 9, 19, 8, 0)

DEFAULT_SEED = 100
NUM_BEDS = 100
SHIFT_HOURS = 5
PINGS_PER_HOUR_RANGE = (20, 30)

ALERT_ON_SEVERITY = 4  # basic debounce: a routine reading never becomes a ping

# A minority of beds carry an ongoing clinical problem (chronic or worsening)
# and generate most of the *repeated* clinical pings - physiology genuinely
# evolves over the shift for these, ping over ping.
PROBLEM_BED_FRACTION = 0.2
PROBLEM_BED_PING_SHARE = 0.5

# A separate minority of beds are just flaky sensors: technical/nuisance
# noise, always severity 1, that fires in short bursts - the case Sentinel's
# duplicate consolidation is supposed to crush.
NOISE_BED_FRACTION = 0.1
NOISE_BED_PING_SHARE = 0.2


def stable_reading(rng: random.Random) -> PatientState:
    return PatientState(
        patient_id="",
        heart_rate=rng.randint(60, 95),
        oxygen_saturation=round(rng.uniform(94, 99), 1),
        systolic_bp=rng.randint(105, 135),
        respiratory_rate=rng.randint(13, 20),
        deterioration_rate=rng.choices([0.0, 0.1, 0.3], weights=[70, 20, 10])[0],
    )


def acute_blip_reading(rng: random.Random) -> PatientState:
    """A quiet bed's single genuinely abnormal reading - no ongoing pattern
    behind it, just a one-off real event."""
    secondary = rng.choice(["hr", "bp", "rr"])
    return PatientState(
        patient_id="",
        heart_rate=rng.randint(125, 150) if secondary == "hr" else rng.randint(65, 100),
        oxygen_saturation=round(rng.uniform(83, 89), 1),
        systolic_bp=rng.randint(160, 185) if secondary == "bp" else rng.randint(100, 140),
        respiratory_rate=rng.randint(25, 30) if secondary == "rr" else rng.randint(13, 20),
        deterioration_rate=rng.choices([0.1, 0.2, 0.3], weights=[50, 30, 20])[0],
    )


def chronic_mild_reading(rng: random.Random) -> PatientState:
    return PatientState(
        patient_id="",
        heart_rate=rng.randint(100, 118),
        oxygen_saturation=round(rng.uniform(90, 93), 1),
        systolic_bp=rng.randint(88, 98),
        respiratory_rate=rng.randint(21, 24),
        deterioration_rate=rng.choices([0.0, 0.1], weights=[70, 30])[0],
    )


def deteriorating_reading(rng: random.Random, progress: float) -> PatientState:
    # progress: 0.0 (near-normal) -> 1.0 (critical), with jitter on top - this
    # is where "physiology genuinely worsens" independent of any waiting time.
    return PatientState(
        patient_id="",
        heart_rate=int(85 + progress * 60 + rng.randint(-4, 4)),
        oxygen_saturation=round(max(78.0, 97 - progress * 18 + rng.uniform(-1, 1)), 1),
        systolic_bp=int(130 - progress * 55 + rng.randint(-5, 5)),
        respiratory_rate=int(16 + progress * 16 + rng.randint(-2, 2)),
        deterioration_rate=min(1.0, 0.1 + progress * 0.9),
    )


def _reading_to_ping(bed: str, room: str, state: PatientState, ts: datetime) -> RawPing | None:
    state.patient_id = bed
    severity = calculate_severity(state)
    if severity < ALERT_ON_SEVERITY:
        return None  # basic hysteresis/debounce, shared by every policy
    incident_type = classify_incident_type(state)
    return RawPing(patient_id=bed, room=room, incident_type=incident_type, severity=severity, timestamp=ts)


def generate_workload(
    seed: int = DEFAULT_SEED,
    num_beds: int = NUM_BEDS,
    shift_hours: float = SHIFT_HOURS,
    pings_per_hour_range: tuple[int, int] = PINGS_PER_HOUR_RANGE,
) -> tuple[list[RawPing], dict[str, str]]:
    """One deterministic run of this function, given the same arguments, is
    the fixed seeded workload every policy (FIFO/Greedy/Sentinel) replays."""
    rng = random.Random(seed)
    beds = [f"P{i + 1}" for i in range(num_beds)]
    rooms = {bed: str(101 + i) for i, bed in enumerate(beds)}

    num_problem = max(1, int(num_beds * PROBLEM_BED_FRACTION))
    problem_beds = rng.sample(beds, num_problem)
    archetype = {bed: ("deteriorating" if i % 2 == 0 else "chronic_mild") for i, bed in enumerate(problem_beds)}
    ping_count: dict[str, int] = {bed: 0 for bed in problem_beds}

    remaining = [b for b in beds if b not in problem_beds]
    num_noise = max(1, int(num_beds * NOISE_BED_FRACTION)) if remaining else 0
    noise_beds = rng.sample(remaining, min(num_noise, len(remaining))) if remaining else []

    pings: list[RawPing] = []
    for hour in range(int(shift_hours)):
        count = rng.randint(*pings_per_hour_range)
        offsets = sorted(rng.uniform(0, 60) for _ in range(count))
        for offset in offsets:
            ts = NOW + timedelta(minutes=hour * 60 + offset)
            roll = rng.random()

            if problem_beds and roll < PROBLEM_BED_PING_SHARE:
                bed = rng.choice(problem_beds)
                ping_count[bed] += 1
                progress = min(1.0, 0.3 + ping_count[bed] / 6)  # already noticeable by the first ping
                state = (
                    deteriorating_reading(rng, progress)
                    if archetype[bed] == "deteriorating"
                    else chronic_mild_reading(rng)
                )
                ping = _reading_to_ping(bed, rooms[bed], state, ts)
                if ping is not None:
                    pings.append(ping)

            elif noise_beds and roll < PROBLEM_BED_PING_SHARE + NOISE_BED_PING_SHARE:
                # Flaky sensor: a short burst of severity-1 technical noise
                # about the same bed, seconds to a couple minutes apart -
                # exactly the case duplicate consolidation should crush.
                bed = rng.choice(noise_beds)
                burst = rng.choices([1, 2, 3], weights=[40, 35, 25])[0]
                for k in range(burst):
                    pings.append(RawPing(
                        patient_id=bed,
                        room=rooms[bed],
                        incident_type="SENSOR_DISCONNECT",
                        severity=1,
                        timestamp=ts + timedelta(minutes=k * rng.uniform(0.3, 1.5)),
                        technical=True,
                    ))

            else:
                bed = rng.choice(beds)
                state = acute_blip_reading(rng)
                ping = _reading_to_ping(bed, rooms[bed], state, ts)
                if ping is not None:
                    pings.append(ping)

    pings.sort(key=lambda p: p.timestamp)
    return pings, rooms
