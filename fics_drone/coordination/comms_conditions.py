"""The named conditions every Phase 10 experiment means the same thing by -
edit here to add or retune one. Numbers are experimental parameters for
comparing architectures under identical conditions, not claims about a real
radio; calibrating against an operational system is separate work.

Scoped to 3 named conditions, not FICS's 4: nominal, moderate, severe behave
exactly like FICS's own (latency/jitter/loss/rate-limit), but "partitioned"
is left out of the default set here, not because it isn't implemented
(`Partition` exists in network_model.py and is tested directly), but because
a *scenario-independent* partition window needs a real position/comms-range
notion this build doesn't have at the bus layer - FICS's own partitioned
condition is tied to its interference-zone geometry, which is out of scope
per the note in network_model.py. run_comms_study.py can still be pointed at
an ad-hoc Partition for a specific experiment; it just isn't one of the
three standing presets.
"""

from .network_model import NetworkProfile

NOMINAL = NetworkProfile(
    name="nominal",
    latency_ms_mean=20.0,
    latency_ms_jitter=10.0,
    packet_loss_probability=0.0,
    message_rate_limit=None,
)

MODERATE = NetworkProfile(
    name="moderate",
    latency_ms_mean=150.0,
    latency_ms_jitter=50.0,
    packet_loss_probability=0.10,
    message_rate_limit=None,
)

SEVERE = NetworkProfile(
    name="severe",
    latency_ms_mean=400.0,
    latency_ms_jitter=150.0,
    packet_loss_probability=0.30,
    message_rate_limit=4.0,
)

ORDER = ["nominal", "moderate", "severe"]
BY_NAME = {"nominal": NOMINAL, "moderate": MODERATE, "severe": SEVERE}
