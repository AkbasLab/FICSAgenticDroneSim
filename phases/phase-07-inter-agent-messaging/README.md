# Phase 7 — Build the inter-agent message protocol under perfect communication

**Stage:** 3 · The team · **Vault note:** `AUV-07 — Inter-Agent Messaging`
**Started:** 2026-11-02 · **Completed:** —

> Until now each drone has known its teammates are on the roster and nothing
> more: in Phase 6's pair flight two drones passed within 3.25 m, each holding
> the other as "never heard". Phase 7 lets them talk -- reliably first, so a
> protocol bug can never be mistaken for a dropped packet (AUV-07) -- through
> nothing but `send` and `receive_available`, and with every message on the
> record. Allocation (Phase 8), recovery (Phase 9) and degraded links
> (Phase 10) are all built on it.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [ ] **7.1** Define message types — 14: `HEARTBEAT` `STATUS_UPDATE` `TASK_ANNOUNCEMENT` `TASK_BID` `TASK_AWARD` `TASK_ACCEPT` `TASK_RELEASE` `TASK_COMPLETE` `INTENT_UPDATE` `TARGET_FOUND` `HELP_REQUEST` `ROLE_CHANGE` `MISSION_UPDATE`
- [ ] **7.2** Use a common message envelope — `AgentMessage` with id, type, sender, recipients, mission, timestamp, sequence number, TTL, payload, confidence
- [ ] **7.3** Prevent hidden global communication — agents interact only via `send()` and `receive_available()`; **no** inspection of the global queue, other agents' memory, undelivered messages, or ground truth
- [ ] **7.4** Add message logging — creation, scheduled delivery, actual delivery, dropped/delivered, sender, recipient, size, expiration, **whether it influenced a decision**

## Exit criterion

> Four deterministic agents exchange heartbeats and status messages while
> flying, and their **local team beliefs update only when messages are
> delivered**.

**Met:** on the mock, 2026-11-02 — 20 of 20 seeds passed all six checks; 5,820 teammate records, in 2,020
decisions, each traced to a message delivered before the decision · **Evidence:**
[`evidence/exit-criterion-2026-11-02.md`](evidence/exit-criterion-2026-11-02.md).
The optional live flight (step 6) is not yet flown.

Planned evidence: four rule agents on `search_relay_001` (S1–S4) across 20
seeds, every team-belief update traced to a delivered message and none
without one, with negative controls in which messages are not delivered and
beliefs do not move. Optionally, two drones talking in CarlaAir.

## Deliverables

| Artifact | Location | State |
|---|---|---|
| Message types and the envelope | `agentic_uav/core/messages.py` | **Done** 2026-11-02; goldens unedited |
| The bus, and the two-function handle | `agentic_uav/simulator/message_bus.py`, `agentic_uav/core/messages.py` (`Comms`) | **Done** 2026-11-02; goldens unedited |
| The message log | `agentic_uav/experiments/message_log.py`, `agentic_uav/core/team.py`, `agentic_uav/agents/belief_state.py`, `agentic_uav/agents/drone_agent.py` | **Done** 2026-11-02; goldens unedited; Phases 5–6 reproduce |
| Agents that talk | `agentic_uav/agents/drone_agent.py`, `agentic_uav/agents/belief_state.py`, `agentic_uav/experiments/single_agent.py` (`messaging=True`) | **Done** 2026-11-02; goldens unedited; Phases 5–6 reproduce |
| The exit | `agentic_uav/experiments/messaging.py`, `agentic_uav/experiments/knowledge.py` (heard teammates), `scripts/messaging_exit.py`, `results/`, `evidence/` | **Done** 2026-11-02; exit met on the mock |
| The clock's same-instant order (6a) | `agentic_uav/core/clock.py` (`sleep_after_others`), `agentic_uav/agents/drone_agent.py` | **Done** 2026-11-04; goldens unedited; Phases 5–7 reproduce |
| Optional live flight; close | `results/`, `evidence/` | step 6b–6e |

## Plan

Approved 2026-11-02 with all six recommendations, after it had been shown in
full. Each step lands as its own commit after the user's go-ahead; the four
Phase 2 goldens must pass unedited after every step.

Four independent rule agents already fly `search_relay_001` (S1–S4, at 12,
16, 20 and 24 m) on 20 of 20 seeds, and at their farthest two are 188.7 m
apart, nearly twice the 100 m radio range: a range-limited network refuses
some messages by itself, which is what the exit needs to show.

1. **The record, the message types and the envelope (7.1, 7.2).**
   `core/messages.py`: `MessageType` and `AgentMessage` -- id, type, sender,
   recipients, mission, timestamp, sequence number, TTL, payload, confidence
   -- validated, serialized to JSON, with its size in bytes. Payload schemas
   for the types used now, `HEARTBEAT` and `STATUS_UPDATE`.
2. **The bus, and nothing else to talk through (7.3).**
   `simulator/message_bus.py` as simulation infrastructure; an agent gets a
   handle of exactly two plain functions, `send()` and `receive_available()`.
   The boundary checks grow: no agent code imports the bus; the walk of a
   flying agent reaches no bus, queue or other agent. No `peek()`, not even
   for debugging.
3. **The message log (7.4).** Every message's life -- created, scheduled,
   delivered or not and why, sender, recipient, size, expiry -- and whether
   it influenced a decision: a team record keeps the message that made it,
   and the belief notes which records the policy read while deciding.
4. **Agents that talk.** `DroneAgent` sends a `HEARTBEAT` every second and a
   `STATUS_UPDATE` after each decision, takes in what arrived each tick
   through Phase 6's `receive()`, and fills the `communication` block with
   estimates from what it heard: peers heard recently, gaps in sequence
   numbers, latency seen.
5. **The exit.** Four agents on `search_relay_001`, 20 seeds: every
   team-belief update in every decision explained by a delivered message,
   none without; the knowledge log showing teammates' records with the
   message that made them; negative controls in which nothing is delivered.
   Evidence generated from the records.
6. **An optional live flight -- two drones in CarlaAir on the proven
   two-drone layout -- and the close.** Ask before tagging and pushing.

**Step 6, as approved 2026-11-04** (shown in full first, on 2026-11-02). Planning
it found a determinism defect from Phase 5 (see the record), so it begins with
the fix:

* **6a. Fix the same-instant race in the simulated clock.** A sleeper may ask
  to wake after every other thread due at that instant has run and slept
  again; the agent's tick uses it, so an agent always sees what ended at its
  tick. Tested on a forced race; the live variant's seeds then repeat
  identically; Phases 5–7's runs of record must still reproduce, and any
  decision that moves gets a dated note, the old record kept.
* **6b. The live variant's mock gate:** two talking agents on
  `search_relay_live_small`, 20 seeds, all six checks.
* **6c. The live path for agents that talk:** `fly_agents_live` -- reset, Drone2
  spawned at runtime, both at rest, the poller and the separation monitor, a
  connection per skill per drone, sensors from the poller, the bus fed the
  poller's latest positions -- and `messaging_exit.py --sim airsim`, with a
  real-time dry run on the mock behind `AUV_SLOW_TESTS`.
* **6d. One live flight, flown by the user** on Windows, CarlaAir fresh with
  Drone1 only. No Vega.
* **6e. The close:** record, ledger, index; AUV-22 7.1–7.4, the AUV-07 callout,
  the MOC, the report AUV-P7…; ask before tagging `phase-07-complete` and
  pushing.

Its four recommendations: fix the race in the clock, not by shifting the
agents' ticks (which would move every decision time); one live flight, two
drones on the variant's 20 m radio, so they talk near the pads and fall silent
searching some 36 m apart; live checks met, exchanged, only on delivery and
known exactly, with the mock twin beside it; live, the bus judges range from
the poller's latest positions.

**The six recommendations:**

1. **The 13 named types, not 14.** The source plan says "fourteen" and names
   thirteen; the gap is recorded rather than filled with an invented type.
2. **Payload schemas only for the types used now.** The other eleven exist as
   names and get their schemas in the phases that use them (contract-net in
   Phase 8, help and role in Phase 9, intent in Phases 8–9); sending a type
   with no schema yet is refused.
3. **"Perfect" means no loss, delivery at the next tick, over a direct link
   within the scenario's 100 m range** -- Phase 4's hard edge. An
   unlimited-range mode is for protocol tests. Relaying agents' messages
   through other drones waits for Phase 10's network model.
4. **Heartbeats and status do not trigger decisions;** only messages that
   change mission state would. So the four agents decide exactly as they
   would with messaging off -- a check. Phase 8 is where messages change what
   agents do.
5. **"Influenced a decision" at two levels:** the message was in the belief at
   a decision, and the policy actually read it. Both logged.
6. **The communication estimates come from messages heard, never from the
   bus's settings** (AUV-10, 10.5), from the start.

## Record

### 2026-11-02 — the plan, shown before it was approved

The plan above was written out in full in the message that asked for its
approval, and approved with all six recommendations: the first plan in four
phases not to need the "approved before it was shown" note. The user had
earlier set aside running on the shared Rocky Linux machine; Phase 7 runs on
the usual Windows setup, and needs no Vega (the agents are rule-based until
Phase 12).

### 2026-11-02 — step 1: the message types and the envelope (7.1, 7.2)

**`agentic_uav/core/messages.py`**, plain data that knows nothing of how a
message travels:

* **`MessageType`: the thirteen types AUV-07 names** — `HEARTBEAT`,
  `STATUS_UPDATE`, the six `TASK_*` of Phase 8's contract-net,
  `INTENT_UPDATE`, `TARGET_FOUND`, `HELP_REQUEST`, `ROLE_CHANGE`,
  `MISSION_UPDATE`. AUV-07 and AUV-22 say "fourteen" and list these thirteen;
  the research plan in the repository lists none. The gap is recorded here,
  not filled with a type of our own.
* **`AgentMessage`, AUV-07's envelope field for field:** id, type, sender,
  recipients (a tuple of drones, or `BROADCAST`), mission, timestamp,
  sequence number, time to live, payload, confidence. It validates itself and
  refuses, with every reason at once: an unknown type; an empty id, sender or
  mission; recipients not a tuple, none, the sender itself, one named twice,
  or `*` mixed with names; a timestamp that is not a finite number; a
  sequence number below 1, a float or a bool; a lifetime that is not
  positive; a confidence outside [0, 1].
* **Payload schemas only for the types in use**: `HEARTBEAT` (position,
  airborne, battery) and `STATUS_UPDATE` (task, stage, skill, position,
  battery, degraded). Every field required; none unknown; each of its kind; the
  payload plain JSON (no NaN, no objects). A message of any of the other
  eleven types is refused — "no payload schema yet" — so no phase can start
  sending one without first saying what it carries.
* **Lifetimes** (AUV-10, 10.4): a heartbeat 3 s (three at 1 Hz), a status
  10 s (the periodic check's interval). A message expires at exactly its
  timestamp plus its lifetime.
* **The id is the sender and the sequence number** (`Drone1#13`), so the same
  flight gives the same ids; the size is the compact JSON's bytes, so the
  same message has the same size.

**Built to sit inside the boundary**, since agents will import it. A first
version copied the payload with `object.__setattr__` and named types with
`type(x).__name__` and `getattr` — all three refused by the boundary check
agents are held to, which caught them. The copy also belonged elsewhere: what
matters is that no two agents hold the same mutable payload, and that is the
bus's job (step 2: each recipient its own copy). So `AgentMessage` only
validates, `new_message` makes the plain copy of what the sender hands over,
and the module passes the check.

**Tests: 12, in `tests/test_messages.py`:** the thirteen types and their
values; schemas and lifetimes only for the two in use; every other type
refused; AUV-07's fields; a status update; read back the same, and its size;
expiry at exactly its end; who a message is for; the sender keeping its own
payload; seventeen malformed envelopes and nine malformed payloads, each
refused for its reason; and the module passing the boundary check.

**Mutations: 21, all caught on the first pass**, against the message tests
(nothing else uses the module yet). A mistyped target stopped the run before
anything was mutated, as the exactly-once check is there to do.

**The goldens did not move.** `record_golden.py --check` matches all four.
664 tests pass, 22 skipped; audit clean.

### 2026-11-02 — step 2: the bus, and nothing else to talk through (7.3)

**`agentic_uav/simulator/message_bus.py`** is simulation infrastructure. It
is central and can see everything -- where every drone is, every queue --
because deciding delivery needs it. What it hands an agent is
**`core.messages.Comms`**: the drone's id and two plain functions, `send` and
`receive_available`, built like `Sensors` and `SkillHandle`. No attribute
leads back to the bus, and there is no `peek`.

**Phase 7's perfect communication** (recommendation 3): no loss, no delay,
over a direct link no longer than 100 m in 3D -- Phase 4's hard edge --
judged when the message is sent. A message sent in range is waiting at once,
so its recipient reads it at its next tick; one sent out of range is never
delivered, and the record says so. `range_m=None` is unlimited, for protocol
tests. A message is never delivered after it expires; one still waiting when
its lifetime ends is dropped as expired.

* **Each recipient its own copy,** rebuilt from the message's JSON: no two
  agents ever hold the same mutable payload, which would be a channel no
  message went through. A broadcast is one delivery per drone but the sender.
* **Refused:** a message not from the handle's drone (no spoofing), one to a
  drone off the roster, one for another mission, anything not an
  `AgentMessage`; and a roster naming a drone twice, a range that is not
  positive and finite, a handle for a drone not on the roster.
* **The record:** every delivery -- one message to one recipient -- with when
  it was sent, scheduled and delivered, the distance at sending, and its
  status: delivered, pending, out of range, expired. It is the experiment's,
  for the message log of step 3; nothing an agent holds reaches it.

**The boundary grows.** `MessageBus` and its `Delivery` records join the
objects the walk of agent code must never reach, and importing the bus is a
fourteenth breach the source check is shown to catch.

**A race, found by a surviving mutation.** With the lock around sending
removed, the tests still passed: they had senders racing senders, whose list
appends Python's GIL keeps whole. The real race is a send landing between
`receive_available`'s two steps -- taking what is ready, keeping the rest --
and it loses the message from the inbox while the record still says pending.
Probed with a sender and a reader at once: 2,248 of 200,000 messages lost
without the lock, none with it. At a test's size the window is rarely hit,
because Python switches threads only every 5 ms: 20,000 messages caught it
once in three. Switching every microsecond for the test's duration
(`sys.setswitchinterval`) makes it certain: 5,000 messages, 1.4 s, the race
caught 8 times in 8, and with the lock the test passes 5 times in 5.

**Tests: 14, in `tests/test_message_bus.py`:** in range it is waiting at
once, read once, only by its recipient; a broadcast reaches all but the
sender; out of range never arrives and the record says so (exactly 100 m is
in, 100 m and a millimetre up is out); unlimited range; range judged at
sending; nothing after expiry; oldest first and pending until read; each
recipient its own copy; what the bus will not carry; the bus itself; many
senders at once; a message sent while its recipient reads is not lost; the
handle is two plain functions and a name; a holder of the handle reaches no
bus. Plus the bus-import breach in `tests/test_sensing.py`.

**Mutations: 20, all caught.** The first pass caught 19; the survivor was the
lock, above. A first test of mine also put a drone "a hair" beyond the range
with a 1e-6 m rise, which floating point rounds away at 100 m; it is a
millimetre now.

**The goldens did not move.** `record_golden.py --check` matches all four.
678 tests pass, 22 skipped; audit clean.

### 2026-11-02 — step 3: the message log, and whether a message mattered (7.4)

AUV-07 asks the log for each message's "creation time, scheduled delivery
time, actual delivery time, dropped-or-delivered status, sender and
recipient, size, expiration -- and whether the message influenced a
decision." The first eight come from the bus's record; the last needs a
chain from a message to a decision with no gap in it.

**The chain:**

* **A record keeps its message.** `core/team.TeamReport` gains `message_id`,
  and the belief's snapshot shows it beside each teammate's record.
* **The belief notes what the policy read.** Between `start_reading()` and
  `read()`, it collects the message ids of the records looked at through
  `teammate()` or `current_teammates()`. The rule policy reads its team
  through them only (its `teammates` assumption).
* **The decision keeps it.** `DroneAgent` starts the reading before the
  policy decides and collects it straight after -- before the validation
  step, whose reads are not the policy's -- and the `TraceEntry` carries the
  ids as `read`, refused decisions included.
* **The log joins them** (`experiments/message_log.py`): one row per message
  per recipient, with the eight columns, distance at sending, and influence
  at two levels -- *in the belief* (the first decision of the recipient whose
  belief held a record from this message) and *read by the policy* (the
  first decision that read it). A message never delivered can do neither, and
  the row says why: out of range, expired, or pending at the end. `summary`
  adds it up: counts by status and type, bytes sent and delivered, how many
  were in a belief, how many were read.

**Phase 5's and Phase 6's records reproduce exactly:** the knowledge exit's
1380 flight and decision rows, and Phase 5's exit decisions and reports,
identical to their runs of record (`agentic_uav` digest `8f754f0e16fbad25`).
Their team records were never heard, so the new column never appears in them.

**Tests: 15, in `tests/test_message_log.py`:** the snapshot naming the
message; reading through the accessors noted (current records only, an
expired one asked for by name, none for a record that came in no message);
each decision starting afresh; the rule policy reading its teammates; the
trace keeping what the policy read, in JSON too; the validation step's reads
not counted; a refused decision keeping its reads; each decision keeping
only its own; every column AUV-07 asks for, on a clock that does not start
at 0; what was not delivered and why; influence at two levels, and as the
recipient's own; the summary; a Phase 6 snapshot without message ids; trace
entries or their JSON.

**Mutations: 19, all caught.** The first pass caught 16. The three survivors
were test gaps: the agent never starting a decision's reading afresh (my
test policy read the same record every time, so the pile-up never showed);
the first read kept rather than the last (no message was read twice); and a
record without a `message_id` key, as Phase 6's are (it would have crashed
the log).

**The goldens did not move.** `record_golden.py --check` matches all four.
693 tests pass, 22 skipped; audit clean.

### 2026-11-02 — step 4: agents that talk

**`DroneAgent` with `comms`** (`agents/drone_agent.py`). Each tick, after
updating its belief and before deciding, the agent **takes in** what has
arrived: each message becomes a `TeamReport` -- sender, sent time, position,
task, stage, the message's lifetime and id -- for the belief to keep or
refuse (Phase 6's rules), and is noted for the link estimates. It **says**
who it is, where and on what in a `HEARTBEAT` every second, and after each
decision a `STATUS_UPDATE` (task, stage, skill, position, battery, health).
All its messages are broadcast and numbered from 1 in one sequence. It
refuses another drone's comms.

**The link, estimated from what was heard** (`agents/belief_state.py`;
AUV-10, 10.5): peers heard in the last 3 s, the share of sequence numbers
skipped, and the mean age on arrival of the last ten messages. A message
missed for any reason is a gap: the agent cannot tell range from loss and
does not pretend to. An agent not listening keeps all three unknown, as in
Phases 5 and 6. **The latency it estimates is 0.5 s, not the bus's 0.1 s:**
it can only measure a message's age when it reads it, at its next tick --
the honest figure from its side.

**Two refinements of the plan, both said before building:**

* **A heartbeat says what the sender is doing** -- task and stage -- as well
  as who and where. A teammate's record is its latest report, so a bare
  heartbeat after a status would have wiped the task.
* **"Delivered at the next tick" is a fixed 0.1 s delay**, below the 0.5 s
  tick (`MESSAGE_DELAY_S`; the bus's `delay_s`). With none, a message sent at
  the instant a teammate's thread read its inbox arrived or not by which
  thread ran first, and team beliefs would differ run to run. The message
  log orders its rows by sent time, sender, sequence and recipient for the
  same reason.

**The four canonical agents talking** (`fly_agents_on_mock(...,
messaging=True)`, `search_relay_001`, S1–S4): the tasks met, **exactly the
decisions and report they make without messaging** (recommendation 4), and
the same message log and beliefs on every run. Seed 17: 2,394 deliveries --
1,595 delivered, 645 out of range, 154 still waiting for agents that had
landed; 208 messages in a belief at a decision, 195 read by a policy.

**Phase 5's and Phase 6's records reproduce exactly** (digest
`994a1620446375cf`): an agent without comms takes in and says nothing.

**Tests: 18, in `tests/test_agents_talk.py`, and 1 in
`tests/test_message_bus.py`:** the four complete their tasks; talking changes
no decision; a heartbeat a second and a status after each decision; one
sequence from 1; **team beliefs update only on delivery** -- every teammate
record in every decision came in a message delivered to that drone at or
before the decision, carries that teammate's task, and is aged from when the
message was sent; nothing undelivered is ever believed; a teammate out of
range goes stale; the policy reads what it believes; the link estimates
against the log; deterministic; unlimited range has no gaps; an agent not
listening keeps the link unknown; the estimates from arrivals alone (gaps,
a late arrival, the connected window, the last ten); an agent with comms
reaches no bus; another drone's comms refused; and the bus's fixed delay.

**Mutations: 25, all caught.** The first pass ran 24 and three survived, all
test gaps: a record aged from arrival rather than sending, the task not
carried, and a negative or infinite delay accepted. The 25th -- a heartbeat
schema without task and stage -- did not fail: **it hung the suite.** The
bus's stress test (step 2) left its "done" flag unset when the sender
raised, and the reader waited for ever. That is a defect of the test, and
of the kind that hides others; the sender now sets the flag however it
ends, the threads are joined with a time limit, and the mutant fails in a
second. The pair flight itself, with the same mutant, raised at once,
naming the agent -- a crashed agent does not hang a team flight.

Also: one mutation target was mistyped (indentation) and stopped the run
before anything was mutated; and a delay test of mine summed 0.09 and 0.01,
which falls short of 0.1 in floating point.

**The goldens did not move.** `record_golden.py --check` matches all four.
712 tests pass, 22 skipped; audit clean.

### 2026-11-02 — step 5: the exit, met on the mock

**Each seed flown three ways** (`experiments/messaging.py`): **talking**, the
four canonical agents on Phase 7's perfect network; **blocked**, the radio's
range cut to 1 m, so every message is sent and none arrives; and **silent**,
no messaging, the reference. **Six checks**, each shown able to fail:

| Check | What it requires |
|---|---|
| met | the talking flight completes its four tasks |
| exchanged | every agent sent heartbeats and status updates, and received both kinds from teammates |
| only on delivery | every teammate record in every decision came in a message from that teammate, delivered to that drone at or before the decision, with that teammate's task, aged from sending; nothing undelivered ever believed |
| known exactly | Phase 6's knowledge log passes every decision |
| blocked moves nothing | messages sent, none delivered, every teammate "never heard" throughout |
| steers nothing | talking and blocked flights make exactly the silent flight's decisions |

**The knowledge log, taught that teammates can now be heard.** Phase 6's
leak check was written when no teammate could be: run on the talking four it
called a heard teammate's position a leak, on 12 of 101 decisions. It now
looks for a teammate's true position everywhere *except that teammate's own
record* -- which came in a delivered message, traced above -- and "correct"
gains a check: a heard teammate's record must say where it truly was when it
spoke (now, less the record's age). So an agent that knows more than it was
told fails, and so does one told something false or holding a record older
than it says. All 101 pass; Phase 6's record still reproduces row for row.

**The run of record** (`results/messaging-exit-20261102-213008-exit`, at
`8e24d56` with the step-5 files uncommitted, `agentic_uav` digest
`480cafb6ab4486b4`, 60 flights): **20 of 20 seeds passed every check.**

* **5,820 teammate records, in 2,020 decisions,** each traced to a message
  delivered to that drone before the decision, from that teammate, with its
  task, aged from sending.
* **31,927 messages delivered, 12,869 out of range** (the sectors put drones
  up to 188.7 m apart), 3,084 pending for agents that had landed, **none
  expired**: every delivered message was read at the next tick.
* **Every blocked flight:** each seed's messages sent, none delivered, every
  teammate "never heard" at every decision; and talking and blocked flights
  made exactly the silent flight's decisions on every seed.
* **Beliefs go stale when delivery stops.** In seed 17, Drone1 heard all
  three teammates at every decision to 47 s; at 57 s its records of Drone3
  and Drone4 had expired, those two being out of range in the far sectors;
  at 73 s, back in range, they were fresh again. 90 decision-records in that
  seed held an expired teammate, shown as expired, not current.
* **What mattered:** in seed 17, 208 messages were in a belief when a
  decision was made, and 195 were read by the policy deciding.

The record keeps, for every seed, the checks and every decision's team block
(which message each record came from, its age, whether current, what the
policy read), and for seed 17 the talking flight's full message log: 1.5 MB.

**Evidence:** [`evidence/exit-criterion-2026-11-02.md`](evidence/exit-criterion-2026-11-02.md),
generated from the record: every seed's checks; who heard whom in seed 17;
what Drone1 believed of each teammate at each of its decisions; a teammate
going stale.

**Tests: 20, in `tests/test_messaging_exit.py`:** every check passes on a real
seed; the three flights are what they say; and each check failing on a real
flight altered to break it -- a record from no delivered message, from
another drone's, delivered after the decision, with the wrong task or age;
something undelivered believed; no record at all is not a pass; an agent
that sent or heard nothing of a kind; a blocked flight that heard
something, or sent nothing; talking that changed a decision (and one check
failing fails the seed); a flight that did not meet its tasks; the team
blocks compact and in order; and the knowledge log's heard-teammate rules --
allowed in its own record, the wrong place, a record fresher than it is,
one teammate's place in another's record, a teammate's place anywhere else.
One test of mine first assumed Drone2 was moving at the decision it used; it
was hovering, so the test now finds a moment it truly was.

**Mutations: 19, all caught.** The first pass caught 16; the three survivors
were test gaps -- the leak exception widened to every teammate's record, a
blocked flight that sends nothing, and "all checks" reduced to "met".

**The goldens did not move.** `record_golden.py --check` matches all four.
732 tests pass, 22 skipped; audit clean.

### 2026-11-04 — step 6a: the clock's same-instant order

**The defect, found planning step 6.** Phase 3's `SimClock` wakes every thread
due at one instant together, and which runs first is the operating system's
choice. That is harmless for threads that only act; it is not for one that
reads what the others did at that instant. On `search_relay_live_small` the
silent pair, seed 1, gave two different decision sets in twelve runs: Drone1's
skill ended at exactly 30.0 s, on an agent tick, and the agent saw the ending
at 30.0 s on some runs and at 30.5 s on others. Twelve of the twenty seeds
could flip so. No run of record was affected: the canonical four, Phase 5's
single agent and Phase 6's pair were stable across repeats. A probe on the
clock alone showed the race can be forced: a worker ending something at 1.0 s
and an observer due then, the observer saw it 300 of 300 times at Python's
default switch interval and 291 of 300 at 1e-6 s.

**The fix, in the clock** (`agentic_uav/core/clock.py`). A thread may sleep
with `sleep_after_others`: it wakes at its instant only once every other
participant due then has run and is asleep again, or has left. Late sleepers
do not wait for one another. `RealClock`'s is a plain sleep: real time has no
shared instants to order. The agent's tick (`DroneAgent.run`) uses it, and
nothing else changed: skills, waits and the executor sleep as before. So an
agent always sees what ended at its tick, as Phase 5 meant it to. The fix
moves no tick; shifting the agents' ticks off the skills' instants was the
alternative, and it would have moved every decision time.

**What it shows:**

* **The forced race, always seen:** at a 1e-6 s switch interval the observer
  sees the ending 300 of 300 times; with the fix switched off the same test
  fails at once.
* **The live variant repeats:** the pair on all 20 seeds, silent and talking,
  six runs each, made identical decisions every run; and again at a 1e-5 s
  switch interval, three runs each.
* **Every run of record reproduces.** Re-run at this code: Phase 7's messaging
  exit (2,415 rows) and Phase 6's knowledge exit (1,381 rows) are identical to
  their records but for timestamps and provenance; Phase 5's exit (26 rows,
  532 decisions) is identical in everything it recorded -- its belief snapshots
  predate the fields Phase 6 added. No decision moved, so no record needed a
  note.

**Tests: 7 new, in `tests/test_clock.py`:** the forced race always seen; late
sleepers wake at their own time and do not wait for each other; a thread
leaving at the instant releases a late sleeper; a late sleep does not make a
thread late for good; a sleep cut short by an exception leaves nothing
registered; alone, unshared or on real time it is a plain sleep; and the
agent's tick uses it.

**Mutations: 10, all caught.** The first pass caught 8; the two survivors were
test gaps -- a thread left marked late after a late sleep, and left marked
late when it leaves -- and the last two tests above are theirs. Reviewing the
fix first took out two redundant lines (a notify after waking, and the caller
skipping itself), so that every line left is tested.

**The goldens did not move.** `record_golden.py --check` matches all four.
739 tests pass, 22 skipped; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-02 | **The thirteen named types, not fourteen** | The source plan's count and its list disagree; filling the gap would put words in the plan's mouth |
| 2026-11-02 | **A payload schema only for a type in use; any other type is refused** | A type's payload is decided when a phase needs it, and not before; an unschema'd message cannot slip through |
| 2026-11-02 | **The envelope validates; the copies are the bus's** | No two agents may share a mutable payload; that is a property of delivery, and keeping the module free of dunders keeps it inside the boundary |
| 2026-11-02 | **Delivery is judged when a message is sent, over a direct link within 100 m** | Phase 4's hard edge, the evaluator's own rule; judging at sending keeps "was it delivered" a fact of one instant. Relays, latency and loss are Phase 10's |
| 2026-11-02 | **A concurrency test may set Python's switch interval** | A race the GIL hides at the default 5 ms is real all the same; forcing frequent switches makes the test certain rather than lucky, and the interval is restored after |
| 2026-11-02 | **A message "influenced a decision" if the policy read its record while deciding; "in the belief" is kept beside it** | The first is what a decision rested on; the second is what it could have rested on. The validation step's reads are not the policy's, and a policy reaching past `teammate()` and `current_teammates()` would not be counted |
| 2026-11-02 | **A heartbeat carries task and stage, not only who and where** | A record is the latest report; a bare heartbeat after a status would wipe the task |
| 2026-11-02 | **Messages are delayed a fixed 0.1 s, below the 0.5 s tick** | Zero delay let thread order decide whether a same-instant message was read, so beliefs varied run to run; a fixed sub-tick delay keeps "read at the next tick" and makes it certain. A modelling choice, not a radio claim |
| 2026-11-02 | **An agent's latency estimate is a message's age when read** | It cannot see the bus's delay, only when a message was sent and when it took it in; 0.5 s is the truthful figure from its side |
| 2026-11-02 | **Each seed is flown talking, blocked and silent** | "Only when delivered" needs a case where messages are sent and not delivered; the blocked flight is that case, and the silent one is the reference the others' decisions are held to |
| 2026-11-02 | **A heard teammate's position may stand only in its own record, and must be true to when it spoke** | The leak check now has messages to allow for; allowing them only in the record that came in one, and checking that record against the truth, keeps the check as strict as before |
| 2026-11-04 | **Fix the same-instant race in the clock: an agent's tick wakes after everything else due then** | It is a defect of the shared timeline, so it is fixed there; moving the agents' ticks off the skills' instants would have moved every decision time, and the runs of record would no longer reproduce |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
