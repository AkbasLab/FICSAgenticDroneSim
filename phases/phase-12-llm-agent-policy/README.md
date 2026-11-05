# Phase 12 — Introduce the LLM as a persistent high-level agent policy

**Stage:** 5 · Intelligence · **Vault note:** `AUV-12 — The LLM as Agent Policy`
**Started:** 2026-11-05 · **Completed:** 2026-11-05 (as a capability; formal LLM experiments wait for Phases 13–17)

> Everything before this phase made it measurable. Phase 12 puts a model in
> each drone: it chooses the drone's mission-level actions, through structured
> tools on the rule team's own primitives, from a summarized context of its own,
> while the protocol, the procedure and the guardian stay deterministic. The
> pinned llama3.3:70b flew the canonical mission on the mock, 690 decisions over
> ten flights, with no fallback, no guardian intervention, and every flight
> replayable exactly from its record.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [x] **12.1** Give each drone its own identity, belief state, active task, memory, inbox and decision history — **the model server may be shared**
- [x] **12.2** Restrict the LLM to structured tools — 15 named tools; **no arbitrary Python or AirSim calls**
- [x] **12.3** Use a structured decision schema — situation assessment, selected tool, parameters, outgoing messages, confidence
- [x] **12.4** Give the LLM only relevant context — **not** the complete raw flight log or every previous message
- [x] **12.5** Use deterministic tools for calculations — distance, travel time, battery, reachability, task cost, route feasibility, separation risk
- [x] **12.6** Add timeout and fallback behaviour — **one** structured correction, otherwise deterministic fallback, and **record the event**
- [x] **12.7** Freeze the model for formal experiments — pinned local model, temperature zero, exact identifier recorded, all prompts and outputs saved, **no silent updates**

## Exit criterion

> Each drone uses a **distinct persistent agent context** to make
> mission-level decisions during flight, while every action still passes
> through structured validation and runtime assurance.

**Met:** yes, on the mock, 2026-11-05 — 5 of 5 seeds passed all four checks on both flights (no stop; Drone1
stopped at 60 s), the pinned 70B deciding, the guardian and keep-out on, every flight replayed offline exactly from
its record, and the model frozen across the run · **Evidence:**
[`evidence/exit-criterion-2026-11-05.md`](evidence/exit-criterion-2026-11-05.md), and the model choice
[`evidence/model-choice-2026-11-05.md`](evidence/model-choice-2026-11-05.md).

## Deliverables

| Artifact | Location | State |
|---|---|---|
| The tools and the decision schema (12.2, 12.3, 12.5) | `agentic_uav/agents/llm_tools.py` | **Done** |
| Each drone's context (12.1, 12.4) | `agentic_uav/agents/llm_context.py` | **Done** |
| The LLM policy, its correction and fallback, its log (12.6) | `agentic_uav/agents/llm_policy.py` | **Done**; the echo model flies the rule team's flight exactly |
| The model clients and the frozen manifest (12.7) | `agentic_uav/planners/llm_ask.py`, `agentic_uav/experiments/llm.py`, `configs/llm/default.toml` | **Done**; llama3.3:70b pinned by digest |
| The model choice | `agentic_uav/experiments/llm_bench.py`, `scripts/llm_bench.py`, `results/llm-bench-*` | **Done**; bench1 and bench2 |
| The exit | `agentic_uav/experiments/llm_exit.py`, `scripts/llm_exit.py`, `results/`, `evidence/` | **Done**; exit met on the mock |
| Optional live flight | -- | **Not flown**, by the user's decision (below) |

## Plan

Approved 2026-11-05 with all eight recommendations, after it had been shown in
full -- including the sequencing question: AUV-22 marks Phase 12 "do not start
until Phases 1–16 are stable"; the user chose to build it now **as a
capability**, with formal LLM experiments waiting for Phases 13–17. Each step
committed; the user asked before anything is pushed; goldens unedited; every
run of record reproduced.

1. **The tools and the decision schema** -- AUV-12's tools on the rule team's
   primitives, targets symbolic, every number computed and given.
2. **One persistent context per drone** -- its own state only, summarized,
   with a size budget.
3. **The LLM policy** -- events only; one correction; then the rule policy;
   recorded. An ECHO model (answers the rule's choice) and a REPLAY model.
4. **Freezing** -- the model by name and digest, temperature 0, a seed, calls
   one at a time, every prompt and reply saved.
5. **The model choice by replay benchmark** on Vega -- the user chooses.
6. **The exit on the mock** on Vega -- five seeds, stop and no stop.
7. **An optional live flight.**
8. **Close.**

**The eight recommendations:** (1) Phase 12 now, as a capability; (2) the LLM
steers mission-level choices through tools, the protocol, bids and skills stay
deterministic -- what makes Architectures C and D a controlled comparison; (3)
calculations computed into the context, one model call per decision; (4) the
fallback is Phase 9's recovery policy, after one correction; (5) primary model
llama3.3:70b, pinned, temperature 0, serialized, the choice the user's after the
benchmark; (6) the echo must reproduce Phase 9 exactly, every real flight must
replay offline; (7) the exit on the mock, five seeds, mission success a
finding; (8) no hosted models.

## Record

### 2026-11-05 — steps 1–4: the tools, the context, the policy, the frozen model

**The split** (recommendation 2). Phase 9's `RecoveryPolicy` stays each drone's
PROTOCOL (contract-net, failure ladder, roles, every tick, as coordinator) and
its PROCEDURE: the take-off when the team mission is given, bookkeeping when a
search ends, retries after a failed skill, the way home and the landing once
begun, anything on the ground. Every other decision -- in the air, on a message,
a sighting, a link change, the periodic check, a refusal of its own last
choice -- is the MODEL's.

**The tools** (`agents/llm_tools.py`). Eleven ACTIONS the model picks one of,
each running on the rule policy's own methods: `continue_task` (added: most
events change nothing), `accept_task`, `start_search`, `go_to_waypoint` (target
`task` | `home` | `relay_point`, never coordinates), `act_as_relay`,
`return_home`, `hold`, `claim_task`, `decline_task` (the protocol then never bids
for it -- a new, empty-by-default `declined` set on the team policy),
`release_task`, `change_role`. Three PROTOCOL tools -- `announce_task`,
`send_bid`, `compute_task_cost` -- run for it every tick; bids are computed,
never estimated (12.5), and the model may not pick them. Two NOT YET --
`request_help`, `report_target` -- have no message to carry them (Phase 9's open
question 3); picking one is refused. Every action has a precondition check.

**The reply** (12.3): situation assessment, selected tool, parameters,
outgoing messages (recorded, never sent: the protocol sends messages),
confidence, and a short `reason_code` -- no chain of thought. Read as strictly
as Phase 11's channel; nothing raises.

**The context** (`agents/llm_context.py`): this drone's identity, role, task,
stage, what is flying, position and battery, the battery it takes to get home,
the reserve; time left, sectors, zones, keep-outs; every task with THIS
drone's computed bid or why it cannot bid; each teammate as it said it was and
as this drone's ladder sees it; its own link estimates; the events of this
decision; its own last five decisions; and every action possible now, already
checked. Deterministic: the same state, the same text.

**The policy** (`agents/llm_policy.py`). Each model decision: the rule's
choice worked out on copies (the echo's answer, and the agreement measure);
the context built; the model asked once, corrected once, else the rule policy
decides and the fallback is recorded; a choice equal to the rule's runs the
rule's own path, any other runs the tool. Its log keeps, per decision, the
context, a digest of the exact messages, every raw reply, the tool, the rule's
tool, agreement, problems and latency.

**The model and its clients** (12.7): `configs/llm/default.toml` -- the model by
name AND digest, temperature 0, seed 0, `num_ctx` 8192, `num_predict` 400, a 60 s
timeout; `preflight` refuses a server whose copy of the name has another digest.
`OllamaAsk` serializes calls (a batching server could answer the same prompt
differently); `EchoAsk`, `ReplayAsk`, `Recorder`.

**The echo flies the rule team's flight exactly** -- seed 17, with no stop and
with Drone1 stopped, every delivery, record, decision and trajectory knot, 65
and 67 model decisions all agreeing. And with stand-ins: garbage replies (one
correction, then the rule, every time), no reply (a timeout, recorded), a
correction that works, a replay (exact) and one off its record (fallback), and
a model that disagrees whenever it can (the tools really run, every command
through the guardian, no limit broken).

### 2026-11-05 — step 5: the model choice, twice

**bench1** (`results/llm-bench-20261105-125057-bench1`): 200 decisions sampled
from the 668 the echo flights recorded (seeds 1–5, stop and no stop), each put
to llama3.3:70b, llama3.1:8b and llama3.2:3b on Vega gpu02. **It found a flaw in
my menu, not in the models.** The context offered `start_search` and
`accept_task` even while the drone was already doing that, and did not say
what was flying: the 70B chose `start_search` 105 times of 200 while already
searching, the 3B `accept_task` 175 times -- each, executed, would restart the
search from its first lane -- and the 8B `continue_task` on arriving at its
sector, with nothing flying. The menu was corrected: what is flying is said;
no restart and no idle is offered. bench1 is kept as found: **how the actions
are offered steers what models choose.**

**bench2** (`results/llm-bench-20261105-131132-bench2`), the decisions
re-collected with the corrected context:

| Model | Usable | Agreed with the rule | Instead | p50 |
|---|---|---|---|---|
| llama3.3:70b | 200/200 | 192 | `start_search` on arriving, a few holds and declines | 3.2 s |
| llama3.1:8b | 200/200 | 90 | **`release_task` 88**: its sector given up mid-search | 0.53 s |
| llama3.2:3b | 194/200 | 8 | `release_task` 95, `hold` 55 | 0.35 s |

**The user chose llama3.3:70b** -- chosen beforehand because it gives better
decisions, and bench2 shows it: six times slower, far more reliable. The 8B's
give-backs would cost the team about 100 s each (Phase 11's finding). Its digest
is pinned. **The trade -- quality against latency against runtime assurance --
is to be its own part of the paper** (the user's call; vault note AUV-12F).

### 2026-11-05 — step 6: the exit, met on the mock

`scripts/llm_exit.py` (`experiments/llm_exit.py`): five seeds, each with no stop
and with Drone1 stopped at 60 s; the pinned 70B deciding; the guardian and the
keep-out on; every reply recorded, each flight then flown again offline from its
record. **5 of 5 seeds passed all four checks; the model was frozen** (the server
held the digest before the first flight and after the last). 690 model decisions
(689 at once, 1 after the correction, **0 fallbacks**), 650 procedural; **0
guardian interventions**; the mission met in all 10 flights; model latency p50
3.24 s, p95 3.55 s.

**Where it chose otherwise than the rule policy** (31 of 690): a hold of
another length while waiting (22); `claim_task` when Drone1's task came back
after the stop (5) -- bidding for it at once; `continue_task` while holding (3);
`accept_task` rather than `start_search` on arriving (1). Completion: 199.1 s on
seeds 1–3 and 193.0 s on 4–5 against the rule team's 194.1; the stopped
flights 308–309 s, as the rule team's.

**Two interrupted runs, said here.** The laptop's connection dropped twice
while the 70B was being asked -- the first time mid-benchmark (stopped by hand,
nothing written), the second mid-exit (stopped, nothing written; the Vega job
ended with the connection). From then on the job ran inside `screen` on the
login node (`tmux` is not installed); the runs of record are whole runs.

### 2026-11-05 — close

**Phase 12 is complete on the mock, as a capability.** All seven objectives are
done and the exit criterion is met. **Not done, and said so:** no live flight,
by the user's decision -- on a real clock the model's latency matters (3–5 s a
decision, four drones queueing on one GPU), and the policy does not yet stamp a
decision with when its information was read, so the guardian's 2 s command
timeout cannot see a stale one. Both are AUV-12F's: its own experiment, on a
real clock. Formal LLM experiments wait for Phases 13–17. `request_help` and
`report_target` wait for messages that carry them.

**1,250 tests pass, 29 skipped**; the goldens unedited; every run of record from
Phases 5–11 reproduced. **Mutations: 21 on the LLM code, all caught** -- 13 at first; the
eight gaps (the task and hold preconditions, the relay's mapping, the ground as
procedure, a reply not possible now, the rule's own path for an agreeing choice,
the memory, the replay's order) each have a test now.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-05 | **Phase 12 now, as a capability; formal LLM experiments after Phases 13–17** | AUV-22's warning is about the LLM covering for an unfinished simulator; the deterministic team, network, recovery and guardian are verified, and Phase 13 needs the policy to exist |
| 2026-11-05 | **The rule policy stays protocol and procedure; the model chooses the rest** | The same primitives either way: Architectures C and D differ only in who chooses |
| 2026-11-05 | **Every number is computed into the context; one call per decision** | 12.5; a multi-round tool loop doubles the calls for nothing a context cannot carry |
| 2026-11-05 | **A choice equal to the rule's runs the rule's own path** | So the echo flies the rule team's flight exactly, which proves the machinery changes nothing by itself |
| 2026-11-05 | **Calls serialized, client and server** | A batching server can answer one prompt differently in company: reproducibility first |
| 2026-11-05 | **The menu says what is flying and offers no restart or idle** | bench1: offered, models chose restarts read as "carry on" |
| 2026-11-05 | **llama3.3:70b, pinned by digest** | The user's choice, on bench2's evidence |
| 2026-11-05 | **No live flight this phase** | The user's decision: real-clock latency is AUV-12F's experiment, after decisions carry when their information was read |

## Open questions

1. **Model size, decision latency and runtime assurance** -- the user's
   candidate paper finding (vault AUV-12F): measure it on a real clock, with
   decisions stamped, against three ways for the guardian to judge a late one.
2. **Stamp decisions with when their belief was read** -- before any real-clock
   LLM flight.
3. **`request_help` and `report_target`** need message types (Phase 9, open
   question 3).
4. **The 8B gave tasks back** in 88 of 200 decisions: a prompt problem, a model
   problem, or the menu again? Worth one look before a smaller model is dismissed
   for the swarm.

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
