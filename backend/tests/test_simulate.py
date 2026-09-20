import copy

from app.simulate import compute_metrics, run
from app.workload import generate_workload

SEED = 100


# 13. All three policies replay the exact same seeded starting workload.
def test_same_seed_produces_identical_workload():
    pings_a, rooms_a = generate_workload(seed=SEED, num_beds=30, shift_hours=2, pings_per_hour_range=(10, 15))
    pings_b, rooms_b = generate_workload(seed=SEED, num_beds=30, shift_hours=2, pings_per_hour_range=(10, 15))

    assert rooms_a == rooms_b
    assert len(pings_a) == len(pings_b) and len(pings_a) > 0
    for a, b in zip(pings_a, pings_b):
        assert (a.patient_id, a.room, a.incident_type, a.severity, a.timestamp) == \
               (b.patient_id, b.room, b.incident_type, b.severity, b.timestamp)


def test_all_three_policies_start_from_the_same_pings():
    pings, _ = generate_workload(seed=SEED, num_beds=30, shift_hours=2, pings_per_hour_range=(10, 15))
    snapshot = copy.deepcopy(pings)

    for mode in ("fifo", "greedy", "sentinel"):
        run(pings, num_nurses=3, mode=mode, seed=SEED, shift_minutes=120)
        # run() must never mutate the shared input ping stream.
        for original, after in zip(snapshot, pings):
            assert (original.patient_id, original.incident_type, original.severity, original.timestamp) == \
                   (after.patient_id, after.incident_type, after.severity, after.timestamp)


def test_sentinel_consolidates_far_fewer_nurse_facing_tasks_than_raw_pings():
    pings, _ = generate_workload(seed=SEED, num_beds=100, shift_hours=5, pings_per_hour_range=(20, 30))

    result = run(pings, num_nurses=5, mode="sentinel", seed=SEED, shift_minutes=300)

    assert result.raw_pings == len(pings)
    assert result.nurse_facing_tasks < result.raw_pings
    assert result.duplicates_consolidated == result.raw_pings - result.nurse_facing_tasks


def test_fifo_and_greedy_have_one_task_per_raw_ping():
    pings, _ = generate_workload(seed=SEED, num_beds=100, shift_hours=5, pings_per_hour_range=(20, 30))

    for mode in ("fifo", "greedy"):
        result = run(pings, num_nurses=5, mode=mode, seed=SEED, shift_minutes=300)
        assert result.nurse_facing_tasks == len(pings)


def test_sentinel_run_reports_starvation_metrics():
    pings, _ = generate_workload(seed=SEED, num_beds=100, shift_hours=5, pings_per_hour_range=(20, 30))
    result = run(pings, num_nurses=5, mode="sentinel", seed=SEED, shift_minutes=300)
    metrics = compute_metrics(result, num_nurses=5, shift_minutes=300)

    for key in ("active_incidents", "duplicates_consolidated", "starvation_escalations", "avg_escalation_count"):
        assert key in metrics

    # FIFO/Greedy metrics never carry Sentinel-only incident bookkeeping.
    fifo_result = run(pings, num_nurses=5, mode="fifo", seed=SEED, shift_minutes=300)
    fifo_metrics = compute_metrics(fifo_result, num_nurses=5, shift_minutes=300)
    assert "active_incidents" not in fifo_metrics
