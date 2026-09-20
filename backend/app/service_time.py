import math
import random

# Target *average* service time per severity band, minutes - a log-normal draw
# around each mean, not a deterministic lookup, so an occasional severity-9
# incident resolves quickly and an occasional severity-2 incident runs long.
# Bands deliberately overlap in practice because the spread (sigma) is wide
# relative to the gap between consecutive means.
#
#   severity 1      avg ~5 min
#   severity 2-4     avg ~15 min, occasionally ~25-30
#   severity 5-7     avg ~30 min, occasionally ~60
#   severity 8-10    avg ~60 min, occasionally ~90
SEVERITY_BAND_MEANS = [
    (1, 5.0),
    (4, 15.0),
    (7, 30.0),
    (10, 60.0),
]

# Tuned so each band's tail lands near its stated "occasionally" ceiling above
# (verified by sampling), while keeping the mean at the target.
SERVICE_TIME_SIGMA = 0.5
MIN_SERVICE_MINUTES = 1.0  # a nurse is never in and out in under a minute


def _mean_for_severity(severity: int) -> float:
    for ceiling, mean_minutes in SEVERITY_BAND_MEANS:
        if severity <= ceiling:
            return mean_minutes
    return SEVERITY_BAND_MEANS[-1][1]


def generate_service_time(severity: int, rng: random.Random) -> float:
    """Log-normal draw whose *mean* (not median) matches the severity band's
    target. mu is solved from the log-normal mean formula E[X] = exp(mu + sigma^2/2)
    so SEVERITY_BAND_MEANS reads as actual expected minutes, not just a scale knob.

    Use the incident's CURRENT severity (not its initial severity) - a
    starvation-escalated or physiology-worsened incident is treated, and
    billed for nurse time, as whatever it has become by the time a nurse
    actually starts it."""
    mean_minutes = _mean_for_severity(severity)
    mu = math.log(mean_minutes) - (SERVICE_TIME_SIGMA ** 2) / 2
    minutes = rng.lognormvariate(mu, SERVICE_TIME_SIGMA)
    return max(MIN_SERVICE_MINUTES, minutes)
