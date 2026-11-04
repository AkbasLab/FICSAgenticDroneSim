# Phase 10 — Build the degraded-communications simulator

**Stage:** 4 · Adversity · **Vault note:** `AUV-10 — Degraded Communications`
**Started:** 2026-11-04 · **Completed:** 2026-11-04

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

- [x] **10.1** Implement a configurable network model — latency mean and jitter, packet loss, message rate limit, bandwidth, communication range
- [x] **10.2** Support four communication conditions — Nominal, Moderately degraded (~10% loss), Severely degraded (~30% loss), Partitioned
- [x] **10.3** Use a seeded random-number generator — same seed ⇒ same lost messages, same latency samples, same target placement, same failure time
- [x] **10.4** Add message expiration — TTL per message class
- [x] **10.5** Let agents estimate communication health — from heartbeat rate, round-trip time, missing sequence numbers, delivery acknowledgments; **never read the configured loss rate**
- [x] **10.6** Verify the network model statistically — thousands of mock messages; empirical loss and latency match configuration; partitions block only intended links; expired messages not delivered; identical seeds reproduce

## Exit criterion

> The same mission can be replayed under nominal, degraded, severe and
> partitioned conditions with **reproducible message delivery**.

**Met:** yes, on the mock, 2026-11-04 — 20 of 20 seeds passed all four checks: the canonical mission under each
condition, with no stop and with Drone1 stopped at 60 s, every flight twice, and on Phase 9's network once
(360 flights) · **Evidence:**
[`evidence/exit-criterion-2026-11-04.md`](evidence/exit-criterion-2026-11-04.md), and for 10.6
[`evidence/network-check-2026-11-04.md`](evidence/network-check-2026-11-04.md).

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
| Message lifetimes (10.4) | `agentic_uav/core/messages.py`, `agentic_uav/agents/belief_state.py`, `agentic_uav/experiments/message_log.py` | **Done** 2026-11-04; goldens unedited; Phases 5–9 reproduce |
| Link-health estimates (10.5) | `agentic_uav/agents/belief_state.py`, `agentic_uav/agents/drone_agent.py` | **Done** 2026-11-04; goldens unedited; Phases 5–9 reproduce |
| Statistical verification (10.6) | `agentic_uav/experiments/network_check.py`, `scripts/network_check.py`, `results/`, `evidence/` | **Done** 2026-11-04; 10.6 verified |
| The exit | `agentic_uav/experiments/network_exit.py`, `scripts/network_exit.py`, `results/`, `evidence/` | **Done** 2026-11-04; exit met on the mock |

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
   which must be zero by construction, and is checked. *(Both changed in
   building it: see step 2's record.)*
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

### 2026-11-04 — step 2: message lifetimes (10.4)

**One part of the plan changed, said here.** The plan moved the lifetime table
into a network manifest. Building it showed it does not belong there: a
lifetime is set by the SENDER and travels in the message (`time_to_live_s`);
the network only enforces it. A manifest copy would hold the same numbers,
read by nothing -- an agent may not read an experiment's manifest -- so **the
table stays in the protocol** (`core/messages.py`), mapped to AUV-10's classes,
and every run can record it (`lifetimes()`). It moves to a manifest when a
phase varies it. AUV-10's classes:

| Class | Lifetime | Types |
|---|---|---|
| heartbeat | short: 3 s, three missed at 1 Hz | HEARTBEAT |
| current intent | short: 10 s, a decision's worth and a lease | STATUS_UPDATE, the six TASK_* types, ROLE_CHANGE |
| target report | longer | none sent: TARGET_FOUND has no schema |
| mission constraints | mission-long | none sent: the team mission comes in the brief |

A type with no schema has no lifetime and cannot be sent at all, so nothing
travels unbounded.

**The instant a lifetime ends, settled.** Under severe latency two heartbeats
were delivered at the very tick their 3 s lifetime ended: lifetimes and ticks
are both whole half seconds, and whether 302.7 + 3.0 fell a hair above or below
the clock's 305.7 decided it -- float rounding, not the rule. **A message read
at the instant its lifetime ends is now expired, and a team record is no
longer current, give or take a nanosecond** (`EXPIRY_TOL_S`). Every run of
record re-ran identical, Phases 5–9 included: no earlier flight had a message
or a record on that instant.

**What the message log checks and counts** (`experiments/message_log.py`):

* **Never delivered late** (`late`, on the bus's own times, not the log's
  rounded ones): none, in any flight.
* **Never current late** (`current_late`): no record past its lifetime held as
  current in any decision's belief.
* **Stale-message decisions** (`stale_decisions`), AUV-10's diagnostic:
  decisions whose policy read a teammate's record already past its lifetime.
  **Not zero by construction, as the plan said** -- a relay flies toward a
  silent teammate's last known place on purpose -- so they are counted and
  named, each with how far past its lifetime the record was.

**The canonical mission under every condition, with and without Drone1
stopped at 60 s:** nothing delivered late, nothing held current late, **no
stale-message decision** -- these policies read only current records, and
none relays here. Messages expired on the way only under severe (9 with no
stop, 3 with Drone1 stopped), and all of them heartbeats, the shortest-lived.

**Tests: 11, in `tests/test_lifetimes.py`.** The table as fixed, a type
without a schema refused; the instant a lifetime ends, for a message and a
record, a hair either side; the three log functions on entries built to pass
and to fail; and the eight flights -- nothing late, every message carrying its
type's lifetime, only severe expiring, and only heartbeats, no stale decision.

**Mutations: 11, all caught on the first pass.**

**Phases 5–9 reproduce; the goldens did not move.** 1021 tests pass, 28
skipped; audit clean.

### 2026-11-04 — step 3: each drone estimates its own links (10.5)

**`agents/belief_state.py`**: an agent on Phase 10's network keeps, for each
teammate, over the last 10 s of what arrived (`communication.links`):

| Estimate | From |
|---|---|
| heartbeat rate | heartbeats heard per second |
| loss | sequence numbers missing between the lowest and highest heard, over that span -- lost, rate-limited or cut off alike |
| latency | arrival less the message's timestamp, on the shared clock (a real fleet would need synchronized clocks; this estimate assumes them) |
| round trip | its claim (TASK_AWARD) to that teammate's acknowledgement (TASK_ACCEPT naming it): `drone_agent` notes each claim it makes |
| heard ago | since anything at all arrived from it |

**Never from the network's settings**, which no agent can import or reach (the
boundary, step 1). **Only an agent on Phase 10's network keeps them**, so every
earlier snapshot -- and every run of record built on one -- is exactly as it
was; and they are shown, not acted on (recommendation 1): nominal decides
exactly as Phase 9 did.

**What the drones estimated, never told** (the canonical mission, seed 17, no
stop, every decision after 15 s, every teammate):

| Condition | Loss estimated (configured) | Heartbeats heard | Latency estimated | Claim round trip |
|---|---|---|---|---|
| nominal | 0.000 (0) | 0.98 Hz | 0.50 s | 1.0 s |
| moderate | 0.091 (0.10) | 0.87 Hz | 0.52 s | 1.0 s |
| severe | 0.295 (0.30, plus the rate limit) | 0.65 Hz | 1.39 s | 2.6 s |
| partitioned | 0.000 (0) | 0.86 Hz | 0.50 s | 1.1 s |

Two things to read right:

* **Latency as a drone lives it.** A message is read at the drone's next
  0.5 s tick, so nominal's 0.1 s is experienced as 0.5 s: the estimate is the
  network's latency rounded up to the tick, plus, under severe, the time a
  message waits behind its sender's earlier ones.
* **A partition is silence, not loss.** Nothing arrives across it, so there
  are no gaps to count: what grows is "heard ago" -- for Drone1, Drone3 and
  Drone4 unheard for 9 s and more inside the partition, Drone2 heard as ever.
  This is the signal Phase 9's ladder reads; telling a partition from a
  failure is still open.

**Tests: 11, in `tests/test_link_health.py`:** each estimate from arrivals
built for it -- a gap of two in ten, a window that drops what is older, one not
yet full, only heartbeats in the rate, a round trip -- and nothing kept or shown
without a window; flown, the estimates tracking the conditions, a partition as
silence, nominal's round trips two ticks every one, no decision changed, no
estimate in an earlier flight.

**Mutations: 16, all caught.** The first pass caught 14; the two gaps were a
round trip measured as a time of day, which passed a loose bound because every
claim on nominal is acknowledged at 2 s (every nominal round trip is now held
to exactly 1.0 s), and every message counted as a heartbeat (the nominal rate
is now held to at most one a second).

**Phases 5–9 reproduce; the goldens did not move.** 1032 tests pass, 28
skipped; audit clean.

### 2026-11-04 — step 4: the network model verified statistically (10.6)

**`experiments/network_check.py`, `scripts/network_check.py`**: heartbeats
through the real bus, no flight, from the four canonical drones -- STEADY,
each broadcasting once a second for 1000 s (12,000 deliveries a seed), and
BURST, four a second for 100 s, which presses severe's two-a-second limit --
under each condition, seeds 1–20. And two networks built only for the check,
since the four conditions rarely reach these limits: SLOW (3 ± 1 s, around a
heartbeat's lifetime), where many expire, and NARROW (500 bytes a second, four
a second sent), where every drone's send queue grows.

| Check | Held to |
|---|---|
| loss | the share lost, among what the network decided by chance, inside a 99 % binomial interval; with p = 0, none |
| latency | arrival less departure (the queue recomputed from sizes) against the configured distribution -- a normal raised to the floor, a point mass there -- by a KS test at 1 % over distinct values |
| rate limit | each admission against a bucket recomputed independently; refused to every recipient or none |
| partitions | each delivery against the partition's rule, pair by pair and instant by instant |
| expiry | nothing delivered past its lifetime, everything arriving past it expired, nothing left pending |
| seeds | the same seed the same record; reversed sending order the same record; another seed another |

**The verdict, stated before the run.** Loss and latency are tests at 1 %: a
true model fails one in a hundred by chance, so each holds for a condition
when no more than 2 of its 20 seeds reject (3 or more happen by chance about
once in a thousand). The exact checks must hold on every seed.

**The run of record** (`results/network-check-20261104-170034-check`, 145 s):
**10.6 verified.** Loss measured 0.1011 against moderate's 0.10 and 0.2991
against severe's 0.30, no seed rejected; latency 0.300 ± 0.099 s against
0.3 ± 0.1 and 1.006 ± 0.488 s against 1 ± 0.5 (the floor raises the low tail:
2.88 % at the floor, the normal's mass below it 2.87 %); **one rejection in
160 tests** -- moderate seed 6, latency, D 0.0158 against 0.0157, as chance
allows; 15,920 refusals in the bursts, each where the bucket says; 9,600
deliveries cut by the partition, each where its rule says; 474 expired under
severe and 66,678 under slow, none delivered late; every seed reproducing,
order-free, and another seed differing. Evidence:
[`evidence/network-check-2026-11-04.md`](evidence/network-check-2026-11-04.md),
generated from the record.

**Two traps in the checking itself, found and fixed before the run of
record:**

* **A latency is two clock readings apart.** Drawn at the 0.05 s floor, it
  came back as 0.04999999999999716; drawn at nominal's fixed 0.1 s, as values
  a hair either side. The reference CDF called the first impossible, and the
  KS test read a tie as a spread: D sat at the critical value on **every**
  severe seed, and at 55 times it on nominal -- a check failing a correct
  model. Measured latencies are now taken to the nanosecond, so a tie is a
  tie, and the reference allows a nanosecond at its steps.
* **A broadcast is one admission, three deliveries.** The rate check kept the
  last recipient's status only, so a message refused to one recipient and not
  the others passed. A test built to fail it did not; it now looks at all of a
  message's deliveries, and flags any that disagree. The first run made with
  the flawed check was discarded and run again.

**Tests: 23, in `tests/test_network_check.py`.** Each check passing on a real
stream and failing on it altered to break it; the loss interval held at its
edge (half an interval off holds, one and a half does not); rate-limited
messages kept out of the loss count; the bucket never holding more than a
second's worth after an idle spell; a clock not starting at zero; KS on known
cases, from the left, and with ties; the CDF's floor and step; a latency drawn
at the floor coming back at it; the stress networks, and one where nothing
expires failing; the verdict's rule; the script writing its record, a failing
check or stress network failing the run.

**Mutations: 26 -- 25 caught, 1 equivalent** (the loss check with p = 0:
with a zero-width interval, "none lost" and "within the interval" are the same
test). The first pass caught 17; the eight gaps were all cases the streams
never produce -- an interval's edge, rate-limited deliveries in the count, a
bucket after idling, a clock not at zero, a sample below its place, a hair
under the floor, a stress network that tests nothing, a run that ignores one --
each now a test.

**The goldens did not move.** 1048 tests pass, 28 skipped; audit clean.

### 2026-11-04 — step 5: the exit, met on the mock

**`experiments/network_exit.py`**: the canonical four-drone mission with
Phase 9's agents, each seed under each condition with no stop and with
Drone1 stopped at 60 s -- the same failure at the same time (10.3) -- every
flight twice, and on Phase 9's own network once, both ways. **Four checks**,
each shown able to fail:

| Check | What it requires |
|---|---|
| reproducible | every message's fate and time identical between the two flights, in a canonical order; and every record and decision |
| as configured | message by message, the network did what its condition says: each loss and latency the model's own draw after its sender's queue, each refusal where the bucket says, each cut where the partition says, nothing out of range, nothing delivered past its lifetime |
| nominal is Phase 9 | nominal's flights, both ways, are Phase 9's: every delivery, record and decision |
| known exactly | Phase 6's knowledge log passes every decision, under every condition |

"Known exactly" was not in the plan's list; it was added because the
agents' knowledge staying within what they sensed and what arrived is a
correctness property, and must hold under any network.

**The run of record** (`results/network-exit-20261104-174326-exit`, at
`e0efe8b` with the step-5 files uncommitted, `agentic_uav` digest
`ed301de89476f791`, 360 flights, 1453 s): **20 of 20 seeds passed every
check**; 28,921 decisions known exactly.

**Beside the exit, how the team fared** -- findings, not pass conditions,
over the 20 seeds:

| Condition / flight | Met | Completion s (median) | Searched twice | Leases run out | Alarms about live drones (suspected / failed) | Loss estimated |
|---|---|---|---|---|---|---|
| nominal / no stop | 20/20 | 194.1 | 0 | 0 | 0 / 0 | 0 |
| moderate / no stop | 20/20 | 307.7 | 20 | 18 | 30 / 4 | 0.088 |
| severe / no stop | 20/20 | 510.9 | 54 | 161 | 1,129 / 22 | 0.290 |
| partitioned / no stop | 20/20 | 313.3 | 20 | 80 | 160 / 160 | 0 |

* **The mission was met under every condition, both ways, on every seed.**
* **Paid for in repeated work and time**: a holder's progress lost on the way
  lets its lease run out while it works, and the sector is searched again.
* **The ladder raises false alarms**: 1,129 suspicions of live drones under
  severe, 22 carried to failed. Under the partition, **each side called the
  other failed** at 29.5 s into it -- exactly as for a stopped drone -- and
  took them back when it healed: from silence alone, a partition longer than
  the failure threshold is a failure. The open question Phase 9 left is now
  measurable.
* **A stop under loss is no longer detected at Phase 9's thresholds** (1 of 20
  under severe): the last message heard from the stopped drone comes earlier,
  so the rungs do too. The team still finished.
* **No stale-message decision**, under any condition.

**Evidence:** [`evidence/exit-criterion-2026-11-04.md`](evidence/exit-criterion-2026-11-04.md),
generated from the record: every seed's checks, the findings by condition,
every message's fate, and seed 17's partition taken for a failure, drone by
drone.

**Tests: 21, in `tests/test_network_exit.py`.** Every check passing on a real
seed's flights (nominal and partitioned) and failing on them altered: another
fate, record or decision on the second flight; the comparison blind to the
order threads sent in; a loss the model did not draw, an arrival off its draw,
a delivery across the partition, a refusal no bucket made, out of range
without a range, a delivery past its lifetime; nominal drifting from Phase 9;
a decision knowing too much; the findings' counts; the script's record and
verdict, nominal required among the conditions.

**Mutations: 21, all caught. The first pass caught 17; the four gaps were the exit's own wiring -- "known exactly" and the seed's verdict never driven to fail through `exit_checks` itself, a lease counted twice when a second book noticed it later, and an undetected stop never shown in the findings -- each now a test.**

**The goldens did not move; Phases 5–9 reproduce.** 1076 tests pass, 28
skipped; audit clean.

### 2026-11-04 — close

**Phase 10 is complete on the mock.** All six objectives are done and the exit
criterion is met: the canonical mission replays under nominal, moderate,
severe and partitioned conditions -- with and without a drone stopped -- every
message meeting the same fate at the same time when flown again, each network
doing message by message what its condition says, nominal being Phase 9's
network exactly. The network model is verified statistically (10.6); the
agents estimate their own links from what arrives, never told the condition.

**Not done, and said so:** no live flight, by the plan (the network is our
code; a real clock cannot replay it). The agents do not act on their link
estimates (recommendation 1). The levels are placeholders until pilots
calibrate them. Burst loss, interference zones and asymmetric links -- AUV-10's
"later" -- are not modelled.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-04 | **The exit also holds every decision to "known exactly"** | What an agent knows staying within what it sensed and what arrived is a correctness property, under any network |
| 2026-11-04 | **How the team fared is recorded, not passed or failed** | The network is the independent variable; Phase 10 makes it reproducible, the experiment measures its effect |
| 2026-11-04 | **A statistical check holds when no more than 2 of 20 seeds reject at 1 %; an exact one on every seed** | A true model fails a 1 % test one time in a hundred; demanding none would fail correct models, allowing many would pass wrong ones |
| 2026-11-04 | **Measured latencies are taken to the nanosecond** | Two clock readings apart, a drawn value comes back a hair off it; without this the check fails a correct model |
| 2026-11-04 | **Each link is estimated from what arrived, per teammate, over 10 s; shown, not acted on** | 10.5 asks for estimates the agent infers; acting on them is the experiment's factor, not this phase's |
| 2026-11-04 | **Latency is estimated on the shared clock, and said so** | One-way latency needs synchronized clocks; the simulation has one clock, a real fleet would not |
| 2026-11-04 | **Lifetimes stay in the protocol, not a network manifest** | A lifetime is the sender's and travels in the message; the network enforces it. A manifest copy would be read by nothing |
| 2026-11-04 | **At the instant a lifetime ends, a message is expired and a record not current** | Lifetimes and ticks share the half-second grid; without a rule, float rounding decided |
| 2026-11-04 | **Stale-message decisions are counted, not forbidden** | A relay reads a silent teammate's last known place on purpose; AUV-10 asks for the diagnostic |
| 2026-11-04 | **A message's fate is keyed by the message, not drawn from a shared stream** | Threads send in no fixed order at one instant; a shared stream would make the lost messages depend on it |
| 2026-11-04 | **A partition is judged the same way by the bus, the sensing and the judge, with a microsecond's allowance** | A decision "at" the partition's start is that instant give or take the clock's rounding; three different answers would be three different truths |
| 2026-11-04 | **Deliveries are compared in a canonical order** | The record lists them in the order threads sent them, which no flight controls |
| 2026-11-04 | **A teammate's place is matched in 3D when written in 3D** | Drones fly at their own heights; the same x, y at another height is another place |
| 2026-11-04 | **The network condition never enters the scenario or the brief** | The brief is what an agent is told; a loss rate or a partition schedule in it would be an oracle (AUV-10, 10.5) |

## Open questions

1. **A partition or a failure?** From silence alone, a partition longer than
   the failure threshold is a failure: under the partitioned condition every
   drone called the far side failed, then took it back. What evidence could
   separate them -- a whole group falling silent at once, the base link, a
   relay's word -- and what should a team do differently on each?
2. **Thresholds under loss.** Severe loss raised 1,129 suspicions of live
   drones. Should a drone's ladder scale with its own loss estimate -- the
   bid's communication-risk term finally given a weight? That is the
   experiment's factor, not this phase's.
3. **Leases under loss.** A holder's progress lost on the way lets its lease
   run out while it works (161 times under severe): longer leases, progress
   sent more often, or a lease that waits for the holder's own silence on
   the ladder?
4. **Calibrating the levels** (AUV-16, 17.3): are 10 % and 30 % loss, and a 60 s
   partition, defensibly different levels for the experiment?
5. **One-way latency assumes synchronized clocks**, which a real fleet would
   have to provide or estimate.
6. **Burst loss, interference zones, asymmetric links** -- AUV-10's "later add".

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
