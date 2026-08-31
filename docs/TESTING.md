# Testing plan: Phases 3–7

How to verify every phase, what each result should look like, and how to
deliberately break things to confirm the checks are real.

**Two tiers.** Tier 1 needs nothing but Python — no simulator, GPU, API key or
network. Tier 2 flies the same code in CARLA-Air. Run Tier 1 constantly; run
Tier 2 when you want to see it fly or record a demo.

---

## 0. The 30-second check

```bash
cd AgenticDroneSimRepo
python scripts/run_all_tests.py
```

Expected: **ALL GREEN — 52 tests passed, 6 demos completed.**

```
TEST SUITES
  [PASS] P3    Skills + contracts           12 passed
  [PASS] P1-2  Behavior preservation         4 passed
  [PASS] P4    Mission scoring               6 passed
  [PASS] P5    Persistent agent loop         5 passed
  [PASS] P6    Belief state + truth split   11 passed
  [PASS] P7    Message protocol             14 passed
```

If that's green, everything below is already passing. The rest of this document
is for checking *why* it passes, which is what matters when explaining the work
or handing it to someone new.

First time on a machine:

```bash
pip install -r requirements.txt
```

---

## Phase 3 — Skills and contracts

**Claim:** the agent's interface is mission-level skills, each with a formal
contract and a structured result.

### Step 1 — unit tests

```bash
python tests/test_skills.py
```

Expect `12 passed, 0 failed`. These cover reaching a waypoint within tolerance,
timing out on an unreachable one, following a waypoint list, holding, landing,
and four drones running concurrently without interfering.

### Step 2 — see the skills run

```bash
python scripts/phase3_demo.py       # 4 drones: take off, waypoints, hold, return, land
python scripts/phase3_showcase.py   # all 11 skills in sequence
```

Expect every skill to report `SUCCESS` and the demo to exit 0.

### Step 3 — prove the contract is enforced

Skills don't just report success blindly — they check the success condition. Try
it in a Python shell:

```python
from agentic_uav.control import skills as sk
from agentic_uav.control.skill_executor import SkillExecutor
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.core.models import Position3D

ex = SkillExecutor(MockVehicleAdapter(0.0))
# a waypoint 500m away with a 2-second timeout cannot be reached
r = ex.execute("Drone1", sk.GoToWaypointCommand(
    waypoint=Position3D(500, 500, -8), timeout_s=2.0))
print(r.status, r.error_code)
```

Expect `SkillStatus.TIMEOUT timeout` — **not** SUCCESS. That's the contract
doing its job.

---

## Phase 4 — Canonical mission and scoring

**Claim:** one fixed scenario, scored against explicit success criteria, with a
scripted non-agentic controller as the baseline.

### Step 1 — run the mission

```bash
python scripts/run_canonical_mission.py
```

Expect `MISSION SUCCESS`, 100% coverage, both targets found and reported, and
all 8 criteria PASS.

### Step 2 — see the scenario

```bash
python scripts/plot_mission_layout.py --paths
```

Writes `docs/images/mission_layout.png` — four sectors, two targets, the no-fly
zone, and the flown sweep. Confirms the config and the flight agree.

### Step 3 — unit tests, including the negative ones

```bash
python tests/test_mission.py
```

Expect `6 passed`. Three of these deliberately feed the evaluator *bad* runs —
a path through the no-fly zone, a run that blows the battery and deadline, two
drones on top of each other — and assert it catches each. A scorer that only
ever says PASS is worthless; these prove it can say FAIL.

### Step 4 — break it yourself

Edit `configs/missions/search_relay_001.yaml` and move the no-fly zone on top of
a sector, e.g.:

```yaml
restricted_zones:
  - id: R1
    polygon: [[10, 10], [50, 10], [50, 50], [10, 50]]   # sits on S1
```

Re-run the mission. Expect `no_restricted_entry` to FAIL and the mission to fail
overall. **Revert the file afterwards** (`git checkout configs/`).

---

## Phase 5 — Persistent closed-loop agent

**Claim:** the agent gets a task, not a plan, and decides one skill at a time.

### Step 1 — normal run

```bash
python scripts/run_persistent_agent.py
```

Expect `TASK COMPLETE` and a decision trace like:

```
task_assigned->take_off
skill_succeeded->go_to_sector
skill_succeeded->search_sector
skill_succeeded/target_detected->report
report_sent->return_home
skill_succeeded->land
skill_succeeded->done
```

Read that left to right: each line is *event → decision*. There is no preflight
list anywhere — every objective was chosen in response to something that
happened. That trace is the whole point of the phase.

### Step 2 — low battery reaction

```bash
python scripts/run_persistent_agent.py --battery 8
```

Expect `TASK ABORTED SAFELY` — it did **not** finish the search, but it landed
safely. Give it too little battery and the right answer is to stop, not to press
on.

### Step 3 — a different sector

```bash
python scripts/run_persistent_agent.py --sector S3
```

Expect `TASK COMPLETE` and `detections: ['T2']` — a different target, because
it searched a different part of the world.

### Step 4 — tests

```bash
python tests/test_persistent_agent.py
```

Expect `5 passed`, including navigation-failure recovery (a fake adapter times
out the first move; the agent must retry and still finish).

---

## Phase 6 — Belief state, truth separation, staleness

**Claim:** structured belief, no hidden global information, and information
that ages.

### Step 1 — the audit trail (the exit criterion)

```bash
python scripts/run_persistent_agent.py --log
```

Each decision prints what the agent **knew** and what it **did not know**:

```
[step 3 t=6.2s] Drone1 triggers=skill_succeeded
    KNEW    : pos=[10, 10, -8.0] battery=99% searched=[] targets=[]
    DID NOT KNOW: sector S1 not searched by me; ...; no targets observed yet
    DECIDED : search_sector via search_region -> success
```

Check that the gaps *shrink* as the run goes on — by the last step it should no
longer say "no targets observed yet."

### Step 2 — machine-readable version

```bash
python scripts/run_persistent_agent.py --log --log-json run.json
```

`run.json` holds the full belief snapshot at every decision. This is what you'd
use to analyse a run later.

### Step 3 — the leak tests

```bash
python tests/test_belief_state.py
```

Expect `11 passed`. Two matter most:

- **structural** — walks the belief's object graph and fails if any
  `GroundTruth`, `MissionScenario` or `Target` object is reachable from it;
- **behavioural** — the agent searches S1 and must find T1 but must *never*
  learn T2 exists, because it never flew near it.

### Step 4 — prove the sensor is the only channel

```python
from agentic_uav.agents.persistent_agent import PersistentAgent
from agentic_uav.agents.objectives import SearchTask
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

sc = load_scenario("configs/missions/search_relay_001.yaml")
s1 = sc.sectors[0]
a = PersistentAgent("Drone1", MockVehicleAdapter(0.0), home=sc.vehicles[0].start,
                    cruise_altitude=s1.altitude)          # note: no sensor=
r = a.run(SearchTask("search_S1", s1, sc.base.position))
print(r.completed, r.detections)
```

Expect `True []` — it completes the task but perceives **nothing**. No sensor,
no knowledge. If this ever prints targets, information is leaking in somewhere
other than the sensor.

---

## Phase 7 — Message protocol

**Claim:** agents coordinate only through delivered messages, with no back channel.

### Step 1 — four agents flying together

```bash
python scripts/run_team_mission.py
```

Expect all four `COMPLETE`, and:

```
dropped (link)   : 0   <- 0 under perfect comms
dropped (expired): 0
```

Both must be 0 — that's what makes this "perfect communication." If link drops
are nonzero, the bus is losing mail it shouldn't.

### Step 2 — watch the traffic

```bash
python scripts/run_team_mission.py --messages
```

Every message with sender, recipient, send time, delivery time, and `*` if it
influenced a decision.

### Step 3 — see the beliefs it produced

```bash
python scripts/run_team_mission.py --beliefs
```

Each agent lists the teammates it knows about, with age and confidence. Note
that Drone2 searched S2 (which has no target) yet still knows about T1 and T2 —
it learned them from `TARGET_FOUND` messages, and recorded them as second-hand.

### Step 4 — tests, especially the blackout

```bash
python tests/test_messaging.py
```

Expect `14 passed`. The one to point at is
`test_team_belief_updates_only_when_messages_are_delivered`: it reruns the same
four-agent mission with a bus that delivers **nothing**, and asserts every
agent's team belief stays completely empty. If agents still learned about each
other, there'd be a hidden channel — that test is the proof there isn't one.

### Step 5 — break communication yourself

```python
from agentic_uav.experiments.team_runner import build_team, run_team
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario
import random

sc = load_scenario("configs/missions/search_relay_001.yaml")
agents, tasks, bus, _ = build_team(sc, lambda v: MockVehicleAdapter(0.0),
                                   latency_s=5.0, loss_rate=0.5,
                                   rng=random.Random(17))
r = run_team(agents, tasks, bus)
print(bus.stats())
print("all completed:", r.all_completed)
```

Expect roughly half the messages dropped with `dropped_link` well above zero —
and the agents should still complete their sectors, because each one's own
search does not depend on hearing from anyone. That's the baseline the
degradation phase will build on.

---

## Tier 2 — Flying it in CARLA-Air

Same code, real simulator. See **[docs/SIM_TESTING.md](SIM_TESTING.md)** for the
full ordered walkthrough — environment checks, what to watch for in each phase,
what counts as a pass, and a troubleshooting table.

Short version:

```bash
python scripts/phase3_showcase.py --adapter airsim        # Phase 3
python scripts/run_canonical_mission.py --airsim          # Phase 4
python scripts/run_persistent_agent.py --airsim --battery 45  # Phase 5
python scripts/run_persistent_agent.py --airsim --log     # Phase 6
python scripts/run_team_mission.py --airsim --messages    # Phase 7
```

If a run fails here but passes on the mock, the problem is the simulator or the
adapter — not the agent logic.

---

## Quick reference

| Phase | Command | Expected |
|---|---|---|
| all | `python scripts/run_all_tests.py` | ALL GREEN, 52 tests |
| 3 | `python scripts/phase3_showcase.py` | all 11 skills SUCCESS |
| 4 | `python scripts/run_canonical_mission.py` | MISSION SUCCESS, 8/8 criteria |
| 5 | `python scripts/run_persistent_agent.py` | TASK COMPLETE, event→objective trace |
| 5 | `python scripts/run_persistent_agent.py --battery 8` | TASK ABORTED SAFELY |
| 6 | `python scripts/run_persistent_agent.py --log` | KNEW / DID NOT KNOW per decision |
| 7 | `python scripts/run_team_mission.py` | 4× COMPLETE, 0 link drops |
