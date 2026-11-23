bash ~/restart_sim.sh
EVADE_SPEED=2.0 AGENT_MOVER_OVERFLY_MIN=1 NAVRL_STATIC_CLEAR=0.7 NAVRL_TREE_MARGIN=1.0 NAVRL_PROFILE=limit5 ~/run_navrl_py.sh live_random_auto.py --tag R46 --film rand_R46 --peds 14 --cars 12 --targets 10 --max-seconds 330 --height 0.75 --hide-object InstancedFoliageActor_0_Inst_127_31 > ~/live_rand_R46.log 2>&1
echo LIVE_DONE >> ~/live_rand_R46.log
