# Network check — 20 seed(s)

Run 2026-11-04T16:58:01, `scripts/network_check.py`, 152.8 s wall. Heartbeats through the real bus, no flight: each drone of four broadcasting every 1 s for 1000 s (steady) and every 0.25 s for 100 s (burst). Loss and latency are tests at 1 %: each holds when no more than 2 of the seeds reject.

| Condition | Loss (mean measured) | Latency KS (rejections) | Rate limit | Partitions | Expiry | Seeds | All |
|---|---|---|---|---|---|---|---|
| nominal | 0.0000 vs 0; 0 rejected | 0 rejected | yes (0 refused) | yes (0 cut) | yes (0 expired) | yes | yes |
| moderate | 0.1011 vs 0.1; 0 rejected | 1 rejected | yes (0 refused) | yes (0 cut) | yes (0 expired) | yes | yes |
| severe | 0.2991 vs 0.3; 0 rejected | 0 rejected | yes (15920 refused) | yes (0 cut) | yes (474 expired) | yes | yes |
| partitioned | 0.0000 vs 0; 0 rejected | 0 rejected | yes (0 refused) | yes (9600 cut) | yes (0 expired) | yes | yes |

**Stress networks**: slow (3 ± 1 s) -- 66678 expired, none delivered late; narrow (500 B/s, four a second) -- latencies against the queue recomputed from sizes: held on every seed.

**10.6: VERIFIED**

Rejections and problems:

* moderate seed 6, latency: KS D 0.0158 above 0.0157 over 10767
