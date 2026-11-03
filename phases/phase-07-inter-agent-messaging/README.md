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

**Met:** no · **Evidence:** —

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
| The exit | `agentic_uav/experiments/`, `scripts/`, `results/`, `evidence/` | step 5 |
| Optional live flight; close | `results/`, `evidence/` | step 6 |

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

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
