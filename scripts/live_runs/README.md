# Live-run scripts (CarlaAir on Heidi)

These were kept outside the repo, in the home folder next to the sim. They are copied here so the live runs and videos can be reproduced.

- `make_street_scenario.py` builds the medium, large, xlarge and full_map scenarios from the sim's road and object dumps.
- `live_full.py` runs six drones live on the full map (`--moving on|off` makes it keep clear of the simulator's cars and pedestrians). `live_view.py` is the chase-camera window. `run_recorder.py` is the camera and recording helper the others import.
- `zone_overlay.py` draws the scenario into the sim window: orange trees, red no-fly zones, green target rings, and optionally circles round drones and moving bodies. It only reads; it never commands a drone. (Drawing every tree on the full map once ate 60 GB of RAM, so large maps use a light draw.)
- `live_overfly.py` is the overfly test: a made-up 20 m tree on a clear road.
- `live_moving.py` is the live check of vehicles and pedestrians: one drone flies low along a road while a real pedestrian and a real car come at it, with `--avoid off` as the control. `live_moving_film.py` is the same mission as a filmed target mission with a chase camera.
- `live_big2.py` is the big filmed scene: autopilot cars (the simulator's Traffic Manager) and AI pedestrians (its walker AI) on a real street, the drone weaving through the sidewalk crowd to a first target and then through the traffic to a second. It loads the map's real buildings, trees, poles and props as keep-outs (`fics_drone/core/map_geometry.py`) and records the video through ffmpeg.
- `watchdog.sh` caps memory for a run; `go_live_*.sh` are the launchers used for the runs in the progress brief.

Paths assume Heidi's home folder (`~`) and the CarlaAir install there. Nothing here is NavRL itself. The real ground in this map is at world height 0.0 (the road) and 0.15 (the pavement); the older `GZ = -1.8` in some scripts is the drawing offset they were written with.
