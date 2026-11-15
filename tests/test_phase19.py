"""Phase 19: the analysis code does what docs/ANALYSIS_phase19.md says it does.

Synthetic runs only - no result directories needed.

Run: python tests/test_phase19.py
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "scripts"))

import phase19_analysis as an      # noqa: E402
import phase19_extract as ex       # noqa: E402
import phase19_failures as fl      # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))


def _row(arch, seed, t, ok=True, net="final_nominal", n=2, fail="none"):
    return {"design": "d", "arch": arch, "team_size": n, "network": net, "failure": fail,
            "seed": seed, "time_s": t, "success_num": 1.0 if ok else 0.0, "success": ok}


def test_pairs_only_match_the_same_mission():
    rows = [_row("X", 1, 100), _row("Y", 1, 90), _row("X", 2, 100),
            _row("Y", 2, 90, net="final_severe")]
    p = an.pairs(rows, "d", "X", "Y", "time_s")
    check("pairs are formed only on identical seed, team, network and failure",
          len(p) == 1 and p[0][1] == 10.0, p)


def test_paired_summary():
    rows = []
    for s in range(1, 21):
        rows += [_row("X", s, 100 + s % 3), _row("Y", s, 100)]
    out = an.summarize(an.pairs(rows, "d", "X", "Y", "time_s"))
    check("mean and median of the paired difference",
          abs(out["mean"] - sum(s % 3 for s in range(1, 21)) / 20) < 1e-9
          and out["median"] == 1.0, out)
    lo, hi = out["ci95_mean"]
    check("the seed-cluster bootstrap interval contains the mean", lo <= out["mean"] <= hi)
    check("shares better / equal / worse add to one",
          abs(out["share_better"] + out["share_equal"] + out["share_worse"] - 1) < 1e-9)
    check("an identical pair of architectures has no effect",
          an.summarize(an.pairs(rows, "d", "Y", "Y", "time_s"))["mean"] == 0)


def test_mcnemar_counts_only_discordant_pairs():
    rows = [_row("X", 1, 1, ok=True), _row("Y", 1, 1, ok=False),
            _row("X", 2, 1, ok=True), _row("Y", 2, 1, ok=True)]
    out = an.summarize(an.pairs(rows, "d", "X", "Y", "success_num"), binary=True)
    check("McNemar uses discordant pairs", out["x_only"] == 1 and out["y_only"] == 0
          and out["mcnemar_p"] == 1.0, out)


def _ev(t, typ, v=None, **data):
    return {"t": t, "type": typ, "vehicle": v, "data": data}


def test_recovery_is_measured_from_skills_not_messages():
    ev = [_ev(1, "SKILL_STARTED", "Drone2", skill="search_region", task="SEARCH_SECTOR_S2"),
          _ev(50, "FAULT_INJECTED", "Drone2", fault="vehicle_stopped"),
          _ev(60, "TASK_ASSIGNED", "Drone1", message_id="m1", to="Drone2"),
          _ev(80, "SKILL_STARTED", "Drone1", skill="go_to_waypoint", task="SEARCH_SECTOR_S2"),
          _ev(95, "SKILL_COMPLETED", "Drone1", skill="sector_sweep", sector="S2",
              outcome="sector_searched", started_at=95.0)]
    f = ex.event_features(ev, ["Drone1", "Drone2"], ["Drone2"])
    check("the orphan is the sector the lost drone was flying", f["orphan"] == "S2", f)
    check("recovery starts when a teammate flies toward it, not when a message arrives",
          f["recovery_start_s"] == 30.0, f)
    check("productive resumption uses the sweep's own start time",
          f["recovery_sweep_s"] == 45.0 and f["orphan_recovered"], f)
    ev2 = ev[:1] + [_ev(0.5, "SKILL_COMPLETED", "Drone2", skill="sector_sweep", sector="S2",
                        outcome="sector_searched", started_at=0.5)] + ev[1:2]
    check("a sector already swept before the failure is not orphaned",
          ex.event_features(ev2, ["Drone1", "Drone2"], ["Drone2"])["orphan"] is None)


def _run_dir(events, turns=None):
    d = tempfile.mkdtemp(prefix="p19_")
    with open(os.path.join(d, "events.jsonl"), "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    if turns is not None:
        os.makedirs(os.path.join(d, "llm"))
        with open(os.path.join(d, "llm", "Drone1.json"), "w", encoding="utf-8") as f:
            json.dump({"turns": turns}, f)
    return d


def _frow(**kw):
    r = {"team_size": "2", "lost": "", "not_landed": "", "coverage": "1.0", "arch": "C",
         "dup": "0", "role_changes": "1", "network": "final_moderate", "time_s": "200",
         "orphan": "", "orphan_recovered": "", "llm_perseveration": "", "llm_rej_format": ""}
    r.update(kw)
    return r


def test_failure_classes():
    d = _run_dir([_ev(t, "DECISION_PROPOSED", "Drone2", objective="claim_task")
                  for t in (1, 5, 9)])
    try:
        check("a drone that never took off is an evaluation artefact",
              fl.classify(_frow(not_landed="Drone2"), d)[0] == "EVALUATION_ARTEFACT")
    finally:
        shutil.rmtree(d)
    loop = [_ev(1, "SKILL_STARTED", "Drone2", skill="take_off")] + \
           [_ev(158.26, "DECISION_PROPOSED", "Drone2", objective="claim_task")] * 30
    d = _run_dir(loop)
    try:
        cls, contrib, *_ = fl.classify(_frow(not_landed="Drone2"), d)
        check("re-deciding at one instant until the budget runs out is stale information",
              cls == "STALE_INFORMATION" and "AGENT_LOOP_EXIT" in contrib, (cls, contrib))
    finally:
        shutil.rmtree(d)
    d = _run_dir([], turns=[{"tool": "start_search", "raw_response": "{}"}] * 5)
    try:
        cls = fl.classify(_frow(arch="D", coverage="0.5", llm_perseveration="12",
                                llm_rej_format="0"), d)[0]
        check("repeating completed searches is mission misinterpretation",
              cls == "LLM_MISSION_MISINTERPRETATION", cls)
        cls = fl.classify(_frow(arch="A", coverage="0.75"), d)[0]
        check("an unsearched sector with no other cause is task-not-reallocated",
              cls == "TASK_NOT_REALLOCATED", cls)
    finally:
        shutil.rmtree(d)


def main():
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        try:
            fn()
        except Exception as e:                                  # noqa: BLE001
            import traceback
            check(f"{fn.__name__} raised", False,
                  f"{type(e).__name__}: {e} {traceback.format_exc()[-300:]}")
    print("Phase 19 analysis\n")
    for n, _ in PASS:
        print(f"  ok    {n}")
    for n, d in FAIL:
        print(f"  FAIL  {n}  [{str(d)[:300]}]")
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
