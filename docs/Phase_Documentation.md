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
| 10 | Degraded comms | Replay one mission under four comms conditions, reproducibly | 30 |
| 11 | Runtime-safety guardian | Every unsafe command is blocked and named | 45 |
| — | Simulator path | Every `--airsim` entry point runs end to end | 16 |

**186 tests, 11 demos, none requiring a simulator, GPU or API key:**

```bash
python scripts/run_all_tests.py
```

---

## Before you start — tools, setup, and what each phase needs

### What you actually need

Most of this project runs on **Python alone**. The simulator and the language
models are only needed for specific phases, so do not install everything before
you begin.

| Tool | Version | Needed for | Required? |
|---|---|---|---|
| Python | 3.10 | everything | **Yes** |
| `numpy`, `PyYAML`, `matplotlib` | see `requirements.txt` | everything | **Yes** |
| Ollama + `llama3.1:8b`, `mistral-nemo` | latest | Phase 1–2 local LLM planning | Optional |
| Google Gemini API key | `google-genai` SDK | Phase 1–2 cloud planning | Optional |
| CARLA-Air (CARLA 0.9.16 + AirSim 1.8.1, UE 4.26) | v0.1.7 | any `--airsim` run | Optional |

**Phases 3 through 10 need nothing but Python.** They run against a
deterministic kinematic mock simulator, which is why the whole test suite works
on a laptop with no GPU.

### One-time setup (all phases)

```bash
conda create -n carlaAir python=3.10
conda activate carlaAir
cd AgenticDroneSimRepo
pip install -r requirements.txt

python scripts/run_all_tests.py      # confirm the install: 140 tests, 9 demos
```

If `run_all_tests.py` is green, you are ready for Phases 3–10.

### Additional setup for LLM planning (Phases 1–2 only)

Local models, via Ollama:

```bash
ollama pull llama3.1:8b
ollama pull mistral-nemo
```

Cloud model — put the key in a `.env` file in the repo root:

```powershell
# Windows PowerShell. Use -Encoding ascii: `echo >` writes UTF-16, which the
# loader cannot read and which produces "UnicodeDecodeError: 0xff".
Set-Content -Path .env -Value "GEMINI_API_KEY=your_key_here" -Encoding ascii
```

Never commit `.env`. It is gitignored; keep it that way.

### Additional setup for the simulator (`--airsim` runs)

1. Launch CARLA-Air and wait for **Town10HD** to finish loading. Commands sent
   during load fail in confusing ways.
2. Confirm the ports: CARLA on **2000**, AirSim RPC on **41451**.
3. Generate `settings.json` (written to `~/Documents/AirSim/`) and **restart
   CARLA-Air** — settings are only read at startup:

```bash
python -c "from agentic_uav.simulator.scenario_manager import write_airsim_settings; print(write_airsim_settings(4))"
```

4. Verify the connection before running anything else:

```bash
python -c "import airsim; c=airsim.MultirotorClient(); c.confirmConnection(); print(c.listVehicles())"
```

Expect `['Drone1', 'Drone2', 'Drone3', 'Drone4']`. If this fails, stop — nothing
downstream will work. The Phase 4–10 scripts also self-heal by calling
`spawn_missing_drones()`, but a clean `settings.json` is more reliable.

See `docs/SIM_TESTING.md` for the full simulator walkthrough and
`docs/TESTING.md` for how to verify each phase and deliberately break it.

### Reading a phase section

Each phase below ends with a **How to run it** block giving the exact commands,
the files involved, and the parameters worth changing. A consolidated command
reference and a parameter-tuning table are in the appendices at the end.

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


### How to run it

**Needs:** Python, plus Ollama (local models) or a Gemini key (cloud model).
The `rule` planner needs neither and is the right choice for a first run.

```bash
# no LLM, no simulator - deterministic keyword planner on the mock.
# This PROMPTS for each drone's instruction; type e.g.
#   fly forward 5 seconds then land
python scripts/run_single_mission.py --planner rule --adapter mock --drones 1

# non-interactive: read the instructions from a JSON file
python scripts/run_single_mission.py --planner rule --adapter mock \
    --mission configs/missions/example_mission.json

# local models (Ollama running)
python scripts/run_single_mission.py --planner llama --adapter mock --drones 1
python scripts/run_single_mission.py --planner mistral --adapter mock --drones 1

# cloud model (.env with GEMINI_API_KEY)
python scripts/run_single_mission.py --planner gemini --adapter mock --drones 1

# fly it for real
python scripts/run_single_mission.py --planner gemini --adapter airsim --drones 1
```

**Options:** `--planner gemini|llama|mistral|rule` · `--adapter mock|airsim` ·
`--drones N` (prompts for N instructions) · `--mission <path.json>`

**Note:** with no `--mission`, the script is **interactive** — it waits for you
to type each drone's instruction, so it will appear to hang if you are not
expecting a prompt. `--mission` takes a **path to a JSON file**, not an
instruction string:

```json
{
  "drones": {
    "Drone1": "fly forward 5 seconds then land",
    "Drone2": "go up 15 meters, hover 3 seconds, then come back and land"
  }
}
```

There is a ready-made one at `configs/missions/example_mission.json`.

**Files:** `agentic_uav/planners/` (one file per planner, plus
`base_planner.py` holding the shared prompt, few-shot examples and the JSON
schema) · `agentic_uav/control/action_executor.py` · `agentic_uav/agents/rule_policy.py`

**Worth adjusting:** the action vocabulary and required parameters live in
`ACTION_PARAMS` in `agentic_uav/control/skills.py`; the schema that forces
multi-step plans is `build_plan_schema()` in the same file. Model names are
`MODEL` constants at the top of each planner. Local models run CPU-only
(`num_gpu: 0`) so the GPU stays free for the simulator — change that in
`llama_planner.py` if you want GPU inference.

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


### How to run it

**Needs:** Python only.

```bash
# behaviour-preservation check - the refactor must not change flight behaviour
python tests/test_behavior_preservation.py

# several drones at once
python scripts/run_single_mission.py --planner rule --adapter mock --drones 4
python scripts/run_single_mission.py --planner mistral --adapter airsim --drones 2
```

**Files:** `agentic_uav/planners/base_planner.py` (the `MissionPlanner`
interface) · `agentic_uav/core/models.py` (the `VehicleAdapter` interface) ·
`agentic_uav/simulator/airsim_adapter.py` · `agentic_uav/simulator/mock_adapter.py`

**Worth knowing:** `AirSimVehicleAdapter._client_for()` creates **one
`MultirotorClient` per vehicle**. Do not change this to a shared client — the
AirSim RPC client is not thread-safe, and sharing it makes drones swap speeds
and stall. Flight constants (altitude, speeds, landing profile) are all in
`agentic_uav/control/navigation.py`.

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


### How to run it

**Needs:** Python only (add CARLA-Air for `--adapter airsim`).

```bash
python scripts/phase3_demo.py                     # 4 drones, exit criterion
python scripts/phase3_showcase.py                 # all 11 skills in sequence
python tests/test_skills.py                       # 12 tests

python scripts/phase3_demo.py --adapter airsim    # fly it
python scripts/phase3_showcase.py --adapter airsim
```

**Files:** `agentic_uav/control/skills.py` (typed commands + `SkillContract`
for each skill) · `agentic_uav/control/skill_executor.py` (executes them and
enforces the contract) · `agentic_uav/control/navigation.py` (flight constants)

**Worth adjusting:** each skill's defaults — `speed_mps`, `tolerance_m`,
`timeout_s`, and `lane_spacing_m` for `SearchRegionCommand` — are dataclass
fields in `skills.py`. Lane spacing controls how thoroughly a sector is swept;
at the default 8 m with a detection radius of 8 m, coverage comes out at 100%.
Widen it and coverage drops.

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


### How to run it

**Needs:** Python only (add CARLA-Air for `--airsim`).

```bash
python scripts/run_canonical_mission.py           # scored 4-drone mission
python scripts/run_canonical_mission.py --airsim  # fly it
python scripts/plot_mission_layout.py --paths     # regenerate the layout figure
python tests/test_mission.py                      # 6 tests
```

**Options:** `--scenario path/to/other.yaml` · `--airsim`

**Files:** `configs/missions/search_relay_001.yaml` (**the scenario — edit this
to change the world**) · `agentic_uav/experiments/mission_runner.py` (the
scripted baseline controller) · `agentic_uav/experiments/metrics.py` (the
scorer) · `agentic_uav/simulator/target_model.py` (geometric detection)

**Worth adjusting — all in the YAML:** sector footprints, target positions and
`detection_radius_m`, the restricted-zone polygon, `deadline_s`,
`required_coverage`, `min_separation_m`, per-vehicle `battery_s`, and
`random_seed`. To add a scenario, copy the YAML, change `scenario_id`, and pass
it with `--scenario`.

**Careful:** keep the restricted zone clear of the base and of the routes drones
fly to their sectors, or every run fails the no-fly check. Coverage is sampled on
a 5 m grid with an 8 m path radius (`COVERAGE_CELL_M` / `COVERAGE_RADIUS_M` in
`metrics.py`).

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


### How to run it

**Needs:** Python only (add CARLA-Air for `--airsim`).

```bash
python scripts/run_persistent_agent.py                  # completes the task
python scripts/run_persistent_agent.py --battery 8      # low-battery safe abort
python scripts/run_persistent_agent.py --sector S3      # a different sector
python scripts/run_persistent_agent.py --airsim         # fly it
python tests/test_persistent_agent.py                   # 5 tests
```

**Options:** `--sector S1|S2|S3|S4` · `--battery <seconds>` · `--scenario` ·
`--airsim` · `--log` · `--log-json out.json`

**Files:** `agentic_uav/agents/persistent_agent.py` (the lifecycle loop) ·
`agentic_uav/agents/search_policy.py` (the deterministic policy) ·
`agentic_uav/agents/guardian.py` (the safety layer) ·
`agentic_uav/agents/objectives.py` (objectives and replan events)

**Worth adjusting:** `low_battery_frac` (0.30) and `critical_battery_frac`
(0.12) are constructor arguments on `PersistentAgent`; `ROLE_BATTERY_FLOOR`
(0.35) is in `role_manager.py`; `max_nav_retries` (2) is on `SearchAgentPolicy`;
`MAX_IDLE_ROUNDS` (3) at the top of `persistent_agent.py` controls how long an
agent with no work waits before flying home.

**On `--battery`:** the value is in **simulated seconds on the mock but real
seconds in AirSim**. On the mock, 8 is a good demo value. In AirSim start around
45 and halve it if the agent still completes.

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


### How to run it

**Needs:** Python only.

```bash
python scripts/run_persistent_agent.py --log                    # audit trail
python scripts/run_persistent_agent.py --log --log-json run.json
python tests/test_belief_state.py                               # 11 tests
```

`run.json` holds the full belief snapshot at every decision — that is the file
to analyse a run from afterwards.

**Files:** `agentic_uav/agents/belief_schema.py` (the six sections) ·
`agentic_uav/agents/belief_state.py` · `agentic_uav/simulator/ground_truth.py`
(`GroundTruth` + `SensorModel`) · `agentic_uav/experiments/decision_log.py`

**Worth adjusting:** information lifetimes are `DEFAULT_TTL` per `Source` in
`belief_schema.py`; confidence decays with a 20 s half-life
(`Provenance.decayed_confidence`).

**Rule to preserve:** an agent must never hold a `GroundTruth`,
`MissionScenario` or `Target`. Everything reaches belief through `SensorModel`
or a delivered message. Two tests in `test_belief_state.py` enforce this — if
you add a feature that hands an agent scenario data, they will fail, and that is
the point.

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


### How to run it

**Needs:** Python only (add CARLA-Air for `--airsim`).

```bash
python scripts/run_team_mission.py                      # 4 agents together
python scripts/run_team_mission.py --messages           # per-message log
python scripts/run_team_mission.py --beliefs            # each agent's team view
python scripts/run_team_mission.py --airsim             # fly it (threaded)
python tests/test_messaging.py                          # 14 tests
```

**Options:** `--messages` · `--beliefs` · `--log-json msgs.json` · `--airsim`

**Files:** `agentic_uav/coordination/protocols.py` (13 message types + the
envelope) · `agentic_uav/coordination/message_bus.py` (`MessageBus` and the
two-method `AgentLink`) · `agentic_uav/experiments/team_runner.py`

**Worth adjusting:** message TTLs are in `comms_conditions.TTL_BY_TYPE`. They
**must exceed the longest skill** (a sector sweep is ~70 s) or messages age out
before the recipient next checks its inbox and appear as losses.

**Two runners:** `run_team()` interleaves agents on a simulated clock — exact and
deterministic, used for all mock experiments. `run_team_threaded()` gives each
drone its own thread and AirSim client so the fleet flies concurrently; it is
selected automatically by `--airsim` and is **not** deterministic.

**Rule to preserve:** agents hold an `AgentLink` (`send` / `receive_available`),
never the bus. The blackout test in `test_messaging.py` reruns the mission with a
bus that delivers nothing and asserts every team belief stays empty.

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


### How to run it

**Needs:** Python only (add CARLA-Air for `--airsim`).

```bash
python scripts/run_allocation_mission.py                # 4 drones divide the work
python scripts/run_allocation_mission.py --bids         # every bid, explained
python scripts/run_allocation_mission.py --conflicts    # duplicate-claim log
python scripts/run_allocation_mission.py --lease 1      # force lease expiry
python scripts/run_allocation_mission.py --airsim
python tests/test_allocation.py                         # 21 tests
```

**Options:** `--bids` · `--conflicts` · `--lease <seconds>` · `--scenario` ·
`--airsim`

**Files:** `agentic_uav/coordination/tasks.py` (`MissionTask`, `TaskBoard`) ·
`agentic_uav/coordination/bidding.py` (the cost function) ·
`agentic_uav/coordination/task_allocator.py` (the contract-net protocol)

**Worth adjusting:** the bid weights are `BidWeights` in `bidding.py`
(`w_distance` 1.0, `w_battery` 1.5, `w_workload` 2.0, `w_comms` 0.5, `w_role`
5.0 — the last is high enough to be disqualifying). `DEFAULT_LEASE_S` (120) and
`DEFAULT_BID_WINDOW_S` (5) are at the top of `task_allocator.py`.
`tasks_from_scenario()` builds the task list from the YAML; pass
`include_relay=True` to add the relay task.

**Constraint that matters most:** the **lease must be longer than the longest
skill**. Shorter, and teammates see a busy drone's lease expire and steal the
sector it is actively flying. Try `--lease 40` to see this happen.

---

## Phase 9 — Dynamic roles and failure recovery

**Goal.** Let the team change shape, not just its to-do list, and keep going when
a drone is lost.

**Built.** Three roles — `SCOUT` (searches), `RELAY` (holds station to keep the
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
   longer renew what it had already stopped "holding" — it abandoned the sector
   it was halfway through. Fixed by separating `claimed_by()` (how a drone sees
   itself — lease-independent) from `held_by()` (how *others* judge it).
2. *Teammates stole sectors from healthy drones.* With a lease shorter than a
   sweep, other agents saw the lease expire and rebid on work that was actively
   being flown. The constraint is now explicit: **the lease must exceed the
   longest skill.**
3. *But then a dead drone's work stayed locked.* A 150 s lease means waiting out
   most of the mission for a drone the team already knows is gone. Fixed by
   letting health detection short-circuit the lease — a task whose holder is
   believed failed becomes available immediately, without waiting for expiry.

A fourth, smaller one: an agent with no task and no pending events quit the loop
**while still airborne**. It now waits a bounded number of rounds for work to
appear, then flies home rather than being left stranded.

**Exit criterion.** One of four drones is switched off mid-mission — no flight,
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
is never reclaimed — 3/4. Shorten the lease below a sweep (`--lease 40`) and
drones lose work they are actively flying — 1/4. The passing result depends on
both mechanisms, not on luck.

**Controlled emergence, defined operationally** (9.4) and checked as assertions
rather than asserted in prose: a team-level objective is given; no central
controller specifies any drone's task sequence; agents use only local beliefs and
delivered messages (verified by scanning each belief for ground-truth objects);
allocation and role changes arise from agent interaction; and the deterministic
safety constraints still hold — every surviving drone lands safely at home.


### How to run it

**Needs:** Python only (add CARLA-Air for `--airsim`).

```bash
python scripts/run_failure_recovery.py                       # kill Drone2 at t=5s
python scripts/run_failure_recovery.py --health              # health transitions
python scripts/run_failure_recovery.py --roles               # role changes
python scripts/run_failure_recovery.py --kill Drone3 --at 40
python scripts/run_failure_recovery.py --airsim
python tests/test_roles_recovery.py                          # 22 tests
```

**Options:** `--kill <DroneN>` · `--at <sim seconds>` · `--lease <seconds>` ·
`--heartbeat <seconds>` · `--roles` · `--health` · `--airsim`

**Files:** `agentic_uav/coordination/roles.py` (`Role`, `HealthState`,
`HealthMonitor`) · `agentic_uav/coordination/role_manager.py` (the role policy) ·
`run_team_with_faults()` in `agentic_uav/experiments/team_runner.py`

**Worth adjusting:** the silence thresholds are multiples of the heartbeat
interval, at the top of `roles.py` — `SUSPECT_AFTER_MISSED` 2.0,
`UNREACHABLE_AFTER_MISSED` 4.0, `FAILED_AFTER_MISSED` 8.0. Lower them to detect
loss faster at the cost of false positives during ordinary comms glitches.

**Two settings that interact, and are easy to get wrong:**

* `--lease` must exceed the longest skill (~70 s). The default is 150.
  Try `--lease 40` and the run degrades to 1/4 sectors, because drones lose work
  they are actively flying.
* `--heartbeat` drives failure detection. Try `--heartbeat 200` and the run
  degrades to 3/4, because the team never concludes the missing drone is gone.

Only both together give 4/4. That is a useful demonstration that the result
depends on the mechanisms rather than on luck.

---

## Phase 10 — The degraded-communications simulator

**Goal.** Phase 7 proved the protocol under *perfect* communication. This is
where it gets tested honestly.

**Built.** A configurable, seeded `NetworkModel`: latency mean and jitter, packet
loss, message rate limit, bandwidth cap, communication range, plus burst loss,
partitions, interference zones and asymmetric links. Four named conditions —
`nominal`, `moderate`, `severe`, `partitioned` — so every experiment means the
same thing by those words.

**These numbers are experimental parameters, not claims about a real radio.**
They exist so two architectures can be compared under identical conditions.
Calibrating them against an operational system is separate work.

**Seeded and reproducible.** One RNG per run, drawn in a deterministic order
because the runner is single-threaded and stepped in simulated-time order. Same
seed means the same messages lost and the same latencies drawn — which is what
makes comparing two architectures "under the same degraded conditions" a
meaningful statement rather than a hopeful one.

**Message lifetimes by type.** A delayed message can arrive after it has stopped
being useful, so heartbeats and intents expire quickly while target reports live
long and mission constraints never expire. `link.send()` applies the per-type TTL
automatically.

**Agents estimate; they never read.** An agent cannot see
`packet_loss_probability`. It infers link quality from missing sequence numbers,
heartbeat arrival rate, message age on arrival, and whether anything is getting
through at all. A test walks each estimator's attributes to confirm no
`NetworkModel` or `NetworkProfile` is reachable from it, and a behavioural test
confirms agents estimate higher loss under `severe` than under `nominal` without
being told which condition they are in.

**Verified statistically, not assumed.** Thousands of messages per check: 10% and
30% configured loss land within a couple of points empirically; a 150±50 ms
profile produces a mean of 145–155 ms and a standard deviation of 45–55 ms;
latency never goes negative even when jitter exceeds the mean; partitions block
only across the split and only inside the window; expired messages are never
delivered; identical seeds reproduce identically and different seeds do not.

**Two honest findings.**

*The agent's "latency" estimate is not latency.* `now - message.timestamp` at
read time is dominated by the agent's own decision cadence — tens of seconds
between inbox checks — not by the wire. Renamed to **message age on arrival**,
which is the number the agent actually needs anyway, since it governs whether the
contents can still be trusted. A true one-way latency estimate would need an echo
protocol and a synchronised clock.

*The `severe` profile is dominated by its rate limit, not its packet loss.* At
4 messages/second, 568 of 744 messages were refused by the rate limiter versus 63
lost to the 30% packet-loss setting. The condition is behaving as configured, but
"severe" currently means "rate-starved" more than "lossy". Worth recalibrating in
the pilot experiments the spec calls for.

**Exit criterion.** The same mission replays under all four conditions with
reproducible delivery:

```
condition      sectors   sent  deliv   rate    delay  drops
nominal          4/4      315    303   96%   10.35s  none
moderate         4/4      282    240   85%   21.13s  packet_loss=32
severe           4/4      744     99   13%   31.09s  burst_loss=11, packet_loss=63, rate_limited=568
partitioned      4/4      426    289   68%   16.01s  packet_loss=15, partitioned=108, expired=2
```

Notably the mission completes under every condition, including one where 87% of
messages never arrive — each drone's own sector search does not depend on hearing
from anyone. That is a result about this scenario as much as about the
architecture, and the coordination-dependent scenarios are where the comparison
will actually bite.

### How to run it

**Needs:** Python only.

```bash
python scripts/run_comms_study.py                             # all four conditions
python scripts/run_comms_study.py --estimates                 # agents' own view
python scripts/run_comms_study.py --condition severe --messages
python scripts/run_comms_study.py --seed 42                   # a different draw
python tests/test_network.py                                  # 30 tests
```

**Options:** `--condition nominal|moderate|severe|partitioned` · `--seed N` ·
`--estimates` · `--messages` · `--lease` · `--heartbeat` · `--scenario`

**Files:** `agentic_uav/coordination/network_model.py` (`NetworkProfile`,
`NetworkModel`, `Partition`, `InterferenceZone`) ·
`agentic_uav/coordination/comms_conditions.py` (**the four conditions and the
per-type TTLs — edit here to add or retune a condition**) ·
`agentic_uav/agents/comms_estimator.py` (the agent-side estimate)

**Adding a condition:**

```python
# in comms_conditions.py
MY_CONDITION = _register(NetworkProfile(
    name="my_condition",
    latency_ms_mean=300.0,
    latency_ms_jitter=100.0,
    packet_loss_probability=0.2,
    message_rate_limit=None,          # messages/sec/sender, None = unlimited
    communication_range_m=None,       # metres, None = unlimited
))
ORDER.append("my_condition")          # so the study script picks it up
```

**Reproducibility:** pass the same `--seed` and you get the same losses and the
same latency draws. Different architectures compared under one seed are
comparing like with like; that is the whole reason the seed exists.

**Rule to preserve:** agents must never read the `NetworkProfile`. They estimate
link quality from sequence gaps, heartbeat arrival rate and message age. A test
in `test_network.py` walks each estimator for a smuggled network object.

**Two things not to misread in the output:** `msg_age` is how old messages are
when read (dominated by decision cadence), **not** wire latency; and `est_loss`
counts everything that failed to arrive, including rate-limited messages, so
under `severe` it legitimately exceeds the configured 30%.

---

## Phase 11 — An independent runtime-safety guardian

**Goal.** Every phase so far has trusted the policy. Phase 11 stops doing that.
A deterministic safety layer sits between *whatever proposed a command* and the
vehicle, so that a buggy rule policy, a future LLM policy, a corrupt message or
a unit-confusion error cannot fly the drone somewhere it should not go.

**Deterministic on purpose.** The guardian contains no model, no learned
component and no randomness. Same command plus same belief always produces the
same verdict, and it can always name which check failed and why. A guardrail
implemented as a second language model would inherit exactly the failure modes it
is meant to contain — wrong in novel ways, not exhaustively testable, unable to
explain itself to an auditor. A fixed list of bounded predicates can be all three.

**Ten checks**, each independently named so a rejection is always attributable:

| Check | Catches |
|---|---|
| `altitude_bounds` | below the floor (3 m) or above the ceiling (60 m) |
| `geofence` | a waypoint outside the operating box |
| `restricted_zones` | flight into a published no-fly polygon |
| `waypoint_validity` | `NaN`, `inf`, or coordinates beyond 300 m |
| `max_speed` | above 12 m/s, or negative |
| `command_timeout` | zero (can never succeed) or absurd (effectively unbounded) |
| `battery_reserve` | starting new work below the 10% reserve |
| `separation` | a waypoint on a teammate's known position |
| `landing_site` | landing where the belief says it is unsafe |
| `conflicting_commands` | a second command issued while one is still running |

**Four outcomes, and the distinction that matters.** `APPROVE` ·
`APPROVE_WITH_MODIFICATION` · `REJECT_AND_REPLAN` · `EXECUTE_SAFE_FALLBACK`. A
violation that can be *narrowed* into the envelope is narrowed — 120 m/s becomes
12 m/s, 1 m altitude becomes the floor — because refusing a command the agent
can safely have a weaker version of costs mission progress for no safety gain. A
violation that cannot be narrowed (a `NaN` waypoint, a no-fly zone) is refused
outright. The guardian has no authority to invent new work; when it substitutes,
it may only substitute one of five pre-agreed fallbacks: `HOLD_POSITION`,
`CLIMB_OR_DESCEND_TO_SAFE_LAYER`, `RETURN_HOME`, `LAND_AT_SAFE_LOCATION`,
`CONTINUE_LAST_VALID_PLAN`.

**Logged separately from the mission.** `GuardianLog` records the proposed
action, the rejection reason, what was substituted, which fallback fired and the
effect on the mission. The headline metric is **intervention rate** — the
fraction of proposed commands the guardian did not pass through unchanged. On a
healthy policy it should be ~0; a rising rate on an LLM policy is a measurement
of how often that policy proposes something unflyable, which is precisely the
number this project needs when the LLM planner arrives.

**Attacked, not assumed.** A safety layer nobody has attacked is an assumption.
`unsafe_injection.py` is the attack: a catalogue of 13 commands a compromised
policy could plausibly emit, each paired with the check that must catch it, plus
an `InjectingPolicy` that substitutes unsafe commands into a live mission so
containment can be observed end to end. Nothing in that module is used in normal
operation.

**A real flight bug found by the guardian.** The guardian flagged a *legitimate*
`return_home` as an altitude violation — and it was right. The policy was
targeting home at `z = 0`, which makes the drone descend while it translates
across the map instead of flying home at cruise altitude and landing as a
separate skill. That is a genuine bug the mock adapter had been forgiving for
six phases. Fixed in `search_policy.py`.

**Containment is not the same as safety, and `--repeat` proved it.** Running the
demo with a policy that stays broken for the whole mission, rather than for three
steps, exposed a design gap: every unsafe command was blocked — zero reached the
vehicle — and the drone still never came down. `REJECT_AND_REPLAN` quietly
assumes the policy can produce something better next time. A permanently broken
policy never will, so the guardian and the agent negotiated for 60 commands while
the aircraft held station until the step cap. Perfectly contained, and perfectly
unsafe.

The fix is escalation: after a bounded number of consecutive failures, the
guardian stops asking and flies the aircraft home itself. `EXECUTE_SAFE_FALLBACK`
already existed for this and had simply never fired in a real run.

**And the first version of that fix was evadable.** Counting consecutive
*rejections* looks right and is not. The injected sequence alternates an
out-of-bounds waypoint (rejected) with a 120 m/s speed (clamped and approved) —
so the rejection counter resets every other command and never reaches three. A
compromised policy could fly indefinitely while never once being rejected twice
in a row. A clamp is not a success; it still means the policy proposed something
unflyable. So the counter that governs escalation resets only on a command that
passed **every** check untouched:

| counter | increments on | resets on | threshold |
|---|---|---|---|
| `consecutive_rejections` | `REJECT_AND_REPLAN` | anything else | 3 |
| `consecutive_interventions` | anything that is not a clean approval | `APPROVE` only | 5 |

Either one tripping escalates, and an escalated fallback must *terminate the
flight* — `RETURN_HOME`, or `LAND_AT_SAFE_LOCATION` if already home. Holding
position or repeating the last valid plan would leave a compromised aircraft
airborne until the battery decided the outcome. With escalation in place the
permanently-broken run ends in 8 commands with the drone landed at home, instead
of 60 with it still flying.

**A correctness bug in the agent, found the same way.** With the policy broken on
every step, `_verify()` credited progress for the *objective* rather than for the
command actually executed — marking a sector "searched" when the command that ran
was a guardian fallback, not a sweep. It crashed loudly here, but the silent
version is worse: a mission reporting coverage no drone ever flew. Verification
is now keyed on the executed command type in `persistent_agent.py`.

**Exit criterion.** Every unsafe command is blocked, and a mission flown with a
deliberately compromised policy still ends safely — including when the policy
never recovers:

```
  blocked 13/13 (all unsafe commands stopped)

  commands evaluated : 7
  approved unchanged : 4
  interventions      : 3 (43% of commands)
  by outcome:  approve 4 · approve_with_modification 1 · reject_and_replan 2
  checks that failed:  geofence 2 · max_speed 1 · waypoint_validity 1

  unsafe commands that reached the vehicle: 0
  drone landed safely at home: True
```

And with `--repeat`, where the policy is broken from step 2 onward and never
recovers:

```
  commands evaluated : 8
  unsafe commands that reached the vehicle: 0
  drone landed safely at home: True
```

Every one of the 13 was caught by its *intended* check, not incidentally by
another one — which is what makes the catalogue a test of the checks rather than
a test of the envelope as a whole.

### How to run it

**Needs:** Python only.

```bash
python scripts/run_guardian_demo.py                  # catalogue; nothing flies
python scripts/run_guardian_demo.py --live           # + compromised-policy mission
python scripts/run_guardian_demo.py --case nan_waypoint   # one case in isolation
python scripts/run_guardian_demo.py --live --repeat  # policy stays broken throughout
python tests/test_guardian.py                        # 45 tests
```

Exit code 0 means every unsafe command was blocked. The catalogue run is the
fast check; `--live` is the one to show someone.

**Options:** `--live` · `--repeat` · `--case <name>` · `--scenario`

**Files:** `agentic_uav/agents/safety_guardian.py` (`SafetyLimits`,
`SafetyCheck`, `GuardianOutcome`, `FallbackAction`, `SafetyGuardian` — **edit
`SafetyLimits` to change the envelope**) ·
`agentic_uav/agents/unsafe_injection.py` (the 13-case catalogue and
`InjectingPolicy`) · `agentic_uav/experiments/guardian_log.py` (the audit log and
`intervention_rate`)

**Wiring it into an agent** — one keyword argument; nothing else changes:

```python
from agentic_uav.agents.safety_guardian import SafetyGuardian, SafetyLimits

agent = PersistentAgent(..., guardian=SafetyGuardian(
    limits=SafetyLimits.from_scenario(scenario)))
...
print(agent.guardian_log.format_summary())
```

`SafetyLimits.from_scenario()` builds the geofence as a 40 m margin around the
scenario's sectors and base, and inherits the scenario's restricted zones and
minimum separation. Pass `SafetyLimits(...)` directly to override any bound.

**Adding a check:**

```python
# in safety_guardian.py, add to the list built in evaluate()
def _check_my_rule(self, command, belief) -> SafetyCheck:
    if <unsafe condition>:
        return SafetyCheck("my_rule", passed=False, reason="...",
                           severity=Severity.HARD)   # HARD = cannot be narrowed
    return SafetyCheck("my_rule", passed=True)
```

Then add a matching `UnsafeCase` to `unsafe_injection.py` with
`expects_check="my_rule"`. A check without a case in the catalogue is an
untested check.

**Escalation thresholds** live on `SafetyGuardian` as `MAX_CONSECUTIVE_REJECTIONS`
(3) and `MAX_CONSECUTIVE_INTERVENTIONS` (5), and both are constructor arguments.
Lower them and a policy having a bad minute gets sent home; raise them and a
compromised one stays airborne longer. On a healthy policy neither counter ever
leaves zero, which is what makes them safe to have.

**Rule to preserve:** the guardian must stay deterministic and policy-independent.
It reads the command and the belief — never ground truth, never the network model,
never the policy's internals — and it must never gain the ability to author new
work beyond the five fallbacks. `test_guardian.py` enforces both.

**Methodological note.** Both findings above came from running a documented
command, not from writing a new test — `--live --repeat` was in the docs and had
never been executed. Two of the three real bugs in this phase were found that
way. Every command in this file is now run as part of the suite.

**What this does *not* do.** It is an envelope check, not a collision-avoidance
system: separation is checked against *believed* teammate positions, which under
degraded comms may be stale. It does not model vehicle dynamics, wind, or
airspace deconfliction with anything outside the team. It bounds what may be
*commanded*; it does not guarantee what the vehicle actually does.


---

## Appendix A — Command reference

Every runnable entry point, in phase order. All work with no simulator unless
the `--airsim` column says otherwise.

| Phase | Command | What it shows | AirSim? |
|---|---|---|---|
| all | `python scripts/run_all_tests.py` | 186 tests + 11 demos, one summary | no |
| 1 | `python scripts/run_single_mission.py --planner rule --adapter mock` | English → validated plan → flight | `--adapter airsim` |
| 2 | `python tests/test_behavior_preservation.py` | refactor changed structure, not behaviour | no |
| 3 | `python scripts/phase3_demo.py` | 4 drones run skills concurrently | `--adapter airsim` |
| 3 | `python scripts/phase3_showcase.py` | all 11 skills | `--adapter airsim` |
| 4 | `python scripts/run_canonical_mission.py` | scored mission, 8 criteria | `--airsim` |
| 4 | `python scripts/plot_mission_layout.py --paths` | regenerates the scenario figure | no |
| 5 | `python scripts/run_persistent_agent.py` | closed-loop agent, no preflight plan | `--airsim` |
| 5 | `python scripts/run_persistent_agent.py --battery 8` | low-battery safe abort | `--airsim` |
| 6 | `python scripts/run_persistent_agent.py --log` | what the agent knew / didn't | `--airsim` |
| 7 | `python scripts/run_team_mission.py --messages` | 4 agents, per-message log | `--airsim` |
| 8 | `python scripts/run_allocation_mission.py --bids` | self-organising division of work | `--airsim` |
| 9 | `python scripts/run_failure_recovery.py --health` | recovery from a lost drone | `--airsim` |
| 10 | `python scripts/run_comms_study.py --estimates` | four comms conditions | no |
| 11 | `python scripts/run_guardian_demo.py --live` | unsafe commands blocked, mission survives | `--live` runs on mock |

Test suites individually:

```bash
python tests/test_skills.py                 # 12   Phase 3
python tests/test_behavior_preservation.py  #  4   Phase 1-2
python tests/test_mission.py                #  6   Phase 4
python tests/test_persistent_agent.py       #  5   Phase 5
python tests/test_belief_state.py           # 11   Phase 6
python tests/test_messaging.py              # 14   Phase 7
python tests/test_allocation.py             # 21   Phase 8
python tests/test_roles_recovery.py         # 22   Phase 9
python tests/test_network.py                # 30   Phase 10
python tests/test_guardian.py               # 45   Phase 11
python tests/test_airsim_path.py            # 16   the --airsim path, faked
```

---

## Appendix B — Parameters worth tuning, and where they live

| Parameter | Default | File | What it does |
|---|---|---|---|
| `ALTITUDE` | −8.0 m | `control/navigation.py` | cruise height (NED: negative is up) |
| `FLY_TO_SPEED` | 4.0 m/s | `control/navigation.py` | point-to-point speed |
| landing profile | 5.0 → 1.5 m/s | `control/navigation.py` | fast descent, settle, slow final approach |
| `lane_spacing_m` | 8.0 m | `control/skills.py` | sweep density; wider means lower coverage |
| `required_coverage` | 0.95 | scenario YAML | coverage needed to pass |
| `deadline_s` | 900 | scenario YAML | mission time limit |
| `battery_s` | 900 | scenario YAML | per-vehicle budget |
| `random_seed` | 17 | scenario YAML | scenario-level seed |
| `low_battery_frac` | 0.30 | `PersistentAgent(...)` | when to stop extending the mission |
| `critical_battery_frac` | 0.12 | `PersistentAgent(...)` | when to land immediately |
| `MAX_IDLE_ROUNDS` | 3 | `agents/persistent_agent.py` | idle waits before flying home |
| `BidWeights` | 1.0/1.5/2.0/0.5/5.0 | `coordination/bidding.py` | distance / battery / workload / comms / role |
| `DEFAULT_LEASE_S` | 120 | `coordination/task_allocator.py` | **must exceed the longest skill** |
| `DEFAULT_BID_WINDOW_S` | 5 | `coordination/task_allocator.py` | how long to collect rival bids |
| `SUSPECT_AFTER_MISSED` | 2.0 | `coordination/roles.py` | heartbeats missed before "suspected" |
| `FAILED_AFTER_MISSED` | 8.0 | `coordination/roles.py` | heartbeats missed before "failed" |
| `TTL_BY_TYPE` | 90–600 s | `coordination/comms_conditions.py` | message lifetimes by type |
| condition profiles | see table | `coordination/comms_conditions.py` | the four comms conditions |
| `max_altitude` / `min_altitude` | −3.0 / −60.0 m | `agents/safety_guardian.py` | guardian altitude floor and ceiling |
| `max_speed_mps` | 12.0 | `agents/safety_guardian.py` | hard speed bound; above it is narrowed |
| `min_battery_reserve_frac` | 0.10 | `agents/safety_guardian.py` | never start new work below this |
| `min_separation_m` | 3.0 (scenario) | `agents/safety_guardian.py` | separation from believed teammate positions |
| `max_waypoint_range_m` | 300.0 | `agents/safety_guardian.py` | sanity bound on coordinates |
| geofence `margin_m` | 40.0 m | `SafetyLimits.from_scenario()` | margin around the sectors and base |
| `MAX_CONSECUTIVE_REJECTIONS` | 3 | `agents/safety_guardian.py` | rejections before the guardian flies home itself |
| `MAX_CONSECUTIVE_INTERVENTIONS` | 5 | `agents/safety_guardian.py` | **the non-evadable counter**; resets only on a clean approval |

**The single most important relationship in the system:**

```
message TTL  >  task lease  >  longest skill duration (~70 s sweep)
```

Break it in either direction and the symptoms are confusing rather than obvious:
too short a lease and healthy drones lose work they are flying; too short a TTL
and normal traffic looks like packet loss.

---

## Appendix C — Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `No module named airsim` / `numpy` | pip installed into `base`, not `carlaAir` | `conda activate carlaAir`, check `python -c "import sys; print(sys.executable)"` contains `envs\carlaAir` |
| `UnicodeDecodeError: 0xff` reading `.env` | PowerShell `echo >` wrote UTF-16 | rewrite with `Set-Content -Encoding ascii` |
| `Vehicle API for Drone1 not available` | vehicles not in `settings.json` | regenerate settings, restart CARLA-Air; scripts also call `spawn_missing_drones()` |
| conda refuses to install | Terms of Service not accepted | `conda tos accept` |
| conda won't activate in PowerShell | execution policy | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`, then `conda init powershell` |
| Gemini returns 404 | model name deprecated | use `gemini-flash-latest` |
| LLM drops steps from a multi-part command | unconstrained output | keep `format=PLAN_SCHEMA` in the Ollama call / `response_mime_type="application/json"` for Gemini |
| Drones swap speeds, stall, interfere | shared AirSim RPC client | one `MultirotorClient` per vehicle (already in `_client_for`) |
| Drone sinks through the ground on landing | ground level not recorded | ensure `takeoff()` ran first — it records `ground_z` |
| Only one drone moves at a time in AirSim | sequential runner | `--airsim` selects the threaded runner; confirm you passed it |
| Battery never depletes in AirSim | adapter clock missing | `AirSimVehicleAdapter.now()` must exist |
| Drones lose sectors mid-sweep | lease shorter than the skill | raise `--lease` above ~70 s |
| Team never notices a dead drone | heartbeat interval too large | lower `--heartbeat` |
| Messages look lost under perfect comms | TTL shorter than a skill | raise the TTL in `TTL_BY_TYPE` |
| Everything times out in AirSim | sim still loading, or paused | wait for Town10HD to finish loading |
| Guardian rejects legitimate commands | envelope too tight for the scenario | check `SafetyLimits.from_scenario()` margin; a real rejection names the failed check |
| Drone returns home mid-mission for no obvious reason | escalation fired | the log line starts `escalated after N...`; the policy proposed 5 unsafe commands in a row |
| `intervention_rate` above 0 on a healthy policy | the policy is proposing something unflyable | read `guardian_log.format_text()` — it names the check and the exact command |

When an AirSim run wedges, restarting CARLA-Air is almost always faster than
debugging the vehicle state.

---

## Appendix D — Where things live

```
agentic_uav/
  core/          data types, enums, geometry, mission models
  simulator/     airsim_adapter.py     real simulator
                 mock_adapter.py       deterministic kinematics, no sim
                 fake_airsim.py        fake AirSim API, for testing the --airsim path
                 ground_truth.py       GroundTruth + SensorModel (Phase 6)
                 target_model.py       geometric detection, no neural network
                 scenario_manager.py   YAML loader, settings.json, vehicle spawning
  control/       skills.py             typed commands + contracts
                 skill_executor.py     executes skills, enforces contracts
                 navigation.py         flight constants
  agents/        persistent_agent.py   the lifecycle loop
                 belief_state.py       + belief_schema.py
                 search_policy.py      deterministic policy
                 safety_guardian.py    deterministic safety layer (Phase 11)
                 unsafe_injection.py   the 13-case attack catalogue
                 comms_estimator.py    agent-side link estimate (Phase 10.5)
  coordination/  protocols.py          message types + envelope
                 message_bus.py        bus + AgentLink
                 tasks.py              MissionTask, TaskBoard
                 bidding.py            deterministic bid function
                 task_allocator.py     contract-net protocol
                 roles.py              roles + health states
                 role_manager.py       role policy
                 network_model.py      seeded degradation model
                 comms_conditions.py   the four conditions + TTLs
  planners/      gemini / llama / mistral / rule
  experiments/   mission_runner.py     scripted baseline
                 team_runner.py        multi-agent runners
                 metrics.py            mission scoring
                 decision_log.py       per-decision belief log
                 guardian_log.py       guardian audit log + intervention rate
configs/missions/search_relay_001.yaml  the canonical scenario
scripts/         one runnable demo per phase
tests/           186 tests, no simulator required
docs/            Phase_Documentation.md (this file)
                 TESTING.md       verify each phase, and break it on purpose
                 SIM_TESTING.md   flying it in CARLA-Air
                 ARCHITECTURE.md  module-by-module design
```

---

## Appendix E — Conventions to preserve

Five rules the tests enforce. Breaking one is usually a design mistake rather
than a failing test.

1. **Agents never touch ground truth.** Everything reaches belief through
   `SensorModel` or a delivered message. Enforced in `test_belief_state.py`.
2. **Agents never touch the message bus or the network model.** They hold an
   `AgentLink` and a `CommsEstimator`. Enforced in `test_messaging.py` and
   `test_network.py`.
3. **Mock runs are deterministic.** Same input, same output, every time. If you
   add randomness, seed it. Enforced in several suites.
4. **The guardian is deterministic and policy-independent.** No model, no
   randomness, no access to ground truth or the network model, and no authority
   to author work beyond the five fallbacks. Enforced in `test_guardian.py`.
5. **Behaviour is preserved across refactors.** `test_behavior_preservation.py`
   pins the exact action sequence for a set of missions and has passed since
   Phase 2.

Before pushing: `python scripts/run_all_tests.py` should print **ALL GREEN**.
