"""The network model, verified statistically (AUV-10, 10.6).

    report = check_condition(load_network("severe"), seed=17)   # every check below, on one condition
    report["all"]                                               # True only if every one held

AUV-10, 10.6: "Run thousands of mock messages and confirm: empirical loss
rate approximates the configured rate; empirical latency approximates the
specified distribution; partitions block only intended links; expired
messages are not delivered; identical seeds produce identical network
behaviour." No flight: heartbeats are driven through the real bus, on a
simulated clock, from the four canonical drones, and the bus's own record is
checked. Each check returns what it measured, what it was held to, and the
problems; each is shown able to fail in `tests/test_network_check.py`.

Two streams per condition: STEADY, every drone broadcasting once a second for
1000 s (12,000 deliveries), for loss, latency, partitions and expiry; and
BURST, four a second for 100 s, which presses the severe condition's rate
limit (two a second). And two networks built only for the check, since the
four conditions rarely reach these limits: SLOW (latency 3 ± 1 s, around a
heartbeat's 3 s lifetime), where many messages expire; and NARROW (500 bytes a
second, four a second sent), where every drone's send queue grows.

* LOSS: among deliveries the network decided by chance (not rate-limited,
  partitioned or out of range), the share lost, inside
  p ± 2.576 sqrt(p (1 - p) / n) -- a 99 % normal interval; with p = 0, none.
* LATENCY: each message's scheduled arrival less the moment it finished
  leaving its sender (recomputed here from the sizes and the bandwidth),
  against the configured distribution -- a normal of the mean and jitter,
  raised to the floor below it, so a point mass at the floor; the mean
  exactly with no jitter. A one-sample KS test at 1 % (D below
  1.628 / sqrt(n)), taken over distinct values, so ties and the point mass
  count as the steps they are.
* RATE LIMIT: every message's admission against a bucket of one second's
  worth, refilled at the rate and full at the start, recomputed here.
* PARTITIONS: every delivery's status against the partition's rule, pair by
  pair and instant by instant: cut across groups strictly inside the
  interval, and nowhere else.
* EXPIRY: no message delivered at or after its lifetime's end; every message
  scheduled to arrive at or past it, expired; nothing left pending.
* SEEDS: the same seed twice, the same record; the drones sending in the
  reverse order, the same record; another seed, another record (when the
  condition draws anything at all).
"""

from __future__ import annotations

import json
import math
from typing import Any

from ..core.clock import SimClock
from ..core.messages import BROADCAST, MessageType, new_message
from ..simulator.message_bus import (
    DELIVERED,
    EXPIRED,
    LOST,
    OUT_OF_RANGE,
    PARTITIONED,
    PENDING,
    RATE_LIMITED,
    MessageBus,
)
from ..simulator.network import NetworkModel

ROSTER = ("Drone1", "Drone2", "Drone3", "Drone4")
Z99 = 2.576                     # two-sided 99 % normal quantile
KS_1PCT = 1.628                 # the one-sample KS critical constant at 1 %
STEADY_PERIOD_S, STEADY_S = 1.0, 1000.0
BURST_PERIOD_S, BURST_S = 0.25, 100.0
STATUSES = (DELIVERED, LOST, RATE_LIMITED, PARTITIONED, EXPIRED, OUT_OF_RANGE, PENDING)
STEP_TOL_S = 1e-9              # a latency measured back from two clock readings is that close to what was drawn
LEFT_LIMIT_S = 1e-6            # "just before" a value, for the KS test: below any step's allowance


def _beat(sender: str, seq: int, at: float) -> Any:
    return new_message(MessageType.HEARTBEAT, sender, BROADCAST, "check", at, seq,
                       {"position": [0.0, 0.0, 10.0], "airborne": True, "battery": 90.0, "task": None, "stage": None})


def size_of(message: Any) -> int:
    return len(json.dumps(message.as_json()).encode("utf-8"))


def send_stream(model: NetworkModel, seed: int, period_s: float = STEADY_PERIOD_S, duration_s: float = STEADY_S,
                reverse: bool = False, roster: tuple[str, ...] = ROSTER) -> dict[str, Any]:
    """Every drone broadcasting a heartbeat every `period_s` for `duration_s`, read twice a period; then drained."""
    clock = SimClock()
    bus = MessageBus(roster, clock, lambda d: (0.0, 0.0, 10.0), None, mission_id="check", network=model.seeded(seed))
    order = tuple(reversed(roster)) if reverse else roster
    for k in range(int(round(duration_s / period_s))):
        for d in order:
            bus.comms(d).send(_beat(d, k + 1, clock.now()))
        for _ in range(2):
            clock.advance(period_s / 2)
            for d in roster:
                bus.comms(d).receive_available()
    clock.advance(600.0)                          # everything still in the air arrives, or expires
    for d in roster:
        bus.comms(d).receive_available()
    return {"model": model.seeded(seed), "start": bus.start, "deliveries": bus.deliveries()}


def canonical(deliveries: Any) -> list[tuple]:
    return sorted((d.sent_at, d.message.sender_id, d.message.sequence_number, d.recipient, d.scheduled_at, d.status,
                   d.delivered_at) for d in deliveries)


def statuses(stream: dict[str, Any]) -> dict[str, int]:
    return {s: sum(d.status == s for d in stream["deliveries"]) for s in STATUSES}


# ------------------------------------------------------------------ checks

def loss_check(stream: dict[str, Any]) -> dict[str, Any]:
    p = stream["model"].loss_probability
    decided = [d for d in stream["deliveries"] if d.status not in (RATE_LIMITED, PARTITIONED, OUT_OF_RANGE)]
    n = len(decided)
    lost = sum(d.status == LOST for d in decided)
    rate = lost / n if n else float("nan")
    half = Z99 * math.sqrt(p * (1 - p) / n) if n else float("nan")
    ok = n > 0 and (lost == 0 if p == 0 else abs(rate - p) <= half)
    return {"n": n, "lost": lost, "rate": round(rate, 5), "configured": p,
            "interval": [round(p - half, 5), round(p + half, 5)], "ok": ok,
            "problems": [] if ok else [f"loss {rate:.4f} over {n} outside {p} ± {half:.4f}"]}


def latency_cdf(x: float, mean: float, jitter: float, floor: float) -> float:
    """The configured latency's CDF: a normal raised to the floor below it; the mean exactly with no jitter.

    A latency is measured back as arrival less departure, two clock readings, so one drawn at exactly the
    floor (or the mean, with no jitter) comes back a hair either side of it: within STEP_TOL_S it is there.
    """
    if jitter == 0:
        return 1.0 if x >= mean - STEP_TOL_S else 0.0
    if x < floor - STEP_TOL_S:
        return 0.0
    return 0.5 * (1.0 + math.erf((x - mean) / (jitter * math.sqrt(2.0))))


def latencies(stream: dict[str, Any]) -> list[float]:
    """Each message's latency, per recipient: scheduled arrival less when it finished leaving its sender."""
    bw = stream["model"].bandwidth_bytes_per_s
    left: dict[tuple[str, int], float] = {}
    busy: dict[str, float] = {}
    out = []
    for d in sorted(stream["deliveries"], key=lambda d: (d.sent_at, d.message.sender_id, d.message.sequence_number)):
        if d.status == RATE_LIMITED:              # never sent: never queued
            continue
        key = (d.message.sender_id, d.message.sequence_number)
        if key not in left:                       # once per transmission, not per recipient
            begin = max(d.sent_at, busy.get(key[0], d.sent_at))
            left[key] = begin + size_of(d.message) / bw if bw else d.sent_at
            busy[key[0]] = left[key]
        if d.scheduled_at is not None:
            # to the nanosecond: two clock readings apart, a latency drawn at the floor comes back a hair either
            # side of it, and the same draw must come back as the same value, or a tie looks like a spread
            out.append(round(d.scheduled_at - left[key], 9))
    return out


def ks_statistic(xs: list[float], cdf: Any) -> float:
    """The one-sample KS D, over distinct values: the empirical CDF jumps once at each, by all its ties."""
    xs = sorted(xs)
    n = len(xs)
    d_stat, i = 0.0, 0
    while i < n:
        j = i
        while j < n and xs[j] == xs[i]:
            j += 1
        x = xs[i]
        # against F at x, and F just before x -- far enough back to fall below a step's allowance
        d_stat = max(d_stat, abs(j / n - cdf(x)), abs(i / n - cdf(x - LEFT_LIMIT_S)))
        i = j
    return d_stat


def latency_check(stream: dict[str, Any]) -> dict[str, Any]:
    m = stream["model"]
    xs = latencies(stream)
    n = len(xs)
    if not n:
        return {"n": 0, "ok": False, "problems": ["no latencies"]}
    d_stat = ks_statistic(xs, lambda x: latency_cdf(x, m.latency_mean_s, m.latency_jitter_s, m.latency_floor_s))
    critical = KS_1PCT / math.sqrt(n)
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / n)
    ok = d_stat <= critical
    return {"n": n, "mean_s": round(mean, 4), "sd_s": round(sd, 4),
            "configured": {"mean_s": m.latency_mean_s, "jitter_s": m.latency_jitter_s, "floor_s": m.latency_floor_s},
            "at_floor": round(sum(1 for x in xs if abs(x - m.latency_floor_s) < 1e-9) / n, 4),
            "ks_d": round(d_stat, 5), "critical": round(critical, 5), "ok": ok,
            "problems": [] if ok else [f"KS D {d_stat:.4f} above {critical:.4f} over {n}"]}


def rate_check(stream: dict[str, Any]) -> dict[str, Any]:
    """Every message's admission against the bucket, recomputed here."""
    model, start = stream["model"], stream["start"]
    rate = model.rate_limit_per_s
    # A message is refused to everyone or to no one: all its deliveries, one per recipient, are looked at.
    sends: dict[str, dict[int, tuple[float, set[bool]]]] = {}
    for d in stream["deliveries"]:
        at, seen = sends.setdefault(d.message.sender_id, {}).setdefault(d.message.sequence_number, (d.sent_at, set()))
        seen.add(d.status == RATE_LIMITED)
    problems, refused = [], 0
    for sender, by_seq in sorted(sends.items()):
        tokens, last = (rate or 0.0), start
        for seq in sorted(by_seq):
            at, seen = by_seq[seq]
            if len(seen) > 1:
                problems.append(f"{sender}#{seq}: refused to some recipients and not others")
            was_refused = True in seen
            expect = False
            if rate is not None:
                tokens = min(rate, tokens + (at - last) * rate)
                last = at
                expect = tokens < 1.0 - 1e-9
                if not expect:
                    tokens -= 1.0
            refused += was_refused
            if expect != was_refused:
                problems.append(f"{sender}#{seq} at {at - start:g} s: {'refused' if was_refused else 'admitted'}, "
                                f"the bucket says {'refuse' if expect else 'admit'}")
    return {"messages": sum(len(v) for v in sends.values()), "refused": refused, "rate_per_s": rate,
            "ok": not problems, "problems": problems[:20]}


def partition_check(stream: dict[str, Any]) -> dict[str, Any]:
    model, start = stream["model"], stream["start"]
    problems, cut = [], 0
    for d in stream["deliveries"]:
        should = model.partitioned(d.message.sender_id, d.recipient, d.sent_at - start)
        is_cut = d.status == PARTITIONED
        cut += is_cut
        if should != is_cut:
            problems.append(f"{d.message.message_id} to {d.recipient} at {d.sent_at - start:g} s: "
                            f"{d.status}, the partition says {'cut' if should else 'not cut'}")
    return {"deliveries": len(stream["deliveries"]), "cut": cut, "ok": not problems, "problems": problems[:20]}


def expiry_check(stream: dict[str, Any]) -> dict[str, Any]:
    problems, expired = [], 0
    for d in stream["deliveries"]:
        expired += d.status == EXPIRED
        if d.status == DELIVERED and d.message.expired(d.delivered_at):
            problems.append(f"{d.message.message_id} to {d.recipient} delivered at {d.delivered_at:g}, past its lifetime")
        if d.status == PENDING:
            problems.append(f"{d.message.message_id} to {d.recipient} still pending after the drain")
        if d.scheduled_at is not None and d.message.expired(d.scheduled_at) and d.status != EXPIRED:
            problems.append(f"{d.message.message_id} to {d.recipient} arrived past its lifetime, yet {d.status}")
    return {"deliveries": len(stream["deliveries"]), "expired": expired, "ok": not problems, "problems": problems[:20]}


def seed_check(model: NetworkModel, seed: int, duration_s: float = 200.0) -> dict[str, Any]:
    first = canonical(send_stream(model, seed, duration_s=duration_s)["deliveries"])
    again = canonical(send_stream(model, seed, duration_s=duration_s)["deliveries"])
    flipped = canonical(send_stream(model, seed, duration_s=duration_s, reverse=True)["deliveries"])
    other = canonical(send_stream(model, seed + 1, duration_s=duration_s)["deliveries"])
    draws = model.loss_probability > 0 or model.latency_jitter_s > 0
    problems = []
    if first != again:
        problems.append("the same seed gave another record")
    if first != flipped:
        problems.append("the drones sending in the reverse order gave another record")
    if draws and first == other:
        problems.append("another seed gave the same record")
    return {"same_seed_same": first == again, "order_free": first == flipped,
            "other_seed_differs": (first != other) if draws else None, "ok": not problems, "problems": problems}


def check_condition(model: NetworkModel, seed: int, duration_s: float = STEADY_S, burst_s: float = BURST_S) -> dict[str, Any]:
    """Every check of 10.6 on one condition: the steady stream, the burst, and the seeds."""
    steady = send_stream(model, seed, duration_s=duration_s)
    burst = send_stream(model, seed, period_s=BURST_PERIOD_S, duration_s=burst_s)
    out: dict[str, Any] = {
        "condition": model.name, "seed": seed, "steady": statuses(steady), "burst": statuses(burst),
        "loss": loss_check(steady), "latency": latency_check(steady), "rate_limit": rate_check(burst),
        "partitions": partition_check(steady), "expiry": expiry_check(steady),
        "seeds": seed_check(model, seed, duration_s=min(duration_s, 200.0)),
    }
    out["all"] = all(out[k]["ok"] for k in ("loss", "latency", "rate_limit", "partitions", "expiry", "seeds"))
    return out


def slow_model() -> NetworkModel:
    """Built only for the check: latency around a heartbeat's 3 s lifetime, so many messages expire."""
    return NetworkModel("slow", latency_mean_s=3.0, latency_jitter_s=1.0)


def narrow_model() -> NetworkModel:
    """Built only for the check: 500 bytes a second, so a drone sending four a second queues."""
    return NetworkModel("narrow", latency_mean_s=0.2, latency_jitter_s=0.05, bandwidth_bytes_per_s=500.0)


def check_stress(seed: int, burst_s: float = BURST_S) -> dict[str, Any]:
    """Expiry where many expire; latency where every send queue grows."""
    slow = send_stream(slow_model(), seed, duration_s=burst_s * 4)
    narrow = send_stream(narrow_model(), seed, period_s=BURST_PERIOD_S, duration_s=burst_s)
    out = {"slow": {"statuses": statuses(slow), "expiry": expiry_check(slow), "latency": latency_check(slow)},
           "narrow": {"statuses": statuses(narrow), "latency": latency_check(narrow), "expiry": expiry_check(narrow)}}
    out["all"] = all(v[k]["ok"] for v in out.values() for k in ("expiry", "latency")) \
        and out["slow"]["statuses"][EXPIRED] > 0
    return out
