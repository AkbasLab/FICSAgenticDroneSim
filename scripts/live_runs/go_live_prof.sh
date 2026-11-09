bash ~/restart_sim.sh
NAVRL_PROFILE=limit5 LEAK_PROBE=1 ~/run_navrl_py.sh live_full.py --tag P1 --profile full_map_dynamic --leg-planner navrl --noclip off --overlay --separation-margin 0.7 --speed 4.75
echo LIVE_DONE P1
