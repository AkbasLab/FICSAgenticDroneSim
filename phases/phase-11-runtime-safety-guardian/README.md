# Phase 11 — Add an independent runtime-safety guardian

**Stage:** 4 · Adversity · **Vault note:** `AUV-11 — The Runtime Safety Guardian`
**Started:** 2026-11-04 · **Completed:** 2026-11-04

> Phases 5–10 checked a decision with a placeholder: two rules, no limits on
> height, speed or place, nothing between a command and the drone but the
> agent's own good behaviour. Phase 12 puts an LLM behind the decisions. Before
> it does, Phase 11 puts a deterministic guardian between every decision and
> every skill, for every architecture: ten checks, four graded outcomes, five
> fallbacks chosen by the drone's state, and a log of its own -- and shows that
> unsafe commands injected through either channel, the rule policy's or an
> LLM's, never fly.

---

## Objectives

Mirrored from `AUV-22 — Phase Objectives Checklist`.

- [x] **11.1** Implement guardian checks — altitude bounds, geofence, restricted zones, waypoint validity, maximum speed, minimum battery reserve, command timeout, separation from other known drones, valid landing location, conflicting simultaneous commands
- [x] **11.2** Support four guardian outcomes — APPROVE, APPROVE_WITH_MODIFICATION, REJECT_AND_REPLAN, EXECUTE_SAFE_FALLBACK
- [x] **11.3** Define safe fallbacks — HOLD_POSITION, CLIMB_OR_DESCEND_TO_SAFE_LAYER, RETURN_HOME, LAND_AT_SAFE_LOCATION, CONTINUE_LAST_VALID_PLAN; chosen by flight phase, battery, comms, local hazards, belief certainty
- [x] **11.4** Keep guardian logs separate — proposed action, reason for rejection, modified or fallback action, resulting mission effect

## Exit criterion

> Unsafe or invalid LLM **and rule-policy** commands can be **deliberately
> injected**, and the guardian prevents their execution.

**Met:** yes, on the mock, 2026-11-04 — 20 of 20 seeds passed all five checks: each seed flown
without a guardian, guarded and clean, guarded through the LLM channel, and once for each of 33
injections -- rule-policy and LLM, every check, each outcome (720 flights). No injected command
started; what could be fixed flew fixed; no guarded flight broke a limit; with nothing injected, the
flights were Phase 9's knot for knot and the guardian intervened not once · **Evidence:**
[`evidence/exit-criterion-2026-11-04.md`](evidence/exit-criterion-2026-11-04.md).

## Deliverables

| Artifact | Location | State |
|---|---|---|
| The guardian: checks (11.1), outcomes (11.2), fallbacks (11.3), its log (11.4) | `agentic_uav/safety/guardian.py`, `configs/guardian/default.toml`, `agentic_uav/agents/validation.py` | **Done** 2026-11-04; goldens unedited; Phases 5–10 reproduce |
| Wired in: the agent's validator and executor handle | `agentic_uav/agents/drone_agent.py`, `agentic_uav/experiments/recovery.py` | **Done** 2026-11-04; a clean guarded flight is the unguarded flight, knot for knot |
| The LLM channel: a decision as text and back | `agentic_uav/agents/proposal.py`, `agentic_uav/agents/decision.py` | **Done** 2026-11-04 |
| The exit | `agentic_uav/experiments/guardian_exit.py`, `scripts/guardian_exit.py`, `results/`, `evidence/` | **Done** 2026-11-04; exit met on the mock |

## Plan

Approved 2026-11-04 with all seven recommendations, after it had been shown in
full; the user asked for the whole plan to be built, each step committed, and
to be asked before anything is pushed. The four Phase 2 goldens must pass
unedited after every step, and Phases 5–10's runs of record must still
reproduce.

1. **The checks and the four outcomes (11.1, 11.2).** `safety/guardian.py`:
   deterministic, pure functions over what the guardian can know, limits in a
   manifest (`configs/guardian/default.toml`). Ten checks -- altitude band,
   geofence, restricted zones, waypoint validity, maximum speed, battery
   reserve, command timeout, separation from teammates' last known positions,
   landing site, conflicting simultaneous commands. Four outcomes -- APPROVE;
   APPROVE WITH MODIFICATION (clamp the speed or altitude, move a waypoint just
   outside the fence onto it); REJECT AND REPLAN for what cannot be fixed;
   EXECUTE SAFE FALLBACK. Every check tested alone.
2. **Safe fallbacks (11.3).** Hold position; climb or descend to the drone's own
   layer; return home; land at a safe site; continue the last approved plan --
   chosen by a fixed table over flight phase, battery, the base link, hazards
   near, and how fresh the drone's news of its teammates is (stale news, a more
   conservative choice).
3. **Wiring it in, and its own log (11.4).** At the executor handle -- the only
   way an agent's command reaches a skill -- replacing the Phase 5 check, whose
   two rules move into it. REJECT keeps the GUARD_REJECTED replanning loop;
   FALLBACK is started by the guardian. Its own log per drone, apart from the
   decision trace. Without injections every earlier flight must come out
   identical, the guardian approving everything.
4. **The LLM's command channel.** A strict parser from a JSON proposal to a
   decision (the interface Phase 12's LLM will use): malformed or invalid comes
   back as a refusal with its reason, never an exception.
5. **The exit.** The canonical four-drone mission, rule-based team, seeds 1–20.
   Unsafe commands injected on a fixed schedule, at least one per check,
   through both channels: decisions substituted for the policy's own, and
   hand-written LLM-shaped proposals (malformed JSON, unknown skills, NaN,
   out-of-range values, through the zone, landing in it, duplicates). Pass: no
   injected unsafe command reaches a skill; the flown trajectories never break
   a limit; every injection logged with its expected outcome; without
   injection, zero interventions and flights identical to Phase 9. Findings:
   each injection's cost to the mission, against the same seed's clean flight.
6. **Close.** Records, vault report, memory; ask before push and tag.

**The seven recommendations:**

1. **The guardian is deterministic infrastructure at the executor handle,
   shared by every architecture.** The Phase 5 check folds into it; the agent
   cannot bypass it, because its handle is the guardian's.
2. **Limits in a manifest, fixed before any run:** geofence the operating box
   (sectors, start line, base) plus 20 m; altitude band 5–40 m; maximum speed
   8 m/s; battery reserve the scenario's 20 %; command timeout 2 s; separation
   the scenario's 2 m; landing within 5 m of the drone's own pad or the base.
   The rule-based team flies well inside all of these (12–24 m, 5 m/s).
3. **The guardian knows only what the drone does**: its own readings, the
   brief, its teammates' last known positions from delivered heartbeats. No
   ground truth, none of the agent's reasoning.
4. **When each outcome applies:** modify only what keeps the command's intent
   (speed, altitude, a waypoint just outside the fence); reject what cannot be
   fixed; fall back when replanning is exhausted (three refusals) or when the
   drone is unsafe right now.
5. **The LLM channel is built now, with no live model**: the injections are
   hand-written, LLM-shaped proposals; Phase 12 reuses the same parser.
6. **The exit flies on the perfect network**; degraded networks are a factor
   for later experiments.
7. **No live flight.** The guardian stops commands before they reach the
   simulator, so CarlaAir would add nothing to what it shows.

## Record

### 2026-11-04 — the plan, shown before it was approved

The plan above was written out in full in the message that asked for its
approval, and approved with all seven recommendations; the user asked for the
whole plan to be built. The live flights of Phases 8 and 9 are still the
user's, to fly later.

### 2026-11-04 — steps 1 and 2: the guardian -- its checks, outcomes and fallbacks (11.1, 11.2, 11.3)

Built as one module, so committed as one step: the fallbacks are the fourth
outcome's content, and neither is testable without the other.

**`safety/guardian.py`**, a new package behind the agents' own boundary (the
boundary test now walks it too): nothing in it may import the simulator or the
experiments, name a ground-truth type, or reach anything by reflection. **The
limits** are a manifest, `configs/guardian/default.toml`, read strictly, at the
values the plan fixed; the battery reserve and the separation are the brief's
own, so the guardian and the judge can never disagree on them.

**The checks**, each a pure function, each reason tagged with its check:

| Check | What it refuses | Can it be fixed? |
|---|---|---|
| `waypoint` | any number in the command not finite (NaN, ±inf) | no |
| `altitude` | outside 5–40 m | **clamped** to the band |
| `geofence` | a point outside the operating box (sectors, start line, base, 20 m round: x −28 to 220, y −100 to 100) | **moved onto the fence** if at most 20 m out; a search region **cut** to it; further, no |
| `restricted_zone` | a ground track touching a zone -- **Phase 5's rule, in Phase 5's words** | no |
| `speed` | over 8 m/s | **clamped** |
| `battery` | not home above the 20 % reserve, by the brief's model -- **Phase 5's rule, its words** | no |
| `timeout` | a decision made on news more than 2 s old (`Decision.issued_at`) | no |
| `separation` | a path passing within 2 m, in 3D, of a teammate's last known position, as heard and still current | no |
| `landing_site` | LAND more than 5 m from home or the base | no |
| `conflict` | a second command at the instant one was started | no |
| `finish_airborne` | FINISH in the air: nobody would decide for a hovering drone | no |
| `proposal` | an answer that could not be read as a decision (step 4) | no |

The last two are not in AUV-11's list; both came from asking what an LLM could
hand back that the ten would not catch.

**The four outcomes.** APPROVE as it stands. APPROVE WITH MODIFICATION when
everything wrong can be fixed -- and the fixed command then passes every other
check (a clamped route must still clear the zone and the battery), else it is
refused. REJECT AND REPLAN otherwise: the agent asks its policy again, with
GUARD_REJECTED, exactly Phase 5's loop. EXECUTE SAFE FALLBACK on the loop's
last ask (the guardian counts refusals at one instant; the fourth becomes a
fallback, so its count is tested equal to the loop's `MAX_REJECTIONS`), or
when the drone is **unsafe now** -- outside the fence, above the band, short of
the battery to get home and not heading there, a teammate inside the
separation -- and the decision is not an approved command.

**The fallbacks**, a fixed table in priority order: on the ground, stay there;
short of battery, LAND_AT_SAFE_LOCATION over home or the base, else
RETURN_HOME (routed round the zones, at its own layer); outside the fence,
RETURN_HOME; above the band, CLIMB_OR_DESCEND_TO_SAFE_LAYER (its own height);
a teammate within two separations, to its layer, or HOLD_POSITION if on it;
**any teammate never heard or no longer current, HOLD_POSITION** -- not
knowing where they are, it does not move (AUV-11's "certainty of the belief");
with an approved skill flying, CONTINUE_LAST_VALID_PLAN; else HOLD_POSITION.
Every fallback command is checked against the zones and the fence before it
is used, and becomes a hold if it fails.

**One input of the plan's list is not used: the base link.** Holding, moving or
landing is no safer with the base in reach than without; the communication
state that matters to safety is whether the drone still knows where its
teammates are, and that is the table's certainty row.

**What it knows.** Each review reads the parts of the belief the agent loop
writes from its sensors that tick (position, height, battery, airborne, home)
and the team records written from delivered messages -- nothing a policy
writes. Reading the belief rather than the sensors again is deliberate: the
same readings, and no extra sensor reads that could change a flight.

**Tests: 55, in `tests/test_guardian.py`** -- the manifest, the geometry, every
check both ways, each outcome's verdict and log entry, each row of the table,
the guarded handle; and Phase 5's two rules giving Phase 5's own reasons.

**The boundary caught the first draft.** `getattr`, `vars`, `re.compile` and a
`__name__` -- all harmless here -- are on the boundary's list because they are
the ways round an import ban; the module was rewritten with `asdict` and plain
string handling, and the test passes as it stood.

**Mutations: 30, all caught -- after seven gaps were closed.** The first pass
caught 23: the band's and the speed limit's exact edges, a route ending over
home counting as "heading home", a search region reaching far out but
overlapping the inside, and three of the four "unsafe now" conditions had no
test that could tell. Each has one now.

### 2026-11-04 — step 3: wired in, with its own log (11.4)

**The guardian sits twice, so it cannot be gone round.** It is the agent's
VALIDATOR -- each decision reviewed before the agent acts, the outcome deciding
what the agent then does -- and the agent's EXECUTOR HANDLE, `guardian.handle()`,
the only way it can start a skill. A command reaching the handle that the
review did not clear -- matched by identity, once -- is reviewed again as it
stands and **refused unless it passes unchanged** (`CommandRefused`): a
command from anywhere but a reviewed decision is never silently modified.

**In the agent loop** (`agents/drone_agent.py`) the change is small: the
verdict now carries the guardian's outcome and what runs instead, and the
agent acts on the replacement -- "modified by the guardian: started ...",
"guardian fallback HOLD_POSITION: started ...". Phase 5's step returns none of
these, so an unguarded agent is exactly what it was, and so is its trace: the
verdict's record gains keys only for a modification or a fallback. Earlier
phases' flights keep Phase 5's step, so their runs of record stand; from this
phase on, a flight given a guardian has the guardian instead.

**Its own log (11.4)**, per drone, apart from the decision trace: for every
intervention the proposal, its source (a decision, or direct to the handle),
the outcome, the checks failed and why, what ran instead, and the fallback.
Plain approvals are counted, not logged. The fourth item, the mission effect,
is measured by the exit, against the same seed's clean flight.

**On the team flight** (`experiments/recovery.py`) a `guardian=` gives each
drone its own, at its own layer; the run records every guardian and every
skill started with its full command (`executed`). Two hooks, `wrap_policy` and
`wrap_handle`, let the exit put its injections between an agent and its
policy or its handle, and are for nothing else.

**A clean guarded flight is the unguarded flight.** Seeds 1, 2, 3 and 17,
flown both ways: the same deliveries, the same drones' records, the same
decisions and actions, the same trajectory knot for knot -- and no
interventions, 113 approvals on seed 17. The exit checks it on every seed.

**Tests: 7, in `tests/test_guardian_agent.py`** -- each outcome changing what
the agent does and what its trace says, the fourth ask falling back, an
unguarded trace unchanged, and the team flight with and without a guardian.

### 2026-11-04 — step 4: the LLM's command channel

**`agents/proposal.py`**: `render_proposal` writes a decision as one JSON object
-- `decision`, `skill`, the skill command's own `parameters` by name,
`objective`, `reason` -- and `parse_proposal` reads one back. **It never
raises.** Text that states a decision exactly comes back as that decision,
with the text and when it was asked; anything else comes back as a new kind,
**INVALID**, carrying the text and every problem found -- not only the first --
each tagged with its check, for the guardian to refuse. Strict by design: an
unknown key at any level is a problem, not ignored, so a model cannot slip in
a field a reader would silently drop (`"override_guardian": true` is refused,
not skipped). NaN and infinity are refused at reading; so are a number written
as a word, a boolean for a number, a point with a field missing or one too
many, an array of two commands (`[conflict]`), and an abort that names a skill
(`[conflict]`: which is meant). Values the skill itself refuses -- 50 m/s --
come back with the skill's own message. A valid answer is not thereby safe:
it goes on to the guardian's checks.

**Round trip:** every one of the eleven skills, written and read back, is the
same decision.

**Tests: 15, in `tests/test_proposal.py`.** **Mutations: 10, all caught after two
gaps were closed** -- a point with an extra field, and `{"decision":
"invalid"}`, which the reader must not accept as a kind. The second exposed a
real gap one level down: **an INVALID decision with no problem listed would
have been approved by the guardian** (as "carry on"). The guardian now refuses
every INVALID decision, problems listed or not, and a test holds it.

### 2026-11-04 — step 5: the exit, met on the mock

**`experiments/guardian_exit.py`** and **`scripts/guardian_exit.py`**. Each seed,
the canonical mission with Phase 9's agents on Phase 9's network, no drone
stopped, flown: **without a guardian** (Phase 9's own flight); **guarded and
clean**; **guarded through the LLM channel** -- every drone's decisions written
as text and read back; and **once per injection**, 33 of them, each made by an
`Injector` at a fixed drone and time, at the first moment from then that fits:

* **Rule-policy channel (15).** The policy's own command MUTATED (take-off at
  60 m, at 3 m, at 15 m/s; its search region stretched 10 m past the fence;
  its next command on news 5 s old); another decision SUBSTITUTED for its
  answer (600 m out along y; the middle of the zone; x = NaN; a 4.5 km loop;
  the nearest teammate's last known position; LAND mid-mission; FINISH in the
  air); the zone REPEATED at every ask of one quiet decision, until the
  guardian falls back; and two that go round the policy to the handle itself
  -- a DIRECT start through the zone, and a CONFLICT, a hold sent at the
  instant the agent starts its own command.
* **LLM channel (18).** That drone's every decision goes through the channel,
  and at the injection its answer is text a model might write: JSON cut off,
  BARREL_ROLL, NaN, "high", an `override_guardian` key, 50 m/s, two commands
  in one answer, an answer 5 s late, malformed text at every ask -- or
  well-formed and unsafe: 12 m/s, 90 m, a region past the fence, 600 m out,
  the zone, a landing mid-mission, a teammate's position, the loop, a finish
  in the air.

Every check is injected; every check that can arrive by a channel arrives by
both (a rule policy hands back objects, never text; an LLM's NaN is caught
reading it); each outcome but APPROVE is expected on both. **The checks**, on
every seed: `clean_is_phase_9`, `channel_transparent`, `no_interventions`,
`injections_stopped` -- made, logged at its instant with the expected outcome
and check, the agent's trace showing the injected decision and what was done
with it, the injected command never started (a modification's replacement
started instead; a command at the handle refused there) -- and `limits_kept`,
as flown, in every guarded flight. Each check is shown able to fail on a real
flight's record altered to break it.

**The exit run of record: 20 of 20 seeds passed all five checks** (720 flights,
1,658 s): every injection made on every seed and caught as expected; no
limit broken in any of the 700 guarded flights; the clean flights Phase 9's,
knot for knot, through the LLM channel too; 2,275 commands approved as they
stood and no intervention. Evidence:
[`evidence/exit-criterion-2026-11-04.md`](evidence/exit-criterion-2026-11-04.md).

**The first full run was deleted, and why.** It met every check too -- but its
findings counted every guardian entry at the injection's instant as the
injection's own, so the policy's answer to a refusal, refused in its turn,
was never reported as a knock-on (it showed 0 where there were 20). A
knock-on is now whatever follows the injection's own review, even at its
instant; tested, and the run made again. The pass checks did not depend on it.

**What each injection cost the mission** (findings, not pass conditions; the
clean flight ends at 194.1 s on every seed -- the seed places the targets,
which changes nothing in these flights' timing, so each cost is the same on
every seed):

| | Injections | Cost to the mission |
|---|---|---|
| **Modified** | altitude, speed, a region past the fence -- both channels | 0 to 15 s: the take-off at 40 m costs 10 s, the search strip to the fence 15 s |
| **Fallen back** | the zone, or malformed text, at every ask | 0 s: CONTINUE_LAST_VALID_PLAN every time -- every teammate heard, an approved search flying |
| **Refused at the handle** | the direct start through the zone; the conflicting second command | 0 s: the policy is never told, and its own command flies |
| **Refused late** | the stale decisions, made as the drone set off home | 0 s (one knock-on: below) |
| **Refused in the mission** | every other refusal, both channels | **98 to 115 s** |

**The finding: one refused command costs the rule team a sector's worth of
time.** Phase 8's team policy answers any GUARD_REJECTED by giving its task
back and going home; the task is auctioned again and another drone flies it.
Safe, and the mission was met every time -- but under a policy whose commands
are refused often (Phase 12's LLM), that is the price of every refusal. AUV-11
asks the guardian's cost to be measurable separately; this is it, per refusal.

**The one knock-on: the guardian caught the policy's own unsafe answer.** On
every seed, refused (stale) on its way home, the rule policy's answer was
"land where it is" -- at (205, −8), no landing site. The guardian refused that
too, and the policy then routed home and landed there.

**Tests: 26, in `tests/test_guardian_exit.py`.** **Mutations: 19, all caught** --
17 at first (16 caught: a trace whose decision is not the injected one was not
noticed; a test plants one now) and 2 on the knock-on fix.

**Phases 5–10 reproduce** -- Phase 5's exit, Phase 6's knowledge exit, Phase 7's
exit and gate, Phase 8's exit, Phase 9's exit and Phase 10's network check,
all identical. **The goldens did not move.**

### 2026-11-04 — close

**Phase 11 is complete on the mock.** All four objectives are done and the exit
criterion is met: unsafe and invalid commands, injected through the
rule-policy channel and the LLM channel -- 33 kinds, every check, every
seed -- never reached a skill; what could be fixed flew fixed; nothing flown
broke a limit; and with nothing injected the guardian changed nothing.

**Not done, and said so:** no live flight, by the plan (recommendation 7). The
guardian checks at decisions and at the handle, not every tick: a drone that
drifts out of bounds between decisions is caught at its next one (an event,
or the 10 s periodic check). Separation is checked against teammates' last
known positions, not where they will be. The limits are placeholders until
AUV-16's pilots calibrate them. Earlier phases' flights keep Phase 5's step;
from Phase 12 every flight has the guardian.

**1,180 tests pass, 28 skipped** (live CarlaAir and real time); the goldens
unedited; Phases 5–10's runs of record identical; audit clean.

## Decisions

| Date | Decision | Why |
|---|---|---|
| 2026-11-04 | **The guardian sits twice: the agent's validator and its executor handle** | A validator can be skipped by whatever holds the handle; the handle alone could not tell the agent to replan. Both, and an unreviewed command is reviewed again |
| 2026-11-04 | **An unreviewed command is refused unless it passes unchanged** | Silently changing a command nobody reviewed would hide that it came round the policy |
| 2026-11-04 | **Phase 5's two rules keep Phase 5's words** | A reason a reader learnt in Phases 5–10 must still mean the same thing |
| 2026-11-04 | **Earlier phases' flights keep Phase 5's step** | Their runs of record must stand; a guarded clean flight is shown to be the same flight |
| 2026-11-04 | **Two checks beyond AUV-11's ten: a FINISH in the air, an unreadable answer** | Both are things an LLM can hand back that the ten would let through |
| 2026-11-04 | **The fourth refusal at one instant becomes the fallback** | The agent loop asks four times; the guardian answers its last ask, so its count is tested equal to the loop's |
| 2026-11-04 | **Unsafe now falls back, unless the decision is an approved command** | An approved command passed every check from where the drone is; anything else leaves it where it is unsafe |
| 2026-11-04 | **The fallback table does not use the base link** | No action is safer with the base in reach; whether the drone knows where its teammates are is what matters, and is used |
| 2026-11-04 | **The guardian reads the belief's loop-written parts, not the sensors again** | The same readings, nothing a policy writes, and no extra sensor reads to change a flight |
| 2026-11-04 | **Plain approvals counted, not logged** | A clean flight's log is empty; every entry is an intervention |
| 2026-11-04 | **The LLM channel refuses, never guesses** | An unknown key ignored is a field a model got past the reader; every problem reported, none raised |
| 2026-11-04 | **Every INVALID decision is refused, problems listed or not** | Found by a mutation: one with none listed would have been approved |
| 2026-11-04 | **For a stale decision, the trace is the evidence, not the command** | Refused, the policy may decide the same command again on fresh news; that start is its own |
| 2026-11-04 | **A knock-on is whatever follows the injection's own review, even at its instant** | The first run of record counted the policy's refused answer as the injection's; that run was deleted |

## Open questions

1. **A refusal costs the rule team a sector's worth of time** (98–115 s): it
   gives its task back on any GUARD_REJECTED. Should a refused drone replan the
   same task instead -- and is that the policy's job or the architecture's?
   Phase 12 will refuse an LLM more often than Phase 8's rules ever were.
2. **Checked at decisions, not every tick.** Is a per-tick watch (unsafe now,
   without waiting for an event) worth its cost, and does it change any flight?
3. **Separation by last known position** ignores where a teammate is going; a
   heartbeat can be 3 s old. Predicted positions, or the judge's monitor live?
4. **Calibrating the limits** to a real airframe and site (AUV-16): band,
   speed, fence margin, timeout.
5. **H5's measure.** Interventions per decision, by outcome and check, is now
   recorded per flight; Phase 12 and the experiments decide how it is reported.

---

*Folders: `results/` for measurements, `evidence/` for exit-criterion proof.*
