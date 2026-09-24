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
