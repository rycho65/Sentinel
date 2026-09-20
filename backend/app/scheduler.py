"""Dispatch-time policy only. Whenever a nurse becomes available, `decide()`
inspects whatever's currently eligible and picks one - no continuous sorting,
no holding a nurse idle to wait for more pings. Every policy is
work-conserving: if a nurse is free and unresolved work exists, it dispatches
immediately.

Greedy and Sentinel are both "pick highest current severity first" at this
exact point - and both now benefit from starvation-driven escalation
(app/starvation.py), since a neglected problem can plausibly worsen no
matter who's scheduling it. Sentinel's real, sole edge is upstream in
app/incidents.py: duplicate consolidation, so a patient re-pinging about the
same problem costs one nurse-facing task instead of several."""

from datetime import datetime


def pick_fifo(waiting: list) -> object:
    """Oldest arrival wins, ignoring severity entirely."""
    return min(waiting, key=_arrival_time)


def pick_greedy(waiting: list) -> object:
    """Highest current severity wins; oldest arrival breaks ties. Treats
    every item independently - no consolidation, so a patient re-pinging
    about the same problem shows up as several separate tasks competing for
    a nurse instead of one."""
    return max(waiting, key=lambda item: (item.current_severity, -_arrival_time(item).timestamp()))


def pick_sentinel(waiting: list) -> object:
    """Highest current severity wins; oldest first_seen breaks ties -
    mechanically identical to Greedy's pick. The difference already happened
    upstream: `waiting` here is Sentinel's consolidated incident table, not
    raw pings."""
    return max(waiting, key=lambda item: (item.current_severity, -_arrival_time(item).timestamp()))


def _arrival_time(item) -> datetime:
    return getattr(item, "first_seen", None) or item.created_at


_PICKERS = {
    "fifo": pick_fifo,
    "greedy": pick_greedy,
    "sentinel": pick_sentinel,
}


def decide(mode: str, waiting: list, current_time: datetime):
    """Pick the single item a just-freed nurse should take next, or None if
    nothing eligible is waiting. No per-nurse state, no window to hold open -
    every call is a fresh, independent look at what's currently eligible."""
    if not waiting:
        return None
    picker = _PICKERS.get(mode)
    if picker is None:
        raise ValueError(f"unknown scheduling mode: {mode!r}")
    return picker(waiting)
