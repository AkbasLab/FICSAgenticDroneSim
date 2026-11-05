# Keep-out check — search_relay_001 and search_relay_live_small, mock

Run 2026-11-05T10:00:55, `scripts/keepout_check.py`, 842.4 s wall. Keep-out 5 m either side of a teammate silent 10 s in the air, with the guardian; the four with each drone stopped at 60 s (twice each) and with no stop; the live pair's twin with each drone stopped at 17 s (twice each).

| Seed | phase_9_checks | twin_checks | kept_out | no_interventions | no_stop_unchanged |
|---|---|---|---|---|---|
| 1 | yes | **no** | yes | yes | yes |
| 2 | yes | **no** | yes | yes | yes |
| 3 | yes | yes | yes | yes | yes |
| 4 | yes | **no** | yes | yes | yes |
| 5 | yes | **no** | yes | yes | yes |
| 6 | yes | **no** | yes | yes | yes |
| 7 | yes | **no** | yes | yes | yes |
| 8 | yes | yes | yes | yes | yes |
| 9 | yes | yes | yes | yes | yes |
| 10 | yes | **no** | yes | yes | yes |
| 11 | yes | yes | yes | yes | yes |
| 12 | yes | **no** | yes | yes | yes |
| 13 | yes | yes | yes | yes | yes |
| 14 | yes | yes | yes | yes | yes |
| 15 | yes | yes | yes | yes | yes |
| 16 | yes | **no** | yes | yes | yes |
| 17 | yes | **no** | yes | yes | yes |
| 18 | yes | **no** | yes | yes | yes |
| 19 | yes | **no** | yes | yes | yes |
| 20 | yes | **no** | yes | yes | yes |

**Closest passes over every seed and stop** (findings): to where the stopped drone was last heard, 7.1 m; to where it truly hovered, 7.1 m (last heard up to 0.43 m from where it truly stopped).

**NOT ALL PASSED** — 7 of 20 seeds passed every check.

Problems:

* seed 1, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 1 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T1 by Drone2 at 32.7 s; detected, never reported: T2
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 2, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 2 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T2 by Drone2 at 32.7 s; detected, never reported: T1
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 4, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 4 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T1 by Drone2 at 32.7 s; detected, never reported: T2
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 5, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 5 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T2 by Drone2 at 32.7 s; detected, never reported: T1
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 6, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 6 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T2 by Drone2 at 32.7 s; detected, never reported: T1
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 7, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 7 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T1 by Drone2 at 32.7 s; detected, never reported: T2
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 10, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 10 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T2 by Drone2 at 32.7 s; detected, never reported: T1
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 12, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 12 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T1 by Drone2 at 32.7 s; detected, never reported: T2
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 16, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 16 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T1 by Drone2 at 32.7 s; detected, never reported: T2
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 17, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 17 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T2 by Drone2 at 32.7 s; detected, never reported: T1
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 18, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 18 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T1 by Drone2 at 32.7 s; detected, never reported: T2
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 19, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 19 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T2 by Drone2 at 32.7 s; detected, never reported: T1
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
* seed 20, twin_checks: Drone1 stopped: the mission was not met: search_relay_live_small seed 20 [mock-exact]: FAILED
  PASS  C1 coverage threshold reached: 1.0 (required 0.95) -- S1 1.000, S2 1.000
  PASS  C2 all targets detected: 2 (required 2) -- detected: T1, T2
  FAIL  C3 detections reported to base, or eventually synchronized: 1 (required 2) -- reported: T2 by Drone2 at 10.0 s; detected, never reported: T1
  PASS  C4 no restricted-region entry: 0 (required 0)
  PASS  C5 no collision or separation violation: {'collisions': 0, 'separation_violations': 0} (required {'collisions': 0, 'separation_violations': 0}) -- closest pair Drone1-Drone2 4.00 m
  PASS  C6 all functioning drones return safely: 1 (required 1) -- Drone2 94.5%
