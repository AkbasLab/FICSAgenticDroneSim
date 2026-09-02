# Project Documentation

A dedicated section of the repository where every phase of the project is clearly documented, including the steps, tools, procedures, and important decisions made throughout development. This documentation will improve reproducibility and allow new team members or contributors who are unfamiliar with the project to quickly understand the workflow, set up the necessary environment, and follow the same process without needing extensive prior knowledge or guidance.

Research direction by Dr. M. Ilhan Akbas, FICS Lab, Embry-Riddle Aeronautical
University.

| Phase | Theme | Exit criterion | Tests |
|---|---|---|---|
| 1 | Natural language → flight | An English instruction flies a validated plan | — |
| 2 | Multi-drone + architecture | Same behavior, now behind clean interfaces | 4 |
| 3 | High-level skills | Four drones run contract-bound skills concurrently | 12 |
| 4 | Canonical mission | A scripted controller completes the scored mission | 6 |
| 5 | Persistent agent | One agent completes a task with no preflight plan | 5 |
| 6 | Belief state | The log shows what the agent knew *and didn't* | 11 |
| 7 | Message protocol | Four agents coordinate only via delivered messages | 14 |
| 8 | Task allocation | Four drones divide the work with no central assignment | 21 |
| 9 | Roles + recovery | Kill one drone; the rest reassign its work and finish | 22 |
| — | Simulator path | Every `--airsim` entry point runs end to end | 13 |

**86 tests, 7 demos, none requiring a simulator, GPU or API key:**

```bash
python scripts/run_all_tests.py
```

---

## Phase 1 — Natural-language flight planning

**Goal.** An operator types a plain-English instruction; a language model turns
it into a validated sequence of flight actions; the drone executes it.

**Built.** CARLA-Air v0.1.7 (CARLA 0.9.16 + AirSim 1.8.1 in one Unreal 4.26
process) set up from scratch on Windows, with the AirSim Python client, Ollama
for local models, and cloud API access. Nine low-level primitives the planner may
emit — `arm_takeoff`, `fly_to`, `fly_straight`, `fly_backward`, `fly_left`,
`fly_right`, `hover`, `set_altitude`, `land` — with every plan validated against
that vocabulary and its required parameters before anything flies. Four
interchangeable planners: Gemini (cloud), Llama 3.1 8B and Mistral-Nemo 12B
(local via Ollama on CPU), and a deterministic keyword policy used as a control.

**The interesting problem.** The local models silently collapsed multi-step
instructions into a single action — "fly forward, turn left, then land" returned
one step. The fix depended on diagnosing it as an *output-format* problem rather
than a reasoning one: constraining generation with a JSON schema
(`{"plan": [...]}`) made both local models produce correct multi-step plans.

**Also solved.** AirSim's drone doesn't collide with CARLA's ground, so naive
landing either sank through the terrain or stopped in mid-air. Fixed by recording
ground level before takeoff, descending fast to 4 m above it, settling, then a
slow final approach and disarm.

---

## Phase 2 — Multi-drone flight and an architecture to build on

**Goal.** Fly several drones at once, and reorganize the prototype so the later
phases have something to attach to.

**Built.** An automated benchmark comparing the planners on plan correctness,
consistency across repeated runs, and latency, on both a standard and a
deliberately harder instruction set. Then a restructure of the flat scripts into
two interfaces that everything since has been built on:

- **`MissionPlanner`** — `decide(context) -> AgentDecision`. Gemini, Llama,
  Mistral and the rule policy all implement it; the agent doesn't know which it
  holds.
- **`VehicleAdapter`** — navigation primitives and state. Agents never call
  AirSim directly, so the same code runs against the real simulator or a
  kinematic mock.

**The interesting problem.** With multiple drones, vehicles started interfering —
swapping speeds, stalling, behaving erratically. The cause was a shared AirSim
RPC client across the threads flying them; the client is not thread-safe. Fixed
with one `MultirotorClient` per vehicle.

**Exit criterion.** The refactor had to change *structure only*. Four
behavior-preservation tests run missions through the new pipeline on the mock
adapter with the deterministic policy and assert the exact sequence of actions
each drone executes — they still pass today, eight phases later.

---

## Phase 3 — High-level skills with formal contracts

**Goal.** Give the agent a mission-level vocabulary instead of directional
commands, so later phases reason about *what to do*, not *how to move*.

**Built.** Eleven skills — `TAKE_OFF`, `GO_TO_WAYPOINT`, `FOLLOW_WAYPOINTS`,
`SEARCH_REGION`, `INSPECT_POINT`, `HOLD_POSITION`, `RENDEZVOUS`, `ACT_AS_RELAY`,
`RETURN_HOME`, `LAND`, `EMERGENCY_HOLD` — each with a typed command and a
**formal contract**: preconditions, success and failure conditions, timeout,
abort behavior, and expected state change. Each returns a structured
`SkillResult` (`success | failed | aborted | timeout`) with timing, final
position and an error code.

The contract is enforced, not decorative: a waypoint 500 m away with a 2-second
timeout returns `TIMEOUT`, not `SUCCESS`. That is what makes a skill result
something the agent can *reason about* in later phases.

**Exit criterion.** Four drones take off, fly to distinct waypoints, hold,
return and land — every skill reporting success, concurrently.

---

## Phase 4 — The canonical mission and how to score it

**Goal.** One fixed world that every later experiment runs against, so results
stay comparable as the architecture changes.

**Built.** `configs/missions/search_relay_001.yaml`: a base station, four
rectangular search sectors, two targets, a restricted no-fly region, four drones
with a battery budget, a comms range and a deadline — all declarative.

**Target detection is deliberately geometric, with no neural network.** A target
is found when a drone's path stays inside its detection radius long enough. This
is the point: a mission failure is then attributable to coordination,
communication or control, never to a perception model.

**Evaluation** scores a run against every success criterion — sector coverage,
targets detected *and reported to base*, no restricted-zone entry, no separation
violation, battery and deadline respected, all drones home safely. Three of the
six tests deliberately feed the evaluator bad runs and assert it catches each,
because a scorer that can only say PASS proves nothing.

**Exit criterion.** A fully scripted, *non-agentic* controller completes the
mission — 100% coverage, both targets found. That is the baseline the coordinated
architecture has to beat.

---

## Phase 5 — Persistent closed-loop agent

**Goal.** Replace one-shot planning with an agent that decides continuously.

**Built.** The lifecycle loop: `observe → update belief → select objective →
choose skill → validate → execute → verify`. The agent is handed a **task**, not
an action list, and picks one skill at a time based on what just happened.

**Replanning is event-driven.** The agent re-decides only on events — a skill
finished, a target was seen, a battery threshold crossed, a safety guard fired —
never in a busy loop, so low-level motion never waits on the decision layer.

**The deterministic policy came first, before any LLM**, as both a debugging tool
and a research baseline. A separate `Guardian` gets the last word on every
command, so an unsafe action never reaches the vehicle — and the LLM policy later
is held to the same rules without being trusted to enforce them.

**Exit criterion.** One agent completes a search task with no preflight plan. The
decision trace is the evidence:

```
task_assigned->take_off → skill_succeeded->go_to_sector
→ skill_succeeded->search_sector → target_detected->report
→ report_sent->return_home → skill_succeeded->land → done
```

Every objective was chosen in response to something that happened. Low battery
makes it break off and land safely; a failed navigation skill is retried and
recovered.

---

## Phase 6 — Structured belief, and the line between truth and belief

**Goal.** Give each drone real memory, and make its decisions auditable.

**Built.** An explicit typed belief state — `self`, `mission`, `local_map`,
`team`, `communication`, `assumptions` — deliberately **not** an LLM conversation
transcript, because a transcript can't answer "what did this agent know about
Drone2 at t=140?". The Phase 5 interface was preserved as properties over the new
structure, so nothing downstream had to change.

**Truth is separated from belief.** Ground truth belongs to the simulator and
evaluator; the only bridge into an agent is a `SensorModel` returning what that
drone could actually perceive from where it flew.

**This phase caught a real flaw in Phase 5.** The agent had been handed the
scenario's target list, so it was "detecting" targets it already knew about —
exactly the accidental-global-information problem that would have invalidated
every later decentralization result. Fixed, and now enforced two ways: a test
that walks the belief's object graph for smuggled ground-truth objects, and a
behavioral test that the agent finds the target in the sector it searched but
never learns the other one exists.

**Beliefs age.** Every teammate record carries a timestamp, source, confidence
and expiry, with confidence decaying by half-life — a 45-second-old position
report shows as stale, not current.

**Exit criterion.** The logger records, for each decision, what the agent knew
**and what it did not**:

```
[step 3 t=6.2s] Drone1 triggers=skill_succeeded
    KNEW    : pos=[10, 10, -8.0] battery=99% searched=[] targets=[]
    DID NOT KNOW: sector S1 not searched by me; no targets observed yet
    DECIDED : search_sector via search_region -> success
```

---

## Phase 7 — Inter-agent message protocol

**Goal.** Let the team talk, under perfect communication first. Degradation only
after the protocol works.

**Built.** Thirteen message types over one common envelope (id, type, sender,
recipients, mission, timestamp, sequence number, TTL, payload, confidence), so
ordering, expiry, addressing and logging are implemented once rather than per
type.

**No hidden global communication.** The bus is central simulation
infrastructure, but agents never hold one — each holds an `AgentLink` exposing
exactly two methods, `send()` and `receive_available()`. An agent cannot
enumerate peers, read another inbox, see what is in flight, or inspect what was
dropped.

The strongest check is a **blackout test**: the same four-agent mission with a bus
that delivers nothing, asserting every agent's team belief stays completely
empty. It passes — so team beliefs demonstrably update *only* on delivered
messages, with no back channel.

**Every message is logged** with creation, scheduled and actual delivery,
delivered/dropped status, sender, recipient, size, expiry, and whether it
influenced a decision.

**Exit criterion.** Four agents fly the mission together, interleaved by
simulated clock so messages cross mid-flight. All four complete; target knowledge
spreads by `TARGET_FOUND`, and a drone searching an empty sector still learns
both targets — recorded as second-hand rather than its own observation.

**Worth noting.** The first run showed 21 drops under "perfect" communication.
None were link loss: heartbeat TTL was shorter than a 70-second search sweep, so
messages aged out before agents next checked their inbox. TTLs were raised above
skill duration, and the statistics now separate link loss from expiry, so
"perfect" is visibly perfect.

---

## Phase 8 — Decentralized task allocation, without an LLM

**Goal.** Have the team divide the work itself, deterministically — so that when
agentic reasoning arrives, its contribution can be measured against this.

**Built.** Work as explicit `MissionTask` objects (type, region, priority,
required capabilities, deadline, status, assignee, lease, version), and a
**contract-net protocol** running independently on every drone: announce → bid →
claim → acknowledge → report progress. No auctioneer anywhere.

**Bids are deterministic and transparent:**

```
Bid(i,k) = w_d·distance + w_b·battery + w_l·workload + w_c·comms-risk + w_r·role-mismatch
```

Lowest wins, ties break on vehicle ID, and every bid keeps its term-by-term
breakdown — so you can see *why* a drone won a sector, which is what makes the
eventual comparison against an LLM allocator meaningful.

**Leases make recovery automatic.** A claim is not permanent; the holder must
keep reporting progress. Go silent and the lease expires, the task is announced
again, and a teammate takes it over.

**The interesting problem.** At zero latency the bidding separated cleanly and no
simultaneous claims ever occurred — so the conflict path was untested. Adding
message latency to provoke it exposed a real bug: all four drones claimed all
four sectors and flew every one, four times the necessary work.

The cause was that each agent keeps its own copy of the board, so `version += 1`
gave every agent a private counter — `Drone1 v3` and `Drone2 v3` were unrelated
numbers, and the rule "higher version wins" was comparing meaningless values, so
a stale claim could out-rank a newer one. Fixed by making the version a **Lamport
clock** (`max(seen) + 1`): versions become globally ordered, and two genuinely
simultaneous claims land on the *same* version, which is exactly the case the bid
and agent-ID rules exist to settle. Lease renewals no longer bump the version
either, since a holder could otherwise out-rank rivals just by reporting often.

After the fix, at 0 / 20 / 60 seconds of latency: 0 / 44 / 48 conflicts raised,
all resolved, every board converged, no sector flown twice.

**Exit criterion.** Four drones receive one mission, divide the sectors with no
central assignment, complete the work, and converge on a single holder per task.

---

## Phase 9 — Dynamic roles and failure recovery

**Goal.** Let the team change shape, not just its to-do list, and keep going when
a drone is lost.

**Built.** Three roles: `SCOUT` (searches), `RELAY` (holds station to keep the
team connected), `RESERVE` (spare capacity) — each agent choosing its own from
local belief, deterministically. A RELAY drops the `search` capability, so the
capability check already in the bidding path stops handing it sectors; no
special-casing in the allocator.

**Failure detection is graded on purpose.** `HEALTHY → SUSPECTED → UNREACHABLE →
FAILED`, with `RECOVERED` if a peer speaks again. A missed heartbeat means "I
have not heard from you", which is not the same as "you have crashed" — comms
loss is common, vehicle loss is not. Declaring failure on one missed message
would be worse than no detection at all, because sectors would be pulled off
healthy drones that were briefly quiet. That restraint is asserted as a test, as
is the fact that a peer we have never heard from at t=0 is not "failed".

**The interesting problem.** Three separate bugs, all of them really one issue:
the relationship between lease duration and skill duration.

1. *A drone lost its own task mid-flight.* `my_tasks()` filtered on lease
   validity, so once a 40 s lease lapsed during a 70 s sweep, the drone could no
   longer renew what it had already stopped "holding", it abandoned the sector
   it was halfway through. Fixed by separating `claimed_by()` (how a drone sees
   itself — lease-independent) from `held_by()` (how *others* judge it).
2. *Teammates stole sectors from healthy drones.* With a lease shorter than a
   sweep, other agents saw the lease expire and rebid on work that was actively
   being flown. The constraint is now explicit: **the lease must exceed the
   longest skill.**
3. *But then a dead drone's work stayed locked.* A 150 s lease means waiting out
   most of the mission for a drone the team already knows is gone. Fixed by
   letting health detection short-circuit the lease, a task whose holder is
   believed failed becomes available immediately, without waiting for expiry.

A fourth, smaller one: an agent with no task and no pending events quit the loop
**while still airborne**. It now waits a bounded number of rounds for work to
appear, then flies home rather than being left stranded.

**Exit criterion.** One of four drones is switched off mid-mission, no flight,
no sensing, no heartbeats, and nobody is told. The others detect the silence,
reclaim its sector, and finish:

```
!! Drone2 switched off at t=15s (teammates not informed)
detected the loss : Drone3:unreachable, Drone4:failed
sectors completed : 4/4
  SEARCH_SECTOR_S2     by Drone4  <- reassigned after the failure
human commands after launch: 0
```

Both halves are checked negatively too. Raise the heartbeat interval
(`--heartbeat 200`) and the team never concludes the drone is gone, so the sector
is never reclaimed - 3/4. Shorten the lease below a sweep (`--lease 40`) and
drones lose work they are actively flying - 1/4. The passing result depends on
both mechanisms, not on luck.

**Controlled emergence, defined operationally** (9.4) and checked as assertions
rather than asserted in prose: a team-level objective is given; no central
controller specifies any drone's task sequence; agents use only local beliefs and
delivered messages (verified by scanning each belief for ground-truth objects);
allocation and role changes arise from agent interaction; and the deterministic
safety constraints still hold, every surviving drone lands safely at home.
