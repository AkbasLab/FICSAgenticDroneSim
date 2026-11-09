# Live-run scripts (CarlaAir on Heidi)

These were kept outside the repo, in the home folder next to the sim. They are copied here unchanged so the live runs and videos can be reproduced.

- `make_street_scenario.py` builds the medium, large, xlarge and full_map scenarios from the sim's road and object dumps.
- `live_full.py` runs six drones live on the full map. `live_view.py` is the chase-camera window.
- `zone_overlay.py` draws the scenario into the sim window: orange trees, red no-fly zones, green target rings. It only reads; it never commands a drone. (Drawing every tree on the full map once ate 60 GB of RAM, so large maps use a light draw.)
- `live_overfly.py` is the overfly test: a made-up 20 m tree on a clear road.
- `watchdog.sh` caps memory for a run; `go_live_*.sh` are the launchers used for the runs in the progress brief.

Paths assume Heidi's home folder (`~`) and the CarlaAir install there. Nothing here is NavRL itself.
