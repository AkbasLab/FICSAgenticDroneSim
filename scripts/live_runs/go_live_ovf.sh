bash ~/restart_sim.sh
NAVRL_PROFILE=limit5 ~/run_navrl_py.sh live_overfly.py --tag O3 > ~/live_overfly_O3.log 2>&1
echo LIVE_DONE >> ~/live_overfly_O3.log
