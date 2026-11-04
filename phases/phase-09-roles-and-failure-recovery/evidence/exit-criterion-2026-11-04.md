# Phase 9 exit criterion — evidence, 2026-11-04

> During a four-drone mission, one agent can be **intentionally stopped**. The remaining agents detect the
> disruption, reassign its task, and continue **without a new human command**.

**Met on the mock.** 20 of 20 seeds passed all eight checks: each seed flown with no stop and with each of the four drones stopped in turn at 60 s, each stopped flight twice (180 flights). In every stopped flight every survivor detected the stop at its thresholds, the stopped drone's task came back and a survivor finished it, the mission was met, and nobody was told anything after the team mission. 14630 decisions known exactly. Generated from `../results/recovery-exit-20261104-115126-exit.jsonl`; nothing is transcribed.

## What ran

| | |
|---|---|
| Scenario | `configs/scenarios/search_relay_001.toml`: the canonical mission, four drones, four sectors |
| Agents | the recovery policy (`agents/recovery_policy.py`): Phase 8's team policy with a failure detector, roles and recovery; each told only the team mission |
| Network | every message delivered (range unlimited) -- a stopped drone's silence is the only silence |
| Manifests | `configs/allocation/default.toml` (bids, window, lease 10 s); `configs/recovery/default.toml`: suspected 3 s, unreachable 10 s, failed 30 s |
| A stop | from outside at 60 s: the agent stops deciding and talking, its skill is aborted, the drone holds; the judge is told, no agent is |
| Seeds | 1–20 |
| Code | commit `8e508b7` + the step-4 files (dirty: True); `agentic_uav` digest `d94baeaba3bf29ed` |
| Wall time | 467.84 s |

## The eight checks

| Check | What it requires |
|---|---|
| detected | every survivor's ladder for the stopped drone climbs suspected, unreachable, failed, in order, each at its threshold's silence and within a tick |
| no false alarm | no survivor's ladder moves for a drone that was not stopped -- in any flight, the one with no stop included |
| reassigned | the stopped drone's task returns one version on (its lease run out) and is completed by a survivor, in every survivor's book |
| continued | the mission met by the survivors, each ending its part itself |
| no new human command | every drone told the team mission and nothing else, ever |
| roles from interactions | every role change follows from the drone's own claim, completion or detector, and was announced |
| deterministic | each stopped flight flown twice gives the same records |
| known exactly | Phase 6's knowledge log passes every decision |

Each is shown able to fail in `tests/test_recovery_exit.py`, on a real seed's flights altered to break it.

## Every seed

| Seed | detected | no_false_alarm | reassigned | continued | no_new_command | roles_from_interactions | deterministic | known_exactly | Reassigned: stopped's task → taken by (claimed s) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 2 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 3 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 4 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 5 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 6 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 7 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 8 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 9 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 10 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 11 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 12 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 13 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 14 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 15 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 16 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 17 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 18 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 19 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |
| 20 | yes | yes | yes | yes | yes | yes | yes | yes | Drone1 S3 → Drone4 (119.6); Drone2 S4 → Drone4 (119.6); Drone3 S1 → Drone4 (119.6); Drone4 S2 → Drone3 (125.1) |

Completion, by flight (the same on every seed): no stop 194.1 s; Drone1 stopped 309.1 s; Drone2 stopped 292.2 s; Drone3 stopped 309.1 s; Drone4 stopped 294.1 s.

## Seed 17: Drone1 stopped at 60 s

### Detection: every survivor's ladder

| Survivor | Suspected | Unreachable | Failed |
|---|---|---|---|
| Drone2 | 63.5 s (3 s silent) | 70.5 s (10 s silent) | 90.5 s (30 s silent) |
| Drone3 | 63.5 s (3 s silent) | 70.5 s (10 s silent) | 90.5 s (30 s silent) |
| Drone4 | 63.5 s (3 s silent) | 70.5 s (10 s silent) | 90.5 s (30 s silent) |

Drone1's last message was sent at 60 s. Nobody else's ladder moved.

### Reassignment

* Drone2's book, 69 s: search S3 -- Drone1's lease ran out at 69.000 -> open v2
* Drone3's book, 69 s: search S3 -- Drone1's lease ran out at 69.000 -> open v2
* Drone4's book, 69 s: search S3 -- Drone1's lease ran out at 69.000 -> open v2

**Drone4** took it. Its own record:

| s | Role | Why |
|---|---|---|
| 1 | reserve → scout | holds search S2 |
| 118.5 | scout → reserve | holds no task: available for one returned |
| 119.6 | reserve → scout | holds search S3 |
| 252.7 | scout → reserve | holds no task: available for one returned |

| s | Claimed | Version | Bid |
|---|---|---|---|
| 1 | search S2 | 1 | 108.0 |
| 119.6 | search S3 | 2 | 131.7 |

Completed: search S2, search S3.

### Roles, as each drone announced them

| s | Drone | Role | Why |
|---|---|---|---|
| 1 | Drone1 | reserve → scout | holds search S3 |
| 1 | Drone2 | reserve → scout | holds search S4 |
| 1 | Drone3 | reserve → scout | holds search S1 |
| 1 | Drone4 | reserve → scout | holds search S2 |
| 118.5 | Drone4 | scout → reserve | holds no task: available for one returned |
| 119.6 | Drone4 | reserve → scout | holds search S3 |
| 124 | Drone3 | scout → reserve | holds no task: available for one returned |
| 136 | Drone2 | scout → reserve | holds no task: available for one returned |
| 252.7 | Drone4 | scout → reserve | holds no task: available for one returned |

## Across the seeds

| Stopped | Its task | Taken by (claimed at s), over all seeds |
|---|---|---|
| Drone1 | search S3 | Drone4 (119.6) |
| Drone2 | search S4 | Drone4 (119.6) |
| Drone3 | search S1 | Drone4 (119.6) |
| Drone4 | search S2 | Drone3 (125.1) |

## Beside the exit: reprioritization (9.3, step 6)

Drone1 stopped at 60 s with the deadline cut to 250 s, so its search S3 cannot be redone in time. As it should: abandoned in every survivor's book -- Drone2 at 69 s, Drone3 at 69 s, Drone4 at 69 s; nobody chased it; the team ended at 188 s, inside the deadline, with the partial result (S1 1.000, S2 0.999, S3 0.387, S4 1.000). The mission is not met -- the point: a team that cannot lower its ambition burns its time on what it cannot finish.

## Beside the exit: 9.4, controlled emergence

| Condition | Held | How the record shows it |
|---|---|---|
| a team-level objective | yes | every drone told only the team mission, in every flight |
| no central controller | yes | no task given to any drone, by anyone, after the start; the flight code calls only assign_team (tests/test_recovery_exit.py) |
| only local beliefs and delivered messages | yes | the boundary checks over agents/ and coordination/; every decision known exactly |
| allocation and roles from interactions | yes | every role change traced to the drone's own claim, completion or detector; every claim to its bids |
| deterministic constraints | yes | every executed decision passed the validation step |

AUV-19's proxies -- **reported, not claimed as a measure of emergence**:

* **Assignment distance from one drone per sector**: 4 of 4 drones fly other than the naive assignment (Drone1 search S1, Drone2 search S2, Drone3 search S3, Drone4 search S4); flown: Drone1 search S3, Drone2 search S4, Drone3 search S1, Drone4 search S2.
* **Allocation divergence across seeds**: 1 distinct division(s) over 20 seeds. These agents are deterministic and the bids depend on geometry, not targets: one division on every seed is expected, and is not emergence measured.

**Exit criterion: MET** on the mock.
