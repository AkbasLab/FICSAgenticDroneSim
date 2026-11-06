# Phase 13 — Implement the experimental comparison architectures

**Stage:** 6 · Apparatus · **Vault note:** `AUV-13 — Comparison Architectures`
**Started:** 2026-11-05 · **Completed:** 2026-11-06 (on the mock)

> A paper cannot compare only the old system against the new one. Phase 13
> builds every arm the study compares, A, B, C, D and E, and the ablations,
> as **configurations of one harness**: the same world, skills, sensing, bus,
> network, guardian, keep-out and judge, differing only in how coordination
> decisions are made and which mechanisms are on. Thirteen configuration files,
> one entry point, and 20 of 20 seeds on which every arm is what it claims to be.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [x] **A** Centralized fleet controller — the nominal-efficiency baseline (`configs/architectures/A.toml`)
- [x] **B** Independent persistent agents — isolates the value of communication (`B.toml`)
- [x] **C** Deterministic decentralized agents — **isolates architecture from LLM reasoning** (`C.toml`: Phase 9's team)
- [x] **D** Agentic decentralized agents — the proposed system (`D.toml`: Phase 12's LLM policy)
- [x] **E** *(optional)* the non-agentic baseline, as history (`E.toml`: Phase 4's preflight plan; see Decisions)
- [x] The six ablations as switches — no persistent memory (`D-no-memory`) · no task leases (`D-no-leases`) · no dynamic roles (`D-no-roles`) · perfect communication (`D-perfect-comms`) · deterministic with the same communication-health inputs (`C-link-inputs`) · LLM replaced by the fallback policy (`D-fallback`); and, added, no guardian (`C-no-guardian`, `D-no-guardian`)
- [x] ✅ **Exit:** the architecture can be **selected through configuration** rather than maintaining four unrelated programs

"Run the six ablations" is met as **built, selectable and shown to switch
their mechanism off** on every seed. What each ablation *costs or buys* is
an experiment, under the live model and degraded links: Phase 17's (see Open
questions).

## Exit criterion

> The architecture can be **selected through configuration** rather than maintaining four unrelated programs.

**Met:** yes, on the mock, 2026-11-06 — 20 of 20 seeds passed all five checks: every configuration in
`configs/architectures/` flown by the one entry point, with no stop and with Drone1 stopped at 60 s; each arm
what it claims (C is Phase 9's flight, D by the echo and D with its model replaced by the fallback are C's, D
replayed is Phase 12's 70B flight, B starts from C's division and sends no task message, A flies only the base's
awards, E meets the mission); every ablation's mechanism off; every limit kept; seeds 1–5 flown twice, the same.
· **Evidence:** [`evidence/exit-criterion-2026-11-06.md`](evidence/exit-criterion-2026-11-06.md).

## Deliverables

| Artifact | Location | State |
|---|---|---|
| The configurations and the one entry point | `configs/architectures/*.toml` (13), `agentic_uav/experiments/architecture.py` | **Done**; read strictly, impossible combinations refused |
| A: the base controller and its follower | `agentic_uav/coordination/central.py`, `agentic_uav/agents/follower_policy.py` | **Done** |
| B: the independent agent and C's first division | `agentic_uav/agents/independent_policy.py` | **Done** |
| The switches in the shared code | `experiments/recovery.py` (`team=`, `leases=`, `roles=`, `link_inputs=`), `ContractNet(leases=)`, `RecoveryPolicy(roles=)`, `LLMPolicy(memory=)` | **Done**; every earlier run of record reproduces |
| The exit | `agentic_uav/experiments/architecture_exit.py`, `scripts/architecture_exit.py` (`--jobs`), `results/`, `evidence/` | **Done**; exit met on the mock |
| Tests | `tests/test_architecture.py` (18), `tests/test_architecture_exit.py` (7), `tests/test_central.py` (5) | **Done**; 30 mutations accounted for |
| Optional live flight | -- | **Not flown**, by the approved plan |

## Plan

Approved 2026-11-05 ("Approve, build it all"), shown in full first: one harness, config and entry point, C and D;
B; A; the ablations as switches, each checked; the exit on the mock, 20 seeds; close. Seven recommendations, all
taken:

1. **One harness; the guardian and keep-out on for every arm** (switched off only by the no-guardian ablations).
2. **A's controller is a participant on the bus at the base**, so its messages suffer the same network as everyone's.
3. **B starts from C's own first division**, so B differs from C only by never coordinating after it.
4. **E is included, labelled historical.**
5. **A no-guardian ablation is added.**
6. **The exit runs on the mock**, seeds 1–20, with and without a stop; D by the echo, plus Phase 12's recorded 70B replies replayed.
7. **No live flight.**

## Record

### 2026-11-05/06 — steps 1–4: one harness, the arms, the switches

`experiments/architecture.py` reads a configuration — `[architecture]` name, description, `team`
(`decentralized`, `independent`, `central`, `scripted`), `decider` (`rules`, `llm`, `llm-fallback`) and
`[mechanisms]` (`memory`, `leases`, `roles`, `guardian`, `keep_out`, `link_inputs`, `perfect_comms`) — strictly:
an unknown key, a non-boolean switch or an impossible combination (a model deciding for A, memory without a
model, roles outside the decentralized team) is refused. `fly_architecture` flies any of them through
`recovery.fly_recovery_on_mock`, the harness every arm shares; only E, which has no agents, goes through Phase 4's
`fly_on_mock`.

* **C** is Phase 9's team, unchanged: the same flight as Phase 9's on every seed.
* **D** wraps each drone's recovery policy in Phase 12's `LLMPolicy`. By the echo (the rule's own choice) it flies
  C's flight exactly; with the model replaced by the fallback (`D-fallback`), too; replayed from Phase 12's recorded
  replies it flies Phase 12's flight, decision for decision.
* **B**: `initial_division` gives each task to its best free bidder, best bid first (a bid's value is a cost), from
  the pads with full batteries — C's own first round — and each drone flies its task alone with Phase 5's
  persistent agent. It talks (heartbeats, status), so the guardian and the keep-out still know where teammates
  are, but sends no task message: a stopped drone's sector stays unsearched.
* **A**: `CentralController` sits on the bus as `base`. It hears heartbeats and status updates, awards each open
  task to the best free drone it has heard from lately, re-sends an award each second until the drone's status
  shows it, reopens a task given back on the way home, reassigns a silent holder's task after the recovery
  ladder's 10 s (a lease, for A), and says "complete" when every task is done. `FollowerPolicy` flies what the
  base awards, reports each task done, and after 10 s without the base finishes its task and goes home (the
  disconnected fallback).

Three guardrails failed on the first full suite, each honoured rather than loosened:

1. *Every type with a schema has a lifetime in the table*: `MISSION_UPDATE` was given its 10 s by its sender.
   Now it is in the table ("current intent", 10 s). A re-run of Phase 10's network exit therefore lists one more
   lifetime in its header, for a type Phase 10 never sent; no flight changes.
2. *The types in use*: `test_messages` names `MISSION_UPDATE` as Phase 13's, as Phase 9 added `ROLE_CHANGE`.
3. *The flight code gives no task* (Phase 9's "no central controller", by AST): the harness called `assign` for B.
   B's task is now its own policy's, taken up when told the team mission; the harness tells every team the
   mission and never a task. B flies the same flight before and after (the same commands; each drone the same
   messages at the same times).

**Every run of record reproduced, identical**, on the final code: Phases 5–8 (five runs), Phase 9's recovery exit
and keep-out check, Phase 10's network check, and Phase 11's guardian exit (NaN fields compared as equal). The
first attempt ran while shared code was still being edited, so it was stopped and run again from the start.

**Mutations: 30, all accounted for.** 18 caught at first; the gaps were A's controller (reassignment off, the
re-send stopping once confirmed, a drone not heard lately, a task given back, a drone going home), B (its own task
in its reports; best bid first — the canonical layout is symmetric enough that worst-first gives the same
division, so it is tested on a lopsided start, by the guarantee best-first gives), roles off (no reserve), the
keep-out switch (no configuration turns it off: the entry point's wiring of every switch is tested), and perfect
comms. Each has a test now (`tests/test_central.py` and additions to `tests/test_architecture.py`). One was
equivalent: `LLMPolicy` guarded the memory twice; the redundant guard is removed and the remaining one is caught.

### 2026-11-06 — step 5: the exit, met on the mock

`scripts/architecture_exit.py --jobs 10 --block exit` at commit `f98fe25` (clean): every configuration, seeds 1–20,
with no stop and with Drone1 stopped at 60 s (E with no stop), D by the echo, and on seeds 1–5 D replayed from
Phase 12's 70B; seeds 1–5 flown twice; 510 configuration-flights and Phase 9's comparison flight each seed, in
314 s with seeds side by side (`--jobs` writes the same record as one at a time: checked on two seeds).
**20 of 20 seeds passed all five checks.**

**Each arm, side by side** (findings, not experiments; the same on every seed — on this scenario and a perfect
network the seed changes no flight):

| Arm | No stop | Drone1 stopped at 60 s |
|---|---|---|
| A, central controller | met, 192.1 s | **met, 308.2 s** (the base reassigned Drone1's sector) |
| B, independent | met, 188.0 s | **not met, 0/20** (Drone1's S3 never searched) |
| C, decentralized rules | met, 194.1 s | met, 309.1 s |
| D, by the echo | met, 194.1 s (C's flight) | met, 309.1 s (C's flight) |
| D, Phase 12's 70B replayed (seeds 1–5) | met, 193.0–199.1 s | met, 308.0–309.1 s |
| E, Phase 4's preflight plan | met, 192.1 s | -- (no agents to stop) |
| D-no-leases | met, 194.1 s | **not met, 0/20** (the silent holder's task never returns) |
| D-no-roles | met, **188.0 s** | met, **307.1 s** |
| D-no-memory, D-perfect-comms, D-fallback, D/C-no-guardian, C-link-inputs | C's / D's flights exactly | C's / D's flights exactly |

What this shows, and what it doesn't:

* **Coordination is what survives a loss.** Without it (B), or without the lease that frees a silent holder's task
  (D-no-leases), losing one drone loses the mission. A's controller and C's contract-net both recover it, A about a
  second sooner.
* **Roles cost time on a perfect network**: without them the team is 6 s faster, and 2 s with the stop. Their
  purpose (a relay, a reserve) is degraded links — Phase 17's to measure.
* **The other ablations change nothing here, as they must**: with the echo the model *is* the rule, so memory and
  the fallback cannot change a choice; the network is perfect, so perfect comms and link inputs are the same
  flight; and the guardian never intervenes on a clean flight (Phase 11). These flights prove the switches are
  wired and the mechanisms off, not what they are worth.

### 2026-11-06 — close

**Phase 13 is complete on the mock.** Every arm and ablation is a configuration of one harness, and the exit
criterion is met. **1,280 tests pass, 29 skipped**; the goldens unedited; every run of record from Phases 5–11
reproduced. No Vega was needed: D's model decisions came from the echo and from Phase 12's recorded replies.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-05 | **One harness for every arm; the guardian and keep-out on unless an ablation turns them off** | AUV-13: the arms share everything but how coordination decisions are made |
| 2026-11-05 | **A's controller is a participant on the bus at the base** | Its state reports and commands then suffer the network like everyone's (AUV-13: "state reports can be delayed or lost; commands can be delayed or lost") |
| 2026-11-05 | **B starts from C's own first division** | So B differs from C only by never coordinating afterwards |
| 2026-11-05 | **E is Phase 4's preflight plan, labelled historical** | The non-agentic baseline on this mission; Phase 1's open-loop planner flies different missions (M01–M10) and could not share the judge |
| 2026-11-05 | **A no-guardian ablation added** | Runtime assurance is a layer the paper must be able to remove like the others |
| 2026-11-05 | **The exit on the mock, D by the echo plus Phase 12's replay; no live flight** | Selection by configuration is a property of the code; the live model's effect is an experiment (Phase 17) |
| 2026-11-06 | **MISSION_UPDATE gets the table's lifetime; B's task is its policy's own** | The protocol's and Phase 9's guardrails, honoured rather than loosened |
| 2026-11-06 | **Exit seeds flown side by side (`--jobs`)** | The laptop's 12 cores sat at 14 %; each seed is independent, so the record is the same |

## Open questions

1. **What each ablation is worth** needs the live model and degraded links: Phase 17's pilots, on Vega (about one
   4 h job for D; see the vault's `AUV-HW4`).
2. **The seed changes nothing on a perfect network** for any arm here; variance between seeds comes from the
   network model and failures. Phase 17's conditions must supply it, or 20 seeds are one flight twenty times.
3. **A under degraded links** — delayed or lost state reports and awards — is built (the base is on the bus) but
   flown only on a perfect network; the follower's disconnected fallback is tested directly, not in flight.
4. **Model size, decision latency and runtime assurance** (vault AUV-12F) stays its own piece of work, kept apart
   from the phases at the user's request.

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
