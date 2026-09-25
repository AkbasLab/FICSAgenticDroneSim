# CarlaAir Reference

The full operating reference for the simulator this study runs on: CarlaAir
v0.1.7 — CARLA 0.9.16 and AirSim 1.8.1 inside one Unreal Engine 4.26 process.

[`../CONTROLS.md`](../CONTROLS.md) is the short version — enough to start the
simulator and fly something. This is the long version: every control, feature
and API surface the build exposes.

**Writing your own agents against this platform?** Read
[00 · Architecture and Integration](00-architecture.md) first. It covers how the
pieces actually fit together — one Unreal process hosting two unrelated RPC
servers — and the four ways to wire agents to it, which is the decision that is
expensive to change later.

---

## The documents

| | Covers |
|---|---|
| [00 · Architecture and Integration](00-architecture.md) | **Start here for integration work.** One process with two RPC servers, the launch chain, ports, the Python client model, concurrency and determinism, four patterns for attaching agents, ground truth versus belief |
| [01 · Simulator Control](01-simulator-control.md) | Environment checks, launcher options, starting and stopping, **synchronous mode, ticking, pause, step and resume** |
| [02 · Maps and Navigation](02-maps-and-navigation.md) | The six towns, switching maps, layered `_Opt` variants, waypoints, lanes, junctions, route planning |
| [03 · World and Environment](03-world-and-environment.md) | Weather and time of day, street lighting and appearance, querying static scene objects |
| [04 · Actors and Traffic](04-actors-and-traffic.md) | Spawning vehicles and pedestrians, autopilot and the traffic manager, manual driving, traffic lights |
| [05 · Drone Flight](05-drone-flight.md) | Arming, takeoff, movement commands, low-level control, **the NED convention** |
| [06 · Sensors and Perception](06-sensors-and-perception.md) | Cameras and sensors on both sides, detection, visibility and occupancy queries |
| [07 · Recording, Debugging and Monitoring](07-recording-and-monitoring.md) | Recording and replay, debug drawing, logs and live monitoring |
| [08 · Shipped Scripts and Known Limits](08-scripts-and-limits.md) | The bundled example scripts, the agent layer, and what this build explicitly does not do |
| [09 · Diagnostics and Reference](09-diagnostics-and-reference.md) | Symptoms and causes, ports, paths, constants |
| [10 · API Index](10-api-index.md) | Every public method of the principal classes, by introspection |

---

## Four things that cost time if you do not know them

**Negative Z is up.** AirSim is North-East-Down, so 30 metres of altitude is
`z = -30`. A positive Z flies the aircraft into the ground. This is the single
most common error against this platform — see
[05 · Drone Flight](05-drone-flight.md).

**Velocity commands do not brake.** They apply for their duration and then stop
being applied; the aircraft coasts. Follow one with `hoverAsync()` to stop.

**There is no terrain collision.** The drone passes through the ground, so
landing cannot wait for a physical touchdown. Record the ground height before
takeoff and descend back to it deliberately.

**The map argument is ignored at boot.** This package always starts on
`ServerDefaultMap` — Town10HD — regardless of what you asked for. The patched
launcher works around it by switching over the API once the RPC port is up; the
`[Map]` line in the launch output is the authoritative statement of where you
actually are.

---

## Why these are generated

These documents are converted from *CarlaAir Command Reference v1.0*
(`D:\Research\CarlaAirDocs\`), whose API tables were produced by introspecting
the installed `carla` and `airsim` modules rather than copied from upstream
documentation. Where a method is listed here, it exists in this build.

**Edit the manual and regenerate; do not hand-edit these files.** Two copies of
the same reference drifting apart is worse than one that is occasionally stale.
