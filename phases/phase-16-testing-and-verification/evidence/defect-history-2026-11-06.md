# Where the project's defects were found — Phases 3 to 15

Phase 16's exit asks whether "most coordination and communication defects can be discovered without launching
CARLA-Air". This is the project's own answer from its history: every **code defect** recorded in the phase
reports' defect tables (vault `AUV-P3.4` … `AUV-P15.4`, and the live-flight notes `AUV-P8.7`, `AUV-P9.7`,
`AUV-P9.8`), classed by **what found it**.

* **Simulator-free (N)**: a test, a mutation, a mock flight or check, a mock run in real time, review of code or
  of a mock record, a benchmark on Vega. No CarlaAir.
* **Live (L)**: a live CarlaAir flight, or a record that only a live flight produced.

**Counted:** defects in the code, and gaps that let one through. **Not counted:** slips in documents, commit
messages or a test's own expectation; tooling (the mutation harness's bytecode); design facts recorded as
"by design". **Coordination and communication (C)** marks defects in messaging, the bus and network, allocation,
leases, health, roles, recovery and the keep-out — the code the exit is about.

The classification is a judgment, made row by row below, so it can be disputed row by row.

| Phase | Defect | Found by | Where | C |
|---|---|---|---|---|
| 3 | The first exit plan was unsafe on CarlaAir's timing (drones fanned forward, 3.48 m apart) | the mock's separation report | N | |
| 3 | The live contract waited a fixed 4 s for a reset drone to land | Phase 1's live record (the drone 18 m wrong) | **L** | |
| 3 | A completed mock move ended at 49.99999999999988, not 50 | a mock test | N | |
| 4 | The scripted plan never searched the corners at lane ends | the live variant's mock gate, one seed in 20 | N | |
| 4 | The poller would have read every landed drone as flying (CarlaAir reports 1.17 m landed) | Phase 3's live numbers | **L** | |
| 4 | The first live record began with drones still falling from placement | the first live flight | **L** | |
| 4 | The spectator camera would have counted as a collision | reading `classify_contact` | N | |
| 5 | A lost abort between `start` and `run` | reasoning on the simulated clock, then a test | N | |
| 5 | The way home could cross a restricted zone | writing the give-up branches | N | |
| 5 | Search progress estimated by time, not position | review of the estimate | N | |
| 5 | A search started that could never finish | choosing the mock troubles | N | |
| 5 | Landing under the battery reserve at half speed | calibrating a mock trouble | N | |
| 6 | A path from the agent to the simulator through its executor | a walk of a flying (mock) agent's attributes | N | |
| 6 | The radio picture ended too early (float end of trajectory) | the knowledge logger's first (mock) run | N | |
| 6 | A drone's own velocity read as a teammate's position | the logger's first run | N | |
| 6 | Three link qualities held with no source | the completeness check | N | |
| 6 | The live allowance (0.5 m) exceeded by a correct belief | a mock-in-real-time flight | N | |
| 6 | The poll rate kept, misnamed in the live printout | reading the live flight's output | **L** | |
| 7 | The simulated clock's same-instant race | repeating the live variant's pair on the mock | N | C |
| 7 | A belief judged at the wrong instant on the live path | the real-time dry run of the live path (mock) | N | C |
| 7 | A send lost between a reader's two steps | a surviving mutation, then a probe | N | C |
| 7 | A heard teammate's position called a leak | Phase 6's knowledge log on the talking four (mock) | N | C |
| 7 | Thread order deciding whether a message arrived | team beliefs differing run to run (mock) | N | C |
| 7 | A bare heartbeat would wipe a teammate's task | designing step 4 | N | C |
| 8 | Simultaneous claims settled one by one, naming the wrong winner | the contested test | N | C |
| 8 | A task completed by a teammate left its holder crashing | the first (mock) team flights | N | C |
| 8 | Stale bids could leave a free drone waiting for ever | the first team flights | N | C |
| 8 | One instant's messages in thread order: different book logs | the determinism test | N | C |
| 8 | `super().__init__`, refused by the agents' boundary | the boundary check | N | C |
| 9 | Landed drones climbed the health ladder: a false alarm at every landing | step 3's mock flights | N | C |
| 9 | Drones listed in thread order | step 3's mock flights | N | C |
| 9 | A belief's millisecond past the flight's end failed "known exactly" | the exit (mock) | N | C |
| 9 | A drone over its stopped teammate read as a leak | the mock twin | N | C |
| 9 | The roles check allowed a relay to begin only on unreachability | the dry run (mock) | N | C |
| 9 | **A survivor sent into a stopped teammate's column: collision** (no keep-out) | **the live flight `live1`** | **L** | C |
| 9 | The keep-out's "already inside, fly out" too generous | the first (mock) trial of the fix | N | C |
| 10 | Two identical flights listed deliveries in different orders | step 1's mock check | N | C |
| 10 | A teammate at the same x, y but another height read as a leak | step 1 | N | C |
| 10 | A partition's edge judged three ways | step 1 | N | C |
| 10 | Float rounding deciding expiry at a lifetime's end | step 2 | N | C |
| 10 | The latency check failing a correct model | step 4 (statistical check) | N | C |
| 10 | The rate check reading one recipient of a broadcast | step 4 | N | C |
| 11 | An INVALID decision listing no problem would have been approved | a mutation | N | |
| 11 | A point with an extra field accepted by the channel | mutation | N | |
| 11 | Seven guardian behaviours untested | mutation | N | |
| 11 | The exit not noticing a traced decision other than the injected one | mutation | N | |
| 11 | A finding counted knock-ons at the injection's instant | reading seed 17's (mock) log | N | |
| 12 | The menu offered restarts while already searching | bench1 (Vega, no simulator) | N | |
| 12 | Decisions not stamped with when their belief was read | thinking through real-time use | N | |
| 13 | `MISSION_UPDATE`'s lifetime given by its sender, not the table | `test_lifetimes`, `test_messages` | N | C |
| 13 | The harness gave B a task (flight code calling `assign`) | `test_recovery_exit` (AST) | N | C |
| 13 | A's controller tested only through two flights | mutation | N | C |
| 13 | Best-first hidden by a symmetric layout | mutation | N | C |
| 13 | No configuration turning the keep-out off | mutation | N | C |
| 14 | The event helper's parameter clashing with a field | the smoke run | N | |
| 14 | Agent flights reading the judge's report from the wrong object | the smoke run | N | |
| 14 | Skill ends taken only from what decisions heard | 43 started, 22 ended (mock) | N | |
| 14 | Events at one instant in thread order | the deterministic check | N | |
| 14 | D-fallback logged as model calls | review | N | |
| 15 | Message sizes logged as a method's name | the first scoring (mock batch) | N | |

## The tally

| | Simulator-free (N) | Live (L) | Simulator-free share |
|---|---|---|---|
| **Every code defect, Phases 3–15** | **55** | **5** | **91.7 %** |
| **Coordination and communication (C)** | **28** | **1** | **96.6 %** |

The five found live were about CarlaAir itself — its timing, its landed heights, drones still falling after
placement, a live printout — and one coordination defect: the survivor sent beneath a stopped teammate, whose
collision also involved CarlaAir's physics (a 5 m jump in one poll). The keep-out that fixed it was then found
wanting, and fixed, on the mock.

## Not in the table

The live findings that are not defects: Phase 1–2's M10 Drone3 jump (CarlaAir), Phase 9's second live flight
(coverage 81.9 %: safety against coverage in a small sector), and the operations failures (dropped connections
during Vega runs).
