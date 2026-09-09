# README images

Drop the files below into this folder using these exact names and the main
README picks them up. Until a file exists, GitHub shows a broken-image icon in
that spot — so add them before pushing, or delete the corresponding `<p
align="center">` block from README.md.

| File | What to capture | Source |
|---|---|---|
| `hero_fleet.png` | Best frame from a demo video — 4 drones airborne over Town10HD, mid-sweep. Wide crop (~16:9). | demo video |
| `architecture.png` | Block diagram: Task → Policy → Guardian → SkillExecutor → VehicleAdapter, with Belief ← SensorModel ← GroundTruth. | draw.io / Excalidraw |
| `phase3_skills.png` | 4 drones holding at distinct waypoints (the formation moment). | `scripts/phase3_demo.py --adapter airsim` |
| `mission_layout.png` | Sectors, targets, no-fly zone, base. | **auto-generated** — see below |
| `mission_report.png` | Terminal output with all criteria PASS and MISSION SUCCESS. | `scripts/run_canonical_mission.py` |
| `agent_decision_trace.png` | Terminal decision trace ending in TASK COMPLETE. | `scripts/run_persistent_agent.py` |
| `belief_audit_trail.png` | A couple of steps of KNEW / DID NOT KNOW / DECIDED. | `scripts/run_persistent_agent.py --log` |
| `team_messaging.png` | All four drones COMPLETE plus the message stats and by-type breakdown. | `scripts/run_team_mission.py` |
| `failure_recovery.png` | The kill line, who detected it, and the reassigned sector. | `scripts/run_failure_recovery.py` |

## Auto-generated figure

`mission_layout.png` is drawn straight from the scenario YAML, so it can't drift
out of sync with the config:

```bash
python scripts/plot_mission_layout.py --paths
```

## Tips for the terminal screenshots

- Use a dark theme and crop tight — no desktop, no window chrome.
- Widen the terminal so no line wraps (the audit trail is wide).
- Keep them to a few hundred KB; PNG at ~1400px wide is plenty.
