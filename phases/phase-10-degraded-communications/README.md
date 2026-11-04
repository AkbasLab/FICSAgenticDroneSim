# Phase 10 — Build the degraded-communications simulator

**Stage:** 4 · Adversity · **Vault note:** `AUV-10 — Degraded Communications`
**Started:** 2026-11-04 · **Completed:** —

> Phases 7–9 flew with every message delivered: a stopped drone's silence was
> the only silence. Phase 10 builds the network the central claim depends on
> -- latency, loss, limits and partitions, each seeded so the same mission
> replays with the same messages lost -- and lets the agents estimate how
> their links are doing without ever reading how they were configured. Until
> it exists, "decentralization holds up under degraded communications" cannot
> be tested.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [ ] **10.1** Implement a configurable network model — latency mean and jitter, packet loss, message rate limit, bandwidth, communication range
- [ ] **10.2** Support four communication conditions — Nominal, Moderately degraded (~10% loss), Severely degraded (~30% loss), Partitioned
- [ ] **10.3** Use a seeded random-number generator — same seed ⇒ same lost messages, same latency samples, same target placement, same failure time
- [ ] **10.4** Add message expiration — TTL per message class
- [ ] **10.5** Let agents estimate communication health — from heartbeat rate, round-trip time, missing sequence numbers, delivery acknowledgments; **never read the configured loss rate**
- [ ] **10.6** Verify the network model statistically — thousands of mock messages; empirical loss and latency match configuration; partitions block only intended links; expired messages not delivered; identical seeds reproduce

## Exit criterion

> The same mission can be replayed under nominal, degraded, severe and
> partitioned conditions with **reproducible message delivery**.

**Met:** no · **Evidence:** —

Planned evidence: the canonical four-drone mission with Phase 9's agents,
seeds 1–20, under each of the four conditions, with no stop and with Drone1
stopped at 60 s, every flight flown twice -- every message's fate and time
identical between the two; each condition applied as its manifest says;
nominal reproducing Phase 9 exactly. How the team fared under each condition
reported beside it, as findings.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| The network model (10.1, 10.3); the four conditions (10.2) | `agentic_uav/simulator/network.py`, `agentic_uav/experiments/conditions.py`, `configs/network/`, `agentic_uav/simulator/message_bus.py` | **Done** 2026-11-04; goldens unedited; Phases 5–9 reproduce |
| Message lifetimes (10.4) | `configs/network/lifetimes.toml`, `agentic_uav/core/messages.py` | step 2 |
| Link-health estimates (10.5) | `agentic_uav/agents/belief_state.py` | step 3 |
| Statistical verification (10.6) | `scripts/network_check.py`, `results/`, `evidence/` | step 4 |
| The exit | `agentic_uav/experiments/network_exit.py`, `scripts/network_exit.py`, `results/`, `evidence/` | step 5 |

## Plan

Approved 2026-11-04 with all seven recommendations, after it had been shown in
full; the user asked for the whole plan to be built, each step committed, and
to be asked before anything is pushed. The four Phase 2 goldens must pass
unedited after every step, and Phases 5–9's runs of record must still
reproduce.

1. **The network model (10.1, 10.3).** `simulator/network.py`: latency (mean,
   jitter, a floor), loss, a per-drone message rate limit, bandwidth (time to
   send, from a message's size), range, partitions (named groups, an interval,
   the base on one side); the conditions as manifests
   (`configs/network/{nominal,moderate,severe,partitioned}.toml`), fixed before
   any run. The bus takes a model; every message that does not arrive is
   recorded with why -- lost, rate-limited, partitioned, out of range, expired.
   Without a model the bus is exactly what it was, so every earlier record
   reproduces.
2. **Message lifetimes (10.4).** The lifetime table into a manifest, the same
   values; expired messages counted per condition; a "stale-message decisions"
   diagnostic -- decisions that read a teammate's record past its lifetime --
   which must be zero by construction, and is checked.
3. **Agents estimate their own links (10.5).** Per teammate, over a recent
   window: heartbeat arrival rate, loss from missing sequence numbers,
   latency, round-trip time on acknowledged contract-net claims -- in the
   belief, its sources known to the knowledge log; a boundary test that agent
   code cannot reach the network manifest; how close the estimates come to
   the configured values, reported.
4. **Statistical verification (10.6).** `scripts/network_check.py`: thousands
   of mock messages per condition -- loss within its binomial interval,
   latency against its distribution (a KS test, our own), partitions blocking
   only their links and only in their interval, nothing expired delivered,
   the same seed the same behaviour, another seed another. Evidence generated
   from the record.
5. **The exit.** The canonical four-drone mission, Phase 9's agents, seeds
   1–20, each condition, with no stop and with Drone1 stopped at 60 s, every
   flight flown twice. Pass: reproducible delivery (every message's fate and
   time identical between the two); each condition as configured; nominal
   reproducing Phase 9 exactly. Findings, not pass conditions: how the team
   fared under each.
6. **Close.** Records, vault report, memory; ask before tagging and pushing.

**The seven recommendations:**

1. **Build and verify the network, let agents estimate it; do not change how
   agents act on it.** The bid's communication-risk weight stays 0, the
   ladder's thresholds stay; how the team copes is recorded as findings --
   adapting is the experiment's.
2. **Range unlimited between drones in all four conditions**, so the condition
   is the only thing that varies; the canonical 100 m radio stays Phase 8's
   finding, and the base link keeps the scenario's range, as in Phases 8–9.
3. **The levels**, fixed in manifests and named levels of an experimental
   factor, not claims about any radio (calibrated later by AUV-16's pilots):
   nominal 0.1 s fixed, no loss; moderate 0.3 ± 0.1 s, 10 %; severe 1.0 ± 0.5 s,
   30 %, 2 messages/s per drone, 4 kB/s; partitioned nominal plus {Drone1,
   Drone2, base} cut from {Drone3, Drone4} from 60 to 120 s.
4. **Randomness keyed per message** -- by seed, sender, recipient and sequence
   number -- so thread order cannot change a fate, and the same message
   meets the same fate across architectures.
5. **The base link through the same model**: a partition can cut a group from
   the base; loss and latency are for messages between drones, the base link
   is reachability only (the base is not an agent on the bus).
6. **On the mock only; no live flight this phase.** The network is our code;
   CarlaAir adds nothing to delivery, and a real clock cannot replay it.
7. **Drone1 stopped at 60 s in every condition**, as 10.3 asks (the same
   failure at the same time), which also shows Phase 9's ladder under loss
   and partition.

## Record

### 2026-11-04 — the plan, shown before it was approved

The plan above was written out in full in the message that asked for its
approval, and approved with all seven recommendations; the user asked for the
whole plan to be built. The live flights of Phases 8 and 9 are left for the
user to fly later.

**One part of recommendation 5 settled in building it.** The mission brief
hands the agents the scenario's network block, so a partition schedule written
into the scenario would reach them. The model -- partitions included -- is
handed separately to the bus, the base-link sensing, the evaluator and the
knowledge log's truth, and never to an agent.

### 2026-11-04 — step 1: the network model (10.1, 10.2, 10.3)

**`simulator/network.py`**: a `NetworkModel` -- latency (mean, jitter, a
floor), loss, a rate limit, bandwidth, range, partitions -- and a drone's
`Transmitter` (its rate-limit bucket and its send queue). **The four
conditions** are manifests in `configs/network/`, read strictly by
`experiments/conditions.py`, at the levels the plan fixed:

| Condition | Latency | Loss | Limits | Partition |
|---|---|---|---|---|
| nominal | 0.1 s | 0 | -- | -- |
| moderate | 0.3 ± 0.1 s | 10 % | -- | -- |
| severe | 1.0 ± 0.5 s | 30 % | 2 messages/s, 4 kB/s | -- |
| partitioned | 0.1 s | 0 | -- | {Drone1, Drone2, base} / {Drone3, Drone4}, 60–120 s |

* **Latency** never falls below its floor (0.05 s), so a message never arrives
  at the instant it was sent -- Phase 7's determinism rule, kept; without
  jitter it is the mean exactly.
* **Keyed per message** (10.3): whether a message to a recipient is lost, and
  its latency, come from a generator seeded with the condition, the
  experiment's seed, the sender, the recipient and the sequence number -- not
  one shared stream -- so the order threads send in cannot change a fate.
  Both draws are always taken, so one never shifts the other.
* **The rate limit** is a bucket holding one second's worth, full at the start;
  a broadcast is one transmission; over the limit a message reaches nobody
  (`rate_limited`). **Bandwidth** queues a drone's messages behind each other,
  each taking its JSON size over the bandwidth.
* **Partitions** are judged at sending, like range: a message in the air
  when one begins still arrives.

**The bus** (`simulator/message_bus.py`) takes a seeded model; every message
that does not arrive is recorded with why -- `lost`, `rate_limited`,
`partitioned`, `out_of_range`, `expired`. With no model it is exactly Phase 7's.

**The base link through the same model.** A partition cuts a link between
its groups wherever the base link is judged: a drone's own reading
(`simulator/sensing.py`: no chain crosses it), the evaluator's exact
connectivity (`mission_world.Connectivity`: each pair's spans less the
partition's window) and so the reports' timing, and the knowledge log's
truth. **All three judge the window alike**: strictly inside it, each end
moved back by a microsecond, so a decision "at" 60 s -- give or take the
clock's rounding -- is inside, one "at" 120 s outside; a test holds the
sensing and the judge to the same answer at the edges.

**The condition never reaches an agent.** It is not in the scenario or the
brief (decision, above); agents can import neither module (the boundary's
import rule), and the boundary's walk now looks for `NetworkModel`,
`Partition` and `Transmitter` too: an agent flying on a partitioned, lossy
bus reaches none of them.

**The canonical mission flown once under each condition** (seed 17, no stop):

| Condition | Met | Ended | Lost | Rate-limited | Partitioned | Expired |
|---|---|---|---|---|---|---|
| nominal | yes | 194.1 s | 0 | 0 | 0 | 0 |
| moderate | yes | 194.1 s | 352 | 0 | 0 | 0 |
| severe | yes | 507.7 s | 2,603 | 438 | 0 | 7 |
| partitioned | yes | 313.3 s | 0 | 0 | 798 | 0 |

How the team fares is the exit's finding to record, not this step's. Nominal
is **Phase 9's flight exactly** -- every policy record, and every delivery
once put in a canonical order.

**The record's order is the threads'.** The bus records deliveries in the
order they were sent, and drones send at the same simulated instant from
their own threads, so two identical flights can list them in different
orders. Every comparison of deliveries -- these tests, and the exit's
"reproducible delivery" -- puts them in a canonical order first (sent,
sender, sequence number, recipient).

**A false alarm in the knowledge log, the third of its kind, fixed at the
root.** Under severe latency, at 18.0 s Drone2's record of Drone1 said Drone1
had been at (37.1, 17.1) at 12 m -- correctly -- and Drone4 truly was at
(37.1, 17.1) at 24 m, crossing the same lane higher up: "leak: it knew where
Drone4 really was". Drones fly at their own heights, so **a teammate's place
is now matched in 3D when written in 3D**: its x, y alone, or with its own
height, is a leak; with another height it is another place. A test holds
both sides. The target check is unchanged.

**Tests: 32, in `tests/test_network.py`;** 1 more in `tests/test_knowledge.py`;
the boundary's lists extended in `tests/test_sensing.py`.

**Mutations: 33, 31 caught and 2 equivalent -- loss decided by `u < p` or `u <= p` differs only when the draw equals the probability exactly (about 2^-53), and the cut's outer test differs only for a span that just touches the window, which comes out the same either way. The first pass caught 28 of 32; the two gaps were a span ending just after the window, and the judge not being handed the network -- which a test checking the far group at 90 s missed, because there the range alone already cut it. That test now judges the same flight without the network too, and shows the far group reaching the base inside the window.**

**Phases 5–9 reproduce** -- Phase 5's exit, Phase 6's knowledge exit, Phase 7's
exit and gate, Phase 8's exit, Phase 9's exit, all identical. **The goldens
did not move.** 1010 tests pass, 28 skipped; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-04 | **A message's fate is keyed by the message, not drawn from a shared stream** | Threads send in no fixed order at one instant; a shared stream would make the lost messages depend on it |
| 2026-11-04 | **A partition is judged the same way by the bus, the sensing and the judge, with a microsecond's allowance** | A decision "at" the partition's start is that instant give or take the clock's rounding; three different answers would be three different truths |
| 2026-11-04 | **Deliveries are compared in a canonical order** | The record lists them in the order threads sent them, which no flight controls |
| 2026-11-04 | **A teammate's place is matched in 3D when written in 3D** | Drones fly at their own heights; the same x, y at another height is another place |
| 2026-11-04 | **The network condition never enters the scenario or the brief** | The brief is what an agent is told; a loss rate or a partition schedule in it would be an oracle (AUV-10, 10.5) |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
