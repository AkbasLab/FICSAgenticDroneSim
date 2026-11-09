for T in S1 S2 S3; do
  bash ~/restart_sim.sh
  NAVRL_MIN_SPEED=1.5 LEAK_PROBE=1 NAVRL_ACTION_LIMIT=5 NAVRL_VEL_INPUT=policy NAVRL_GOVERNOR=1 NAVRL_DOWN_ROW=1 NAVRL_TREE_MARGIN=2.0 ~/run_navrl_py.sh live_full.py --tag $T --profile full_map_dynamic --leg-planner navrl --noclip off --overlay --separation-margin 0.7 --speed 4.75
  echo "LIVE_DONE $T"
done
echo ALL_LIVE_DONE
