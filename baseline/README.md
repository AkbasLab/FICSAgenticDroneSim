# baseline/ — the control condition

This directory holds the **open-loop agent**: the system every later
architecture in the study is measured against. "Baseline" names its *role in the
experiment*, not its age and not where it came from.

All code here is original to this project. Nothing is vendored, and nothing
third-party is required at runtime — see
[`../docs/BASELINE_ENVIRONMENT.md`](../docs/BASELINE_ENVIRONMENT.md) §9.

---

## What the agent does

One instruction per drone becomes one complete action list, generated **before
takeoff**, validated, then executed to the end:

- each drone receives a **separate** natural-language instruction;
- the model produces a complete plan before any vehicle arms;
- plans are validated — shape, action names, parameters, durations, altitudes;
- drones execute **concurrently**, one thread each;
- **no replanning happens after launch.**

Two properties follow from that and are worth stating plainly. The agent is
**blind** — no camera image and no vehicle state ever reaches the model — and it
**never reconsiders**. Both are deliberate. Removing the second is the entire
point of Phase 5 onward; the first is removed no earlier than the perception
work.

```powershell
python baseline\open_loop_agent.py                      # interactive
python baseline\open_loop_agent.py --drones 2           # skip the count prompt
python baseline\open_loop_agent.py --plan-only \
    --instruction "fly forward for 5 seconds then land" # no simulator needed
```

`--plan-only` exercises the planner and validator without connecting to AirSim,
which is how the planner is tested without occupying the GPU. Every planning
call is appended to `runs/agent-log.jsonl` — instruction, raw model output,
validated plan, model id, `plan_seconds`, validity, and any normalisation
applied.

---

## Why it is a separate directory, and not part of the package

**It is frozen on purpose.** Once the ten-mission set has been run against it,
every comparison in the study cites those numbers. An edit here silently
invalidates them.

Phase 2 refactors the project into `agentic_uav/` — `core`, `simulator`,
`control`, `agents`, `coordination`, `planners`, `experiments`. **This directory
is deliberately excluded from that refactor.** Code inside the package will move
and change as the study progresses; a control condition that moves with it stops
being a control. Keeping it outside makes "frozen" something the layout
enforces, rather than something everyone has to remember.

It is also meant to be a **flat script**. The plan describes the baseline as the
flat-script system it starts from, so giving it a module tree, dependency
injection and interchangeable policies would misrepresent what is being
compared. The structure is part of the measurement.

If Phase 13 adopts it as the optional **arm E** — "the current open-loop
baseline, as history" — it gets a thin adapter inside the package, and the
script itself still does not change.

---

## Customising it

Every knob is a module-level constant or one small function, deliberately: this
is a script you are meant to be able to read end to end and change without
tracing abstractions.

| I want to… | Change | Notes |
|---|---|---|
| Use a different model | `--model llama3.1:8b`, or `MODEL` | 8B needs ~5.5 GB resident; close other applications. Both models are recorded per planning call, so runs stay attributable |
| Change inference settings | `OLLAMA_OPTIONS` | These are the measurement protocol, not preferences. Changing them starts a new result series |
| Add or remove an action | `ACTIONS`, then `PLAN_SCHEMA`, `SYSTEM_PROMPT`, `validate()`, `DroneRunner.step()` | All five, or the model will emit something the executor cannot fly. The `enum` in the schema is what stops invented actions |
| Change how a step flies | `DroneRunner.step()` | One `elif` per action. Velocity moves must be followed by `hoverAsync()` — velocity commands do not brake |
| Change cruise height, spacing, speed | `CRUISE_ALTITUDE`, `SPACING`, `MOVE_SPEED` | Speed multiplies every distance, because legs are specified in seconds, not metres |
| Tighten or loosen safety checks | `validate()` | Currently: required parameters, positive durations under `MAX_DURATION`, altitude between `MIN_ALTITUDE` and `MAX_ALTITUDE`, positive `z` normalised |
| Change the worked examples | `EXAMPLES` | **Never use a benchmark mission as an example.** It would score correct because it is in the prompt, not because the model solved it |
| Log extra fields | `PlanRecord.as_json()` | One JSON object per planning call, appended to `runs/agent-log.jsonl` |
| Use a different planner entirely | `plan_for()` | It returns a `PlanRecord`; anything that can produce one — another LLM, a rule-based policy, a stub for tests — drops straight in |

The mission set itself is data, not code:
[`../configs/missions/baseline_v1.toml`](../configs/missions/baseline_v1.toml).
Add a mission there and [`../tools/run_missions.py`](../tools/run_missions.py)
picks it up with no code change.

```powershell
python tools\run_missions.py --plan-only                       # whole set, scored
python tools\run_missions.py --plan-only --missions M05,M07    # a subset
python tools\run_missions.py --plan-only --model llama3.1:8b   # compare models
```

Results land in
[`../phases/phase-01-baseline-freeze/results/`](../phases/phase-01-baseline-freeze/results/)
as a JSONL of raw runs plus a Markdown summary table.

---

## Rules for this directory

1. **Do not refactor it** when the rest of the project is refactored.
2. **Do not edit it after mission results are recorded.** If something must
   change, that is a new version with its own tag and its own re-run of the
   mission set — not an edit.
3. **Do not import it from package code.** Nothing does today; a dependency
   would couple the frozen thing to the moving thing.
4. **Fix bugs by recording them, not by patching quietly.** A defect that
   affected recorded results belongs in
   [`../phases/phase-01-baseline-freeze/`](../phases/phase-01-baseline-freeze/)
   with the results it affected.

---

## Related

| | |
|---|---|
| What the baseline is, formally | `AUV-02 — Baseline Freeze` §1.1 |
| The machine it was measured on | [`../docs/BASELINE_ENVIRONMENT.md`](../docs/BASELINE_ENVIRONMENT.md) |
| The ten missions and the run protocol | [`../docs/BASELINE_MISSIONS.md`](../docs/BASELINE_MISSIONS.md) |
| What has actually been run so far | [`../phases/phase-01-baseline-freeze/`](../phases/phase-01-baseline-freeze/) |
| Flying it by hand | [`../docs/CONTROLS.md`](../docs/CONTROLS.md) |
