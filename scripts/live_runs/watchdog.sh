#!/bin/bash
# logs memory of this user's biggest processes every 3 s and kills any live_full/live_view python above 6 GB
while true; do
  now=$(date +%T)
  ps -u gulama -o pid=,rss=,args= --sort=-rss | head -4 | awk -v t="$now" '{printf "%s pid %s rss_mb %d %s %s\n", t, $1, $2/1024, $3, $4}' >> ~/mem_watch.log
  for p in $(pgrep -u gulama -f "python.*(live_full|live_view)"); do
    r=$(awk '/VmRSS/ {print $2}' /proc/$p/status 2>/dev/null)
    if [ -n "$r" ] && [ "$r" -gt 6000000 ]; then kill -9 $p; echo "$now KILLED $p at $r kB" >> ~/mem_watch.log; fi
  done
  free_gb=$(free -g | awk '/Mem:/ {print $7}')
  if [ "$free_gb" -lt 15 ]; then for p in $(pgrep -u gulama -f "python.*live_full"); do kill -9 $p; done; echo "$now KILLED live_full: only $free_gb GB available" >> ~/mem_watch.log; fi
  sleep 3
done
