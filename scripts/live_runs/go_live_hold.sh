for T in H1 H2 H3; do
  bash ~/restart_sim.sh
  NAVRL_PROFILE=limit5 LEAK_PROBE=1 ~/run_navrl_py.sh live_full.py --tag $T --profile full_map_dynamic --leg-planner navrl --noclip off --overlay --separation-margin 0.7 --speed 4.75
  echo "LIVE_DONE $T"
done
echo ALL_LIVE_DONE
