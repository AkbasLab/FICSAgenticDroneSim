# What every figure shows

A plain guide to the plots in `docs/figures/` and `paper/figures/`. For each
one: what it is, how to read it, and what to take from it.

**Read this first.** Figures 3, 6 and 7 and the three pilot plots come from
early phases. In those, "D" is a **scripted stand-in** that always picks the
right action, not a real LLM. Those plots check that the code works. Real-LLM
results are figures 8 to 11.

Names used throughout:

| | |
|---|---|
| A | centralized: one controller assigns all work |
| B | independent: each drone does its own sector and never talks |
| C | deterministic decentralized: drones bid for work using fixed rules |
| D | agentic decentralized: same as C, but an LLM picks each action (main_v1) |
| DV2 | D plus a "report task complete" tool and wrong-step checks (main_v2) |
| E | open-loop: flies a fixed plan, no reaction to anything |

---

## `docs/figures/` - pilot stage (Phase 17)

### `pilot_timeline_D_n4_final_severe.png` - one run replayed from its logs

One mission (architecture D, 4 drones, heavy message loss, one drone dies at
the start), redrawn using only the files the run saved. If a run can be redrawn
from its logs, the logs are complete.

- **Trajectories (top left):** where each drone flew. The X marks the drone that died.
- **Mission progress (top right):** the green line is distinct sectors searched; the dotted line counts repeat sweeps too. Red triangles are sectors flown again.
- **Messages per 10 s:** blue arrived, red dropped.
- **Active task by drone:** which sector each drone was working on over time. A black arrow means it took over another drone's task; a red triangle means someone else was already on that task.
- **Role by drone:** scout, relay, reserve.
- **Messages reaching each drone:** green means everything arrived, red means nothing; a black box is a full outage.
- **LLM decisions:** each dot is a decision. Filled means the model chose; hollow means the backup chose.
- **Red text at the bottom:** problems the plot found automatically, for example 7 repeat sweeps.

**Takeaway:** we used these to find bugs that the averages hid. One example: a
dead drone's old bid kept beating the living drone, so its sector never got
flown. Four bugs were found this way and fixed.

### `pilot_timeline_C_n4_old_severe.png` - why the first "severe" setting was thrown out

Same kind of plot, for C under our first "severe" network.

- 86% of messages were lost, almost all to a rate limiter rather than random loss.
- Every drone ends up flying the same sectors together as a pack (the task rows are identical).
- Every seed gave the same result, so extra seeds told us nothing.

**Takeaway:** that setting measured a simulator quirk, not the network. We
redid the network levels (next figure).

### `comms_calibration.png` - how the network levels were picked

We raised packet loss (left column) and delay (right column) step by step,
then measured duplicate sectors (top row) and mission time (bottom row) for B,
C and D.

- B never talks, so it is flat. That shows the measurement only picks up coordination.
- C and D get worse as loss rises: more repeated sectors, longer missions.
- Grey bands are levels we rejected by written rules: too easy to matter, so bad nothing works, or every seed identical.
- The dashed lines are the chosen levels: moderate = 10% loss, severe = 50% loss.

**Takeaway:** the final network levels sit where communication actually makes
a difference.

---

## `paper/figures/` - figures for the paper

### fig1 - architecture

How one drone's agent is built. Sensing and messages update the **belief
state** (what the drone thinks is true). The **policy** picks an action: fixed
rules (C) or an LLM (D/DV2), and the two are swappable. The **safety
guardian** checks every command, wherever it came from. The **skill executor**
flies it. Agents never see the simulator's ground truth directly.

### fig2 - mission layout

The search area: four 40 × 40 m sectors (S1–S4), two targets (stars), a no-fly
zone (R1), the base, and the drone pads. This is the fixed layout. In the main
experiment, target and no-fly-zone positions are randomised per seed.

### fig3 - degraded communication (old Phase 10 levels)

Left: the share of messages delivered under each network setting (bars), and
how many sectors still got searched (line). Right: why messages were lost.
Most "severe" losses were the rate limiter, the same problem the pilot plot
above exposed. **These are the old levels, replaced by the calibrated ones.**

### fig4 - safety guardian

Thirteen deliberately unsafe commands (too low, too fast, into the no-fly
zone, collision course, NaN waypoint, and so on) were fed in. All 13 were
blocked by the check meant to catch them. "Narrowed" means the value was
clamped to a safe one; "rejected" means the command was refused.

### fig5 - what happens when the LLM gives bad output

Twelve kinds of broken model output (not JSON, a made-up tool, missing fields,
a timeout, an empty reply, and so on). Each one is caught, labelled, and the
drone falls back to the safe default action. 12/12 contained: a bad reply
never turns into a bad flight.

### fig6 - bid bug in the simulator

Left: in the simulator, all drones reported their position as the origin, so
every drone made the same bid and the tie-breaker picked the winner. Right:
after the fix, bids differ by distance, so the cost model actually decides.

### fig7 - early architecture comparison (Phase 13, scripted D)

A–E under the old four network settings, with and without a drone lost at
1 s, over 10 seeds. Columns: sectors covered, sectors flown twice, mission
time. B and E lose a quarter of the area when a drone dies; A gets very slow
under the old severe setting. **D here is scripted, not an LLM.**

### fig8 - main_v1 results (real Llama 8B)

Heatmaps of 1,280 held-out runs. Each box is one architecture under one
condition: shade and % = mission success, number = average mission time.
Top: by network. Bottom: with or without a drone failure. Left 2 drones, right
4. **Takeaway:** C and A are near 100%; B fails when there are more sectors
than drones; D (LLM) is low (4% with 2 drones, 62% with 4) and slow.

### fig9 - why D failed in main_v1

Left: what the LLM picked across 8,237 decisions. Almost all `start_search`, so
drones kept re-searching their finished sector. Right: runs where the model
ever reported a sector done mostly succeeded; runs where it never did mostly
failed. **Takeaway:** D had no clear "I'm done" tool.

### fig10 - main_v2 results (DV2, real Llama 8B)

Same heatmap layout as fig8, on 20 new seeds, with DV2 in place of D.
**Takeaway:** DV2 matches C everywhere (98.8% vs 98.4%), and both beat A on
time. 4 drones are faster but duplicate a bit more work.

### fig11 - D vs DV2

Left: share of each action the LLM picked. D (orange) is nearly all
`start_search`; DV2 (blue) reports completion and bids for new work. Right:
success next to C on the same seeds: D 4% / 62% vs DV2 100% / 98% (2 / 4
drones). **Takeaway:** the problem was the missing tool, not the model's
reasoning.

---

Regenerate any paper figure with `python scripts/make_paper_figures.py --only <name>`.
The numbers behind each are in `paper/figure_data/`.
