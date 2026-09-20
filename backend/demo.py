"""Deterministic FIFO vs Greedy vs Sentinel comparison over the default
Sentinel scenario: ~100 monitored beds, 5 nurses, a 5-hour rush, ~20-30 raw
pings/hour. All three policies replay the exact same seeded workload
(app/workload.py) - only the scheduling policy differs. Entirely synthetic;
not clinically validated.

Run with:  python demo.py
"""

from app.simulate import compute_metrics, run
from app.workload import (
    DEFAULT_SEED,
    NUM_BEDS,
    PINGS_PER_HOUR_RANGE,
    SHIFT_HOURS,
    generate_workload,
)

NURSES = 5


def fmt(value, unit=""):
    if value is None:
        return "n/a"
    if unit == "m":
        return f"{value:.1f}m"
    if unit == "%":
        return f"{value * 100:.0f}%"
    if unit == "x":
        return f"{value:.1f}"
    return str(value)


ROWS = [
    ("avg_wait", "Avg wait", "m"),
    ("sev_1", "  Sev 1", "m"),
    ("sev_2_4", "  Sev 2-4", "m"),
    ("sev_5_7", "  Sev 5-7", "m"),
    ("sev_8_10", "  Sev 8-10", "m"),
    ("worst_wait", "Worst wait", "m"),
    ("max_wait_sev_1", "Max wait, sev 1", "m"),
    ("max_wait_sev_2_4", "Max wait, sev 2-4", "m"),
    (None, None, None),
    ("raw_pings", "Raw pings", ""),
    ("nurse_facing_tasks", "Nurse-facing tasks", ""),
    ("active_incidents", "Active incidents", ""),
    ("duplicates_consolidated", "Duplicates consolidated", ""),
    (None, None, None),
    ("completed", "Completed", ""),
    ("remaining_backlog", "Remaining backlog", ""),
    ("max_backlog", "Max backlog", ""),
    ("avg_nurse_utilization", "Nurse utilization", "%"),
    (None, None, None),
    ("starvation_escalations", "Starvation escalations", ""),
    ("avg_escalation_count", "Avg escalation count", "x"),
    ("escalations_2to4_5to7", "  2-4 -> 5-7 escalations", ""),
    ("escalations_5to7_8to10", "  5-7 -> 8-10 escalations", ""),
]


def main() -> None:
    pings, rooms = generate_workload(seed=DEFAULT_SEED, num_beds=NUM_BEDS, shift_hours=SHIFT_HOURS,
                                      pings_per_hour_range=PINGS_PER_HOUR_RANGE)
    shift_minutes = SHIFT_HOURS * 60

    print(f"{SHIFT_HOURS}-hour rush: {NUM_BEDS} beds, {NURSES} nurses, {len(pings)} raw pings "
          f"(seed={DEFAULT_SEED}). Synthetic scenario, not clinically validated.\n")

    results = {}
    for mode in ("fifo", "greedy", "sentinel"):
        result = run(pings, NURSES, mode=mode, seed=DEFAULT_SEED, shift_minutes=shift_minutes)
        results[mode] = compute_metrics(result, NURSES, shift_minutes)

    policies = ["fifo", "greedy", "sentinel"]
    print(f"{'':<26}{'FIFO':>10}{'GREEDY':>12}{'SENTINEL':>12}")
    for key, label, unit in ROWS:
        if key is None:
            print()
            continue
        row = [fmt(results[p].get(key), unit) for p in policies]
        print(f"{label:<26}{row[0]:>10}{row[1]:>12}{row[2]:>12}")
    print()


if __name__ == "__main__":
    main()
