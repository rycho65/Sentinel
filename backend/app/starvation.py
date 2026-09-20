"""Starvation-driven severity escalation - shared by every policy, not a
Sentinel-only trick. The idea: a patient problem that's been sitting
unresolved for a while can plausibly have actually gotten worse, whether or
not the scheduler watching it has any incident memory. FIFO and Greedy tasks
escalate exactly the same way Sentinel incidents do; Sentinel's real edge is
elsewhere (duplicate consolidation collapsing repeat pings into one
nurse-facing task, see app/incidents.py).

Deliberately gentle and stochastic: every 30 unresolved minutes, roll once -
most rolls do nothing. Not a deterministic "+1 every 30 minutes" ramp."""

import random
from datetime import datetime

STARVATION_INTERVAL_MINUTES = 30
MAX_SEVERITY = 10

# Per 30-minute window, for anything clinical (initial severity >= 2).
# Expected gain per window is ~0.24 severity points (1/6 * 1 + 1/40 * 3) - a
# fully-neglected 5-hour wait (10 windows) drifts up ~2-2.5 points on
# average, not the whole way to critical on its own.
STEP3_CHANCE = 1 / 40  # ~2.5% chance the condition takes a real turn, +3
STEP1_CHANCE = 1 / 6   # ~17% chance of a mild step, +1
# (the remaining ~81% of windows: no change at all)

# Severity 1 is mostly technical/nuisance noise (disconnected sensors,
# monitor glitches) - it should almost never escalate just because it waited.
SEVERITY_1_CHANCE = 0.005


def _roll_delta(rng: random.Random, severity1_exempt: bool) -> int:
    roll = rng.random()
    if severity1_exempt:
        return 1 if roll < SEVERITY_1_CHANCE else 0
    if roll < STEP3_CHANCE:
        return 3
    if roll < STEP3_CHANCE + STEP1_CHANCE:
        return 1
    return 0


def refresh_starvation(item, start_time: datetime, now: datetime) -> tuple[int, int] | None:
    """Advances `item`'s starvation clock in place, rolling once per
    30-minute window that has elapsed since it last checked. `item` needs:
    status, current_severity, initial_severity, escalation_count,
    peak_severity, severity_change_reason, _windows_checked, _rng. Works
    identically for a Sentinel Incident and a plain FIFO/Greedy Task.

    Returns (before, after) severity if this call actually changed
    anything, else None - used upstream to track bucket-crossing metrics."""
    if item.status != "waiting":
        return None

    elapsed = (now - start_time).total_seconds() / 60
    windows_elapsed = int(elapsed // STARVATION_INTERVAL_MINUTES)
    before = item.current_severity
    severity1_exempt = item.initial_severity <= 1
    rng = item._rng

    while item._windows_checked < windows_elapsed:
        item._windows_checked += 1
        if item.current_severity >= MAX_SEVERITY:
            continue
        delta = _roll_delta(rng, severity1_exempt)
        if delta:
            item.current_severity = min(MAX_SEVERITY, item.current_severity + delta)
            item.severity_change_reason = "starvation"
            item.escalation_count += delta
            item.peak_severity = max(item.peak_severity, item.current_severity)

    if item.current_severity > before:
        return before, item.current_severity
    return None


def bucket_for(severity: int) -> str:
    if severity <= 1:
        return "1"
    if severity <= 4:
        return "2-4"
    if severity <= 7:
        return "5-7"
    return "8-10"
