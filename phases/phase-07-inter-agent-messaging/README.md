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
| The bus, and the two-function handle | `agentic_uav/simulator/message_bus.py` | step 2 |
| The message log | `agentic_uav/simulator/message_bus.py`, `agentic_uav/agents/` | step 3 |
| Agents that talk | `agentic_uav/agents/drone_agent.py`, `agentic_uav/agents/belief_state.py` | step 4 |
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

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-02 | **The thirteen named types, not fourteen** | The source plan's count and its list disagree; filling the gap would put words in the plan's mouth |
| 2026-11-02 | **A payload schema only for a type in use; any other type is refused** | A type's payload is decided when a phase needs it, and not before; an unschema'd message cannot slip through |
| 2026-11-02 | **The envelope validates; the copies are the bus's** | No two agents may share a mutable payload; that is a property of delivery, and keeping the module free of dunders keeps it inside the boundary |

## Open questions

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
