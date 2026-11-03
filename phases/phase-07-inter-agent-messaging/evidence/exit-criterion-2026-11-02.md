# Phase 7 exit criterion — evidence, 2026-11-02

> Four deterministic agents exchange heartbeats and status messages while flying, and their **local team
> beliefs update only when messages are delivered**.

**Met on the mock.** 20 of 20 seeds passed all six checks: 5820 teammate records, in 2020 decisions, each traced to a message delivered before the decision; in every blocked flight messages were sent, none arrived, and no belief moved. Generated from `../results/messaging-exit-20261102-213008-exit.jsonl`; nothing is transcribed.

## What ran

| | |
|---|---|
| Scenario | `configs/scenarios/search_relay_001.toml`: the canonical mission, four drones, four sectors |
| Agents | Drone1 `'search S1'`, Drone2 `'search S2'`, Drone3 `'search S3'`, Drone4 `'search S4'` — rule agents at 12, 16, 20, 24 m, each told only its task |
| Network (talking) | Phase 7's perfect network: a direct link within 100 m, judged when sent; no loss; read at the next tick (fixed 0.1 s delay, below the 0.5 s tick) |
| Each seed flown three ways | **talking**; **blocked**, the range cut to 1 m, so messages are sent and none arrives; **silent**, no messaging |
| Messages | a heartbeat a second (who, where, task, stage, battery) and a status after each decision (adds skill and health); one sequence per sender from 1 |
| Seeds | 1–20, Phase 4's |
| Code | commit `8e24d56` + the step-5 files (dirty: True); `agentic_uav` digest `480cafb6ab4486b4` |
| Wall time | 89.72 s for 60 flights and their checks |

## The six checks

| Check | What it requires |
|---|---|
| met | the talking flight completes its four tasks |
| exchanged | every agent sent heartbeats and status updates, and received both kinds from teammates |
| only on delivery | every teammate record in every decision came in a message from that teammate, delivered to that drone at or before the decision, carrying that teammate's task, aged from when it was sent; nothing undelivered is ever in a belief |
| known exactly | Phase 6's knowledge log passes every decision: complete; correct, a heard teammate's record saying where it truly was when it spoke; no leak, a teammate's true position nowhere but its own record |
| blocked moves nothing | in the blocked flight messages were sent, none was delivered, every teammate stays "never heard" |
| steers nothing | talking and blocked flights make exactly the silent flight's decisions |

Each is shown able to fail in `tests/test_messaging_exit.py`, on a real flight altered to break it: a record from no delivered message, from another drone's, delivered after the decision, with the wrong task or age; something undelivered believed; an agent that sent or heard nothing of a kind; a blocked flight that heard something, or sent nothing; talking that changed a decision; a record saying the wrong place or claiming to be fresher than it is; a teammate's position outside its own record.

## Every seed

| Seed | met | exchanged | only_on_delivery | known_exactly | blocked_moves_nothing | steers_nothing | Records checked | Delivered | Out of range | Pending at the end |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | yes | yes | yes | yes | yes | yes | 294 | 1598 | 643 | 156 |
| 2 | yes | yes | yes | yes | yes | yes | 291 | 1596 | 644 | 154 |
| 3 | yes | yes | yes | yes | yes | yes | 288 | 1594 | 643 | 154 |
| 4 | yes | yes | yes | yes | yes | yes | 288 | 1595 | 642 | 154 |
| 5 | yes | yes | yes | yes | yes | yes | 291 | 1594 | 646 | 154 |
| 6 | yes | yes | yes | yes | yes | yes | 288 | 1593 | 644 | 154 |
| 7 | yes | yes | yes | yes | yes | yes | 288 | 1594 | 643 | 154 |
| 8 | yes | yes | yes | yes | yes | yes | 294 | 1600 | 643 | 154 |
| 9 | yes | yes | yes | yes | yes | yes | 291 | 1598 | 642 | 154 |
| 10 | yes | yes | yes | yes | yes | yes | 294 | 1598 | 645 | 154 |
| 11 | yes | yes | yes | yes | yes | yes | 288 | 1594 | 643 | 154 |
| 12 | yes | yes | yes | yes | yes | yes | 291 | 1597 | 643 | 154 |
| 13 | yes | yes | yes | yes | yes | yes | 291 | 1597 | 643 | 154 |
| 14 | yes | yes | yes | yes | yes | yes | 291 | 1596 | 644 | 154 |
| 15 | yes | yes | yes | yes | yes | yes | 291 | 1599 | 641 | 154 |
| 16 | yes | yes | yes | yes | yes | yes | 294 | 1596 | 645 | 156 |
| 17 | yes | yes | yes | yes | yes | yes | 291 | 1595 | 645 | 154 |
| 18 | yes | yes | yes | yes | yes | yes | 294 | 1600 | 643 | 154 |
| 19 | yes | yes | yes | yes | yes | yes | 291 | 1597 | 643 | 154 |
| 20 | yes | yes | yes | yes | yes | yes | 291 | 1596 | 644 | 154 |

Across the seeds: 31927 delivered, 12869 out of range, 3084 still waiting for agents that had landed and stopped listening, none expired.

## Seed 17 in detail

**2394 deliveries** — 2091 heartbeats and 303 status updates, each a broadcast to the three teammates: 1595 delivered, 645 out of range, 154 pending at the end. 829,737 bytes sent, 550,908 delivered. **208** messages were in a belief when a decision was made; **195** were read by the policy deciding.

Who heard whom (messages delivered, sender → recipient):

| Sender \ recipient | Drone1 | Drone2 | Drone3 | Drone4 |
|---|---|---|---|---|
| Drone1 | — | 175 (0 out of range) | 115 (62 out of range) | 97 (80 out of range) |
| Drone2 | 177 (0 out of range) | — | 79 (98 out of range) | 112 (65 out of range) |
| Drone3 | 114 (72 out of range) | 78 (106 out of range) | — | 223 (0 out of range) |
| Drone4 | 96 (89 out of range) | 110 (73 out of range) | 219 (0 out of range) | — |

What Drone1 believed of its teammates at each of its decisions (the message its record came from, how old, whether still current) — every record traced to a delivered message:

| t s | Drone2 | Drone3 | Drone4 | Read by the policy |
|---|---|---|---|---|
| 0 | never heard | never heard | never heard | - |
| 7.5 | `Drone2#9`, 0.5 s | `Drone3#9`, 0.5 s | `Drone4#9`, 0.5 s | Drone2#9, Drone3#9, Drone4#9 |
| 17.5 | `Drone2#20`, 0.5 s | `Drone3#21`, 0.5 s | `Drone4#20`, 0.5 s | Drone2#20, Drone3#21, Drone4#20 |
| 27.5 | `Drone2#31`, 0.5 s | `Drone3#32`, 0.5 s | `Drone4#31`, 0.5 s | Drone2#31, Drone3#32, Drone4#31 |
| 29 | `Drone2#33`, 1 s | `Drone3#33`, 1 s | `Drone4#32`, 1 s | Drone2#33, Drone3#33, Drone4#32 |
| 39 | `Drone2#44`, 1 s | `Drone3#44`, 1 s | `Drone4#44`, 1 s | Drone2#44, Drone3#44, Drone4#44 |
| 47 | `Drone2#53`, 1 s | `Drone3#53`, 1 s | `Drone4#53`, 1 s | Drone2#53, Drone3#53, Drone4#53 |
| 57 | `Drone2#64`, 1 s | `Drone3#59`, 6 s, **expired** | `Drone4#54`, 10 s, **expired** | Drone2#64 |
| 67 | `Drone2#75`, 1 s | `Drone3#59`, 16 s, **expired** | `Drone4#54`, 20 s, **expired** | Drone2#75 |
| 73 | `Drone2#82`, 1 s | `Drone3#83`, 1 s | `Drone4#83`, 1 s | Drone2#82, Drone3#83, Drone4#83 |
| 83 | `Drone2#93`, 1 s | `Drone3#94`, 1 s | `Drone4#94`, 1 s | Drone2#93, Drone3#94, Drone4#94 |
| 90 | `Drone2#102`, 1 s | `Drone3#102`, 1 s | `Drone4#101`, 2 s | Drone2#102, Drone3#102, Drone4#101 |
| 100 | `Drone2#113`, 1 s | `Drone3#106`, 8 s, **expired** | `Drone4#101`, 12 s, **expired** | Drone2#113 |
| 110 | `Drone2#124`, 1 s | `Drone3#126`, 1 s | `Drone4#101`, 22 s, **expired** | Drone2#124, Drone3#126 |
| 115 | `Drone2#130`, 1 s | `Drone3#131`, 1 s | `Drone4#131`, 1 s | Drone2#130, Drone3#131, Drone4#131 |
| 122 | `Drone2#139`, 1 s | `Drone3#139`, 1 s | `Drone4#139`, 1 s | Drone2#139, Drone3#139, Drone4#139 |
| 128 | `Drone2#145`, 1 s | `Drone3#146`, 1 s | `Drone4#145`, 2 s | Drone2#145, Drone3#146, Drone4#145 |
| 138 | `Drone2#157`, 1 s | `Drone3#152`, 6 s, **expired** | `Drone4#145`, 12 s, **expired** | Drone2#157 |
| 148 | `Drone2#169`, 1 s | `Drone3#152`, 16 s, **expired** | `Drone4#145`, 22 s, **expired** | Drone2#169 |
| 149 | `Drone2#170`, 1 s | `Drone3#152`, 17 s, **expired** | `Drone4#145`, 23 s, **expired** | Drone2#170 |
| 155.5 | `Drone2#177`, 1 s | `Drone3#152`, 23.5 s, **expired** | `Drone4#145`, 29.5 s, **expired** | - |

**Beliefs go stale when delivery stops:** in seed 17, 90 decision-records held an expired teammate — heard earlier, then out of range for longer than the record's lifetime — and were shown as expired, not current.

For example, Drone2 at 47 s: it last heard Drone3 at 41.5 s (`Drone3#48`); the 7 messages Drone3 sent it since were out of range (at 101.8–127.3 m), so its record of Drone3 had expired.

**Exit criterion: MET** on the mock.
