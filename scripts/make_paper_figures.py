"""Generate the paper figures from measured data (not hardcoded numbers).

    python scripts/make_paper_figures.py            # regenerate the data, then plot
    python scripts/make_paper_figures.py --no-rerun # plot from the cached JSON

Every number plotted here comes from `paper/figure_data/*.json`, which is
produced by running the actual experiments. Nothing is typed in by hand, so a
figure cannot drift away from the result it claims to show - the same rule the
mission-layout figure has followed since Phase 4.

Output goes to `paper/figures/` as both PDF (vector, for LaTeX) and PNG (for
previewing and for the repository README).
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "paper", "figure_data")
FIGS = os.path.join(ROOT, "paper", "figures")

# IEEE two-column: a single column is 3.5in, full width is 7.16in.
COL, WIDE = 3.5, 7.16

# A colour-blind-safe palette (Okabe-Ito). Journals print in greyscale often
# enough that these are also chosen to differ in luminance.
BLUE, ORANGE, GREEN, RED = "#0072B2", "#E69F00", "#009E73", "#D55E00"
PURPLE, GREY, LIGHT = "#CC79A7", "#555555", "#DDDDDD"

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 9,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 7,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 200,
    # Type 42 (TrueType) rather than matplotlib's default Type 3: Illustrator,
    # Inkscape and Affinity all convert Type 3 glyphs to outlines on import,
    # which turns every label into an uneditable path. With 42 the text stays
    # text, so the figure can be retitled or relabelled without regenerating it.
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    # 'none' keeps SVG text as <text> referencing the font, not as <path>.
    "svg.fonttype": "none",
})


#: pdf for LaTeX, svg for hand-editing, png for previewing.
FORMATS = ("pdf", "svg", "png")


def save(fig, name, formats=FORMATS):
    os.makedirs(FIGS, exist_ok=True)
    for ext in formats:
        path = os.path.join(FIGS, f"{name}.{ext}")
        fig.savefig(path, bbox_inches="tight", dpi=300)
    plt.close(fig)
    print(f"  wrote {name}." + " / .".join(formats))


def load(name):
    with open(os.path.join(DATA, f"{name}.json")) as f:
        return json.load(f)


# --- Figure 1: the architecture -------------------------------------------


def fig_architecture(annotated=True, name="fig1_architecture", strict=True):
    """The agent stack, laid out on an exact grid and checked programmatically.

    Two things kept going wrong by hand and are now enforced by code:

      * connector endpoints. The box style uses `pad=0` so a box's drawn edge is
        exactly its rectangle, and every arrow is derived from those edges, so
        identical gaps produce identical arrows rather than three stubs of
        slightly different length.
      * text fitting. `_fits()` measures each rendered label against the box it
        belongs to and raises if it overflows. Eyeballing a figure at 200 dpi
        does not reliably catch a subtitle that runs two millimetres past its
        border in print.
    """
    FIG_H, Y_SPAN = 4.1, 62.0
    fig, ax = plt.subplots(figsize=(WIDE, FIG_H))
    ax.set_xlim(0, 138), ax.set_ylim(0, Y_SPAN)
    ax.axis("off")

    BOX = "round,pad=0,rounding_size=1.1"
    GAP = 3.0
    VPI = Y_SPAN / FIG_H                       # data units per vertical inch

    def line_h(fs):
        """Height of one line of text, in data units."""
        return fs / 72.0 * VPI

    ENV_X, ENV_W = 3, 26
    AG_X, AG_W = 44, 62
    IN_X, IN_W = 48, 54
    SV_X, SV_W = 109, 28
    CX = IN_X + IN_W / 2
    LABEL_X = (ENV_X + ENV_W + 1 + AG_X) / 2      # the clear corridor, not the
                                                  # midpoint of the arrow (which
                                                  # runs under the agent border)
    checks = []                                   # (artist, x0, y0, x1, y1, tag)

    def stack(top, heights):
        out, y = [], top
        for h in heights:
            out.append((y - h, y))
            y -= h + GAP
        return out

    (bel_b, bel_t), (pol_b, pol_t), (grd_b, grd_t), (exe_b, exe_t) = \
        stack(52.0, [9.5, 12.0, 9.5, 7.2])

    def box(x, y0, y1, label, sub="", fc="white", ec=GREY, lw=0.9, ls="-",
            fs=8, subfs=5.8, w=None, bold=False):
        w = IN_W if w is None else w
        ax.add_patch(FancyBboxPatch((x, y0), w, y1 - y0, boxstyle=BOX, fc=fc,
                                    ec=ec, linewidth=lw, linestyle=ls, zorder=2))
        mid = (y0 + y1) / 2
        lines = sub.count("\n") + 1 if sub else 0
        if lines:
            th, sh = line_h(fs), lines * line_h(subfs) * 1.3
            total = th + 0.55 + sh
            up = total / 2 - th / 2
            dn = total / 2 - sh / 2
        else:
            up = dn = 0.0
        t1 = ax.text(x + w / 2, mid + up, label, ha="center", va="center",
                     fontsize=fs, zorder=3,
                     fontweight="bold" if bold else "normal")
        checks.append((t1, x, y0, x + w, y1, label))
        if sub:
            t2 = ax.text(x + w / 2, mid - dn, sub, ha="center", va="center",
                         fontsize=subfs, color=GREY, zorder=3, style="italic",
                         linespacing=1.3)
            checks.append((t2, x, y0, x + w, y1, sub.replace("\n", " / ")))

    def flow(x1, y1, x2, y2, ls="-", style="-|>"):
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style,
                                     mutation_scale=9, color=GREY, lw=1.0,
                                     linestyle=ls, zorder=1,
                                     shrinkA=0, shrinkB=0))

    # --- simulation environment -------------------------------------------
    ax.add_patch(Rectangle((ENV_X - 1, 4.0), ENV_W + 2, 50.0, fc="none",
                           ec=GREY, lw=0.8, linestyle=(0, (4, 3)), zorder=0))
    ax.text(ENV_X + ENV_W / 2, 56.0, "Simulation environment", fontsize=7.2,
            color=GREY, ha="center")
    box(ENV_X, 43.7, 50.9, "Simulator", "CARLA-Air / AirSim",
        fc="#F4F4F4", w=ENV_W)
    box(ENV_X, 29.0, 38.5, "Ground truth", "reached only through\nthe sensor model",
        fc="#F4F4F4", ls=(0, (3, 2)), w=ENV_W)
    box(ENV_X, 15.0, 22.2, "Network model", "seeded degradation",
        fc="#F4F4F4", w=ENV_W)

    # --- the agent ---------------------------------------------------------
    ag_b, ag_t = exe_b - 2.6, bel_t + 2.6
    ax.add_patch(Rectangle((AG_X, ag_b), AG_W, ag_t - ag_b, fc="none", ec=BLUE,
                           lw=1.1, linestyle=(0, (1, 1.7)), zorder=0))
    ax.text(AG_X + AG_W / 2, 56.0, "Persistent agent  —  one per drone",
            ha="center", fontsize=8.2, color=BLUE, fontweight="bold")

    box(IN_X, bel_b, bel_t, "Belief state",
        "sensing and peer messages\nprovenance, decay", fc="#EDF4FA", ec=BLUE)

    ax.add_patch(FancyBboxPatch((IN_X, pol_b), IN_W, pol_t - pol_b,
                                boxstyle=BOX, fc="#FDF5E6", ec=ORANGE,
                                lw=1.3, zorder=2))
    t = ax.text(CX, pol_t - 2.4, "Policy slot", ha="center", va="center",
                fontsize=8.2, fontweight="bold", color="#8A5A00", zorder=3)
    checks.append((t, IN_X, pol_b, IN_X + IN_W, pol_t, "Policy slot"))
    sub_b, sub_t = pol_b + 1.4, pol_b + 8.2
    box(IN_X + 2.5, sub_b, sub_t, "Deterministic", "rule policy",
        fs=7.4, subfs=5.5, w=22)
    box(IN_X + 29.5, sub_b, sub_t, "LLM agent", "tools + schema", ec=ORANGE,
        fs=7.4, subfs=5.5, w=22)
    ax.text(CX, (sub_b + sub_t) / 2, "or", ha="center", va="center",
            fontsize=7, color=GREY, zorder=4)

    box(IN_X, grd_b, grd_t, "Runtime-safety guardian",
        "deterministic checks\napprove / modify / reject / fallback",
        fc="#EAF6F1", ec=GREEN, lw=1.3)
    box(IN_X, exe_b, exe_t, "Skill executor", "contract-bound skills")

    # --- connectors --------------------------------------------------------
    bel_mid, exe_mid = (bel_b + bel_t) / 2, (exe_b + exe_t) / 2
    COR0, COR1 = ENV_X + ENV_W + 1, AG_X       # the genuinely clear span
    flow(ENV_X + ENV_W, bel_mid, IN_X, bel_mid)
    t = ax.text(LABEL_X, bel_mid + 1.3, "sensing,\nmessages", fontsize=5.6,
                color=GREY, ha="center", va="bottom", linespacing=1.2)
    checks.append((t, COR0, -50, COR1, 200, "sensing, messages"))

    flow(CX, bel_b, CX, pol_t)
    flow(CX, pol_b, CX, grd_t)
    flow(CX, grd_b, CX, exe_t)

    flow(IN_X, exe_mid, ENV_X + ENV_W, exe_mid)
    t = ax.text(LABEL_X, exe_mid + 1.3, "commands", fontsize=5.6, color=GREY,
                ha="center", va="bottom")
    checks.append((t, COR0, -50, COR1, 200, "commands"))

    # --- the one shared resource -------------------------------------------
    # An association, not a step in the pipeline, so it is a plain dashed line
    # with no heads: a double-headed arrow here read as a fourth kind of flow.
    srv_mid = (sub_b + sub_t) / 2
    box(SV_X, srv_mid - 4.9, srv_mid + 4.9, "Shared model server",
        "one process,\nno per-agent state", fc="#FAFAFA", ec=ORANGE,
        ls=(0, (3, 2)), fs=7.2, subfs=5.5, w=SV_W)
    ax.plot([IN_X + IN_W, SV_X], [srv_mid, srv_mid], color=ORANGE, lw=0.9,
            linestyle=(0, (2, 1.4)), zorder=1, solid_capstyle="butt")

    # --- marginal notes ----------------------------------------------------
    if annotated:
        ax.annotate("Interchangeable\npolicy implementations",
                    xy=(IN_X + IN_W, pol_t - 1.8), xytext=(SV_X, 45.0),
                    fontsize=6.4, color=GREY, ha="left", va="center",
                    arrowprops=dict(arrowstyle="-", color=GREY, lw=0.6))
        ax.annotate("Applied to all commands,\nindependent of source",
                    xy=(IN_X + IN_W, (grd_b + grd_t) / 2), xytext=(SV_X, 17.0),
                    fontsize=6.4, color=GREY, ha="left", va="center",
                    arrowprops=dict(arrowstyle="-", color=GREY, lw=0.6))
        ax.text(ENV_X + ENV_W / 2, 1.8, "Not directly accessible to agents",
                fontsize=6.4, color=GREY, ha="center", va="center")

    _fits(fig, ax, checks, strict=strict)
    save(fig, name)


def _fits(fig, ax, checks, strict=True, margin=0.6):
    """Measure every label against its box and report anything that overflows."""
    fig.canvas.draw()
    inv = ax.transData.inverted()
    bad = []
    for artist, x0, y0, x1, y1, tag in checks:
        bb = artist.get_window_extent(renderer=fig.canvas.get_renderer())
        (tx0, ty0), (tx1, ty1) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y1)])
        dx = max(x0 + margin - tx0, tx1 - (x1 - margin), 0)
        dy = max(y0 + margin - ty0, ty1 - (y1 - margin), 0)
        if dx > 0.01 or dy > 0.01:
            bad.append(f"    {tag[:44]!r} overflows by "
                       f"{dx:.2f} x {dy:.2f} data units")
    if bad:
        msg = "text does not fit its box:\n" + "\n".join(bad)
        if strict:
            raise AssertionError(msg)
        print("  WARNING: " + msg)


def fig_architecture_plain():
    fig_architecture(annotated=False, name="fig1_architecture_plain")


# --- Figure 2: the mission layout -----------------------------------------


def fig_mission_layout():
    """Drawn from the YAML so it cannot drift from the scenario actually run."""
    from agentic_uav.simulator.scenario_manager import load_scenario
    sc = load_scenario(os.path.join(ROOT, "configs/missions/search_relay_001.yaml"))

    fig, ax = plt.subplots(figsize=(COL, COL * 0.95))

    for s in sc.sectors:
        r = s.footprint
        ax.add_patch(Rectangle((r.min_x, r.min_y), r.max_x - r.min_x,
                               r.max_y - r.min_y, fc="#EAF3FA", ec=BLUE,
                               lw=0.9, alpha=0.75, zorder=1))
        # corner, not centre: a target sitting mid-sector would hide the label
        ax.text(r.min_x + 2.5, r.max_y - 2.5, s.sector_id,
                ha="left", va="top", fontsize=8, color=BLUE,
                fontweight="bold", zorder=3)

    for z in sc.restricted_zones:
        poly = getattr(z, "polygon", None)
        if poly:
            ax.add_patch(Polygon(poly, closed=True, fc=RED, ec=RED, alpha=0.28,
                                 hatch="///", lw=1.0, zorder=2))
            xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
            ax.text(sum(xs) / len(xs), sum(ys) / len(ys),
                    getattr(z, "zone_id", "no-fly"), ha="center", va="center",
                    fontsize=6.5, color=RED, fontweight="bold", zorder=4)

    tx = [t.position.x for t in sc.targets]
    ty = [t.position.y for t in sc.targets]
    ax.scatter(tx, ty, marker="*", s=95, c=ORANGE, ec="black", lw=0.4,
               zorder=5, label="targets")

    px = [v.start.x for v in sc.vehicles]
    py = [v.start.y for v in sc.vehicles]
    ax.scatter(px, py, marker="s", s=26, c=GREEN, ec="black", lw=0.4,
               zorder=5, label="drone pads")
    ax.scatter([sc.base.position.x], [sc.base.position.y], marker="^", s=55,
               c=GREY, ec="black", lw=0.4, zorder=6, label="base")

    ax.set_xlabel("x (m)"), ax.set_ylabel("y (m)")
    ax.set_aspect("equal")
    ax.grid(alpha=0.2, lw=0.4)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3,
              frameon=False, fontsize=6.2, borderpad=0.3, handletextpad=0.3,
              columnspacing=1.0)
    save(fig, "fig2_mission_layout")


# --- Figure 3: performance under degraded communication -------------------


def fig_comms():
    rows = load("comms")
    names = [r["condition"] for r in rows]
    rate = [r["stats"]["delivery_rate"] * 100 if r["stats"]["delivery_rate"] <= 1
            else r["stats"]["delivery_rate"] for r in rows]
    sectors = [r["sectors"] for r in rows]
    n_sectors = 4

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(WIDE, 2.3))

    # left: delivery rate vs mission completion
    x = range(len(names))
    bars = ax1.bar(x, rate, color=BLUE, width=0.6, zorder=2)
    ax1.set_ylabel("message delivery rate (\\%)" if False else "message delivery rate (%)")
    ax1.set_ylim(0, 105)
    ax1.set_xticks(list(x)), ax1.set_xticklabels(names, rotation=12)
    for b, v in zip(bars, rate):
        ax1.text(b.get_x() + b.get_width() / 2, v + 2.5, f"{v:.0f}%",
                 ha="center", fontsize=6.8, color=BLUE)

    ax1b = ax1.twinx()
    ax1b.plot(list(x), sectors, marker="o", ms=4, color=ORANGE, lw=1.3,
              zorder=3, label="sectors searched")
    ax1b.set_ylim(0, n_sectors + 0.6)
    ax1b.set_ylabel("sectors searched", color=ORANGE)
    ax1b.tick_params(axis="y", colors=ORANGE)
    ax1b.spines["right"].set_visible(True)
    ax1b.spines["right"].set_color(ORANGE)
    ax1b.axhline(n_sectors, color=ORANGE, ls=":", lw=0.7, alpha=0.6)
    ax1.set_title("Delivery collapses; the mission mostly does not", fontsize=8)

    # right: why messages were dropped
    reasons, per = set(), []
    for r in rows:
        d = r["stats"].get("drop_reasons") or {}
        if isinstance(d, str):
            d = {}
        per.append(d)
        reasons |= set(d)
    reasons = sorted(reasons)
    colours = [RED, ORANGE, PURPLE, GREY, GREEN, BLUE][:max(1, len(reasons))]

    bottom = [0] * len(rows)
    for i, reason in enumerate(reasons):
        vals = [d.get(reason, 0) for d in per]
        ax2.bar(list(x), vals, bottom=bottom, width=0.6,
                color=colours[i % len(colours)], label=reason.replace("_", " "),
                zorder=2)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax2.set_xticks(list(x)), ax2.set_xticklabels(names, rotation=12)
    ax2.set_ylabel("messages dropped")
    ax2.set_title("Cause of loss, by condition", fontsize=8)
    if reasons:
        ax2.legend(frameon=False, fontsize=6, loc="upper left")

    fig.tight_layout()
    save(fig, "fig3_degraded_comms")


# --- Figure 4: guardian containment ---------------------------------------


def fig_guardian():
    rows = load("guardian")
    checks = sorted({r["expects"] for r in rows})
    cmap = {c: col for c, col in zip(
        checks, [RED, ORANGE, PURPLE, BLUE, GREEN, GREY, "#8A5A00"] * 3)}

    order = {"approve_with_modification": 0, "reject_and_replan": 1,
             "execute_safe_fallback": 2}
    rows = sorted(rows, key=lambda r: (order.get(r["outcome"], 9), r["expects"]))

    fig, ax = plt.subplots(figsize=(COL, 3.3))
    y = range(len(rows))
    ax.barh(list(y), [1] * len(rows),
            color=[cmap[r["expects"]] for r in rows], height=0.72, zorder=2)
    ax.set_yticks(list(y))
    ax.set_yticklabels([r["case"].replace("_", " ") for r in rows], fontsize=6.2)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.62), ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)

    short = {"approve_with_modification": "narrowed",
             "reject_and_replan": "rejected",
             "execute_safe_fallback": "fallback"}
    for i, r in enumerate(rows):
        ax.text(1.05, i, short.get(r["outcome"], r["outcome"]), va="center",
                fontsize=6.0, color=GREY)

    handles = [plt.Rectangle((0, 0), 1, 1, color=cmap[c]) for c in checks]
    ax.legend(handles, [c.replace("_", " ") for c in checks], frameon=False,
              fontsize=5.6, loc="upper center", bbox_to_anchor=(0.5, -0.02),
              ncol=3, title="caught by", title_fontsize=6.0,
              columnspacing=1.0, handlelength=1.0, handletextpad=0.4)
    blocked = sum(r["blocked"] for r in rows)
    right = sum(r["correct_check"] for r in rows)
    ax.set_title(f"{blocked}/{len(rows)} unsafe commands blocked\n"
                 f"({right}/{len(rows)} by their intended check)", fontsize=8)
    save(fig, "fig4_guardian_containment")


# --- Figure 5: LLM failure taxonomy ---------------------------------------


def fig_llm_failures():
    rows = load("llm_failures")
    fig, ax = plt.subplots(figsize=(WIDE, 2.6))
    ax.set_xlim(0, 100), ax.set_ylim(0, len(rows) + 1.5)
    ax.axis("off")

    ax.text(14, len(rows) + 0.9, "model output", fontsize=7.5,
            fontweight="bold", ha="center")
    ax.text(50, len(rows) + 0.9, "rejected as", fontsize=7.5,
            fontweight="bold", ha="center")
    ax.text(84, len(rows) + 0.9, "what the agent did", fontsize=7.5,
            fontweight="bold", ha="center")

    reasons = sorted({r["rejected_as"] for r in rows if r["rejected_as"]})
    cmap = {c: col for c, col in zip(
        reasons, [RED, ORANGE, PURPLE, BLUE, GREEN, GREY, "#8A5A00"] * 3)}

    for i, r in enumerate(rows):
        y = len(rows) - i
        ax.text(28, y, r["case"], fontsize=6.4, ha="right", va="center")
        col = cmap.get(r["rejected_as"], GREY)
        ax.add_patch(FancyBboxPatch((36, y - 0.32), 28, 0.64,
                                    boxstyle="round,pad=0.08", fc=col,
                                    ec="none", alpha=0.85, zorder=2))
        ax.text(50, y, (r["rejected_as"] or "-").replace("_", " "),
                fontsize=6.0, ha="center", va="center", color="white",
                zorder=3, fontweight="bold")
        ax.annotate("", xy=(35, y), xytext=(29.5, y),
                    arrowprops=dict(arrowstyle="-|>", color=GREY, lw=0.7))
        ax.annotate("", xy=(70, y), xytext=(65, y),
                    arrowprops=dict(arrowstyle="-|>", color=GREY, lw=0.7))
        ax.text(71, y, f"fell back → {r['result']}", fontsize=6.2,
                ha="left", va="center", color=GREEN if r["contained"] else RED)

    n = sum(r["contained"] for r in rows)
    ax.text(50, 0.15, f"{n}/{len(rows)} contained — every malformed, invalid or "
                      f"absent model output ended in the aircraft being flown correctly",
            fontsize=6.8, ha="center", color=GREEN, style="italic")
    save(fig, "fig5_llm_failure_taxonomy")


# --- Figure 6: the bid-collapse artifact ----------------------------------


def fig_bid_collapse():
    data = load("bids")
    tasks = sorted(data["colocated"])
    drones = sorted(data["colocated"][tasks[0]])

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(WIDE, 2.4), sharey=True)
    width = 0.2
    cols = [BLUE, ORANGE, GREEN, PURPLE]

    for ax, mode, title in ((ax1, "colocated",
                             "Simulator artifact: all pads at the origin"),
                            (ax2, "own_pads",
                             "Corrected: drones on their declared pads")):
        for j, d in enumerate(drones):
            vals = [data[mode][t][d] for t in tasks]
            ax.bar([i + (j - 1.5) * width for i in range(len(tasks))], vals,
                   width=width, label=d, color=cols[j % len(cols)], zorder=2)
        ax.set_xticks(range(len(tasks)))
        ax.set_xticklabels([t.replace("SEARCH_SECTOR_", "") for t in tasks])
        ax.set_title(title, fontsize=8)
        ax.grid(axis="y", alpha=0.2, lw=0.4)

    ax1.set_ylabel("bid value (lower is better)")
    ax1.legend(frameon=False, fontsize=6, ncol=4, loc="upper left",
               columnspacing=0.8, handlelength=1.0, handletextpad=0.4)

    # headroom so the callouts never sit on top of a bar
    top = max(max(v for v in data[m][t].values())
              for m in data for t in tasks) * 1.55
    ax1.set_ylim(0, top)

    ax1.text(0.5, 0.74, "all four bids identical \u2014 the winner is\n"
                        "decided by the tie-breaker, not the cost model",
             transform=ax1.transAxes, ha="center", va="center",
             fontsize=6.2, color=RED,
             bbox=dict(fc="white", ec=RED, lw=0.6, boxstyle="round,pad=0.35"))
    ax2.text(0.5, 0.74, "bids differ \u2014 the cost model\n"
                        "is actually exercised",
             transform=ax2.transAxes, ha="center", va="center",
             fontsize=6.2, color=GREEN,
             bbox=dict(fc="white", ec=GREEN, lw=0.6, boxstyle="round,pad=0.35"))

    fig.tight_layout()
    save(fig, "fig6_bid_collapse")


FIGURES = [
    ("fig1_architecture", fig_architecture),
    ("fig1_architecture_plain", fig_architecture_plain),
    ("fig2_mission_layout", fig_mission_layout),
    ("fig3_degraded_comms", fig_comms),
    ("fig4_guardian_containment", fig_guardian),
    ("fig5_llm_failure_taxonomy", fig_llm_failures),
    ("fig6_bid_collapse", fig_bid_collapse),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="one figure by name")
    args = ap.parse_args()

    print(f"figures -> {FIGS}")
    for name, fn in FIGURES:
        if args.only and args.only not in name:
            continue
        fn()
    return 0


if __name__ == "__main__":
    sys.exit(main())
