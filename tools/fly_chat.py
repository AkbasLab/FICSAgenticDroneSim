#!/usr/bin/env python3
"""Free-form session: ask a model for plans and fly them, interactively.

    python tools/fly_chat.py

Asks how many drones you want and at what speed, then takes an instruction for
each, in plain English. Anything goes -- this is a sandbox, not the benchmark.

WHY THIS EXISTS
---------------
`run_missions.py` flies a fixed set and scores it. That is the right tool for
producing data and the wrong one for asking "what does this model do if I phrase
it like THIS", which is how you find out what the mission set does not cover.

It needs a model endpoint. By default `http://127.0.0.1:11435`, which is the
SSH tunnel to a GPU job on the cluster -- see docs/ for the setup. Override with
the OLLAMA_HOST environment variable.

It uses the SAME path as the study: same system prompt, schema, validator,
inference options, and `fly_plans` for the flight itself. That last one is
deliberate; the agent's own comment says the interactive and scored paths must
not diverge or they stop being the same experiment.

It writes NOTHING. No results file, no agent log -- `plan_for` and `fly_plans`
do not log; only `main()` does, and this is not it.

Commands:
    :drones N    change the number of drones (1-4) and respawn
    :speed N     change speed in m/s, and tell the model about it
    :status      where every drone is
    :reset       return all drones to their start poses
    :again       re-fly the last set of plans without asking the model
    :auto        toggle confirm-before-fly (default: confirm on)
    :plans       show the last plans with the raw model output
    :help        this list
    :quit
"""
import os
import sys
import time

# Derived from this file's own location, so the tool works in any clone. The
# repository is the parent of tools/.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "baseline"))

import airsim                      # noqa: E402  (kept for the type, not used directly)
import open_loop_agent as agent    # noqa: E402

ENDPOINT = os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11435"
MODEL = "llama3.3:70b"
MAX_DRONES = 4

# The study's frozen options, so a plan here is comparable with a recorded one.
OPTIONS = {"num_gpu": 999, "num_ctx": 4096, "temperature": 0,
           "num_predict": 512, "num_thread": 12}

C = {"dim": "\033[2m", "b": "\033[1m", "g": "\033[32m", "y": "\033[33m",
     "r": "\033[31m", "c": "\033[36m", "m": "\033[35m", "0": "\033[0m"}


def say(text="", colour=None):
    print(f"{C.get(colour, '')}{text}{C['0']}", flush=True)


def ask(prompt):
    return input(f"{C['b']}{prompt}{C['0']}").strip()


def describe(steps):
    out = []
    for s in steps:
        a = s["action"]
        if a == "set_altitude":
            out.append(f"{a} {abs(s['z']):.0f}m")
        elif a == "fly_to":
            out.append(f"{a}({s.get('x', 0):.0f},{s.get('y', 0):.0f})")
        elif "duration" in s:
            out.append(f"{a} {s['duration']}s")
        else:
            out.append(a)
    return " -> ".join(out)


def status(client):
    for d in client.listVehicles():
        p = client.simGetVehiclePose(d).position
        s = client.getMultirotorState(vehicle_name=d)
        say(f"  {d}: x {p.x_val:7.2f}  y {p.y_val:7.2f}  "
            f"{29.25 - p.z_val:6.2f} m AGL   landed={s.landed_state}  "
            f"api={client.isApiControlEnabled(vehicle_name=d)}", "c")


def set_speed(speed):
    """Change the speed AND the prompt that tells the model about it."""
    old = agent.MOVE_SPEED
    agent.MOVE_SPEED = speed
    agent.SYSTEM_PROMPT = agent.SYSTEM_PROMPT.replace(
        f"fixed at {old} m/s", f"fixed at {speed} m/s")
    return old


def report(outcomes, separation):
    say()
    say(f"  (flown at {agent.MOVE_SPEED} m/s)", "dim")
    for o in sorted(outcomes, key=lambda o: o["drone"]):
        ok = o["completed"] and o["landed_on_ground"]
        say(f"  {o['drone']}  {'/'.join(o['executed']) or '(nothing)'}"
            f"   {o['flight_seconds']}s", "g" if ok else "y")
        for a in o["step_altitudes_agl"]:
            asked = a.get("asked_agl")
            extra = "" if asked is None else f"   asked {asked}"
            say(f"       after {a['after']:<14} {a['agl']} m{extra}", "dim")
        if o["failure"]:
            say(f"       FAILED: {o['failure']}", "r")
        if not o["landed_on_ground"]:
            say(f"       did NOT land: {29.25 - o['final_position']['z']:.2f} m "
                f"above ground", "r")

    if separation.get("per_pair_min_m"):
        say(f"  closest approach per pair: {separation['per_pair_min_m']}", "dim")
    hits = separation.get("drone_collisions") or []
    obst = separation.get("obstacle_collisions") or []
    if hits:
        for h in hits:
            say(f"  DRONE CONTACT: {h['drone']} <-> {h['object']}  "
                f"{h['events']} events, worst {h['max_penetration_depth']} m, "
                f"t+{h['first_at_s']}", "r")
    if obst:
        for h in obst:
            say(f"  OBSTACLE: {h['drone']} hit {h['object']}", "r")
    if not hits and not obst:
        say("  no drone or obstacle contacts", "dim")
    say()


def collect(names):
    """One instruction per drone. Blank repeats the previous drone's."""
    say("  instructions (blank = same as the drone above, :cancel to abort)", "dim")
    instructions, previous = [], None
    for n in names:
        while True:
            text = ask(f"  {n}> ")
            if text == ":cancel":
                return None
            if not text and previous:
                text = previous
                say(f"       (same as above: {text})", "dim")
            if text:
                break
            say("       type something, or :cancel", "y")
        instructions.append(text)
        previous = text
    return instructions


def plan_all(names, instructions):
    records, bad = [], False
    say()
    for n, text in zip(names, instructions):
        t0 = time.time()
        try:
            r = agent.plan_for(text, n, model=MODEL, endpoint=ENDPOINT,
                               options=OPTIONS)
        except Exception as exc:
            say(f"  {n}: planning failed: {type(exc).__name__}: {exc}", "r")
            bad = True
            continue
        if not r.valid:
            say(f"  {n}: REJECTED ({time.time()-t0:.1f}s) {r.error}", "r")
            say(f"      raw: {r.raw_output}", "dim")
            bad = True
            continue
        say(f"  {n} ({r.plan_seconds:.1f}s): {describe(r.plan)}", "c")
        for note in r.normalised:
            say(f"      note: {note}", "y")
        records.append(r)
    return records, bad


def main():
    say("\nconnecting to the simulator ...", "dim")
    client = agent.connect()

    say(f"checking {ENDPOINT} ...", "dim")
    try:
        agent.check_endpoint(MODEL, ENDPOINT)
    except Exception as exc:
        say(f"endpoint problem: {exc}", "r")
        return 1
    say(f"endpoint OK, serving {MODEL} on the cluster", "g")

    # ------------------------------------------------------- how many drones
    while True:
        raw = ask(f"\nhow many drones? [1-{MAX_DRONES}] ")
        if raw.isdigit() and 1 <= int(raw) <= MAX_DRONES:
            count = int(raw)
            break
        say(f"  a number from 1 to {MAX_DRONES}", "y")

    # ------------------------------------------------------------ what speed
    #
    # Asked here and NOT in the study runner. Speed is the conversion factor
    # between the plan and the world -- legs are given in seconds, so distance
    # is speed x duration -- and a value typed at a prompt exists nowhere in the
    # record. In a scored run that would be an unrecorded variable, which is the
    # shape of every measurement failure this project has had. Here it is a
    # sandbox, nothing is recorded anyway, and varying it is one of the more
    # interesting things to try.
    while True:
        raw = ask(f"\nspeed in m/s? [blank = {agent.MOVE_SPEED} as in the study] ")
        if not raw:
            break
        try:
            speed = float(raw)
        except ValueError:
            say("  a number, e.g. 5 or 8.5", "y")
            continue
        if not 0.5 <= speed <= 20.0:
            say("  keep it between 0.5 and 20 m/s", "y")
            continue
        old = agent.MOVE_SPEED
        agent.MOVE_SPEED = speed
        # The system prompt is an f-string built at import, so the old number is
        # baked into it. Without this the model is TOLD 5 m/s while the aircraft
        # flies at something else, and every duration it reasons about is wrong.
        agent.SYSTEM_PROMPT = agent.SYSTEM_PROMPT.replace(
            f"fixed at {old} m/s", f"fixed at {speed} m/s")
        say(f"  speed {speed} m/s -- a 5 s leg is now {speed * 5:.0f} m, "
            f"not {old * 5:.0f} m", "m")
        break

    names = agent.vehicle_names(count)
    say(f"\nroster: {', '.join(names)}   speed {agent.MOVE_SPEED} m/s", "m")
    say("spawning any that are missing ...", "dim")
    agent.ensure_vehicles(client, names)
    status(client)
    say("\ntype instructions, or :help for commands\n", "dim")

    confirm = True
    last_records = None

    while True:
        try:
            line = ask("fly> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if line in (":quit", ":q", "quit", "exit"):
            break
        if line == ":help":
            say(__doc__.split("Commands:")[1], "dim")
            continue
        if line == ":status":
            status(client)
            continue
        if line == ":auto":
            confirm = not confirm
            say(f"confirm-before-fly is {'ON' if confirm else 'OFF'}", "y")
            continue
        if line == ":reset":
            agent.reset_world(client)
            agent.forget_ground_reference()
            say("world reset", "g")
            status(client)
            continue
        if line == ":plans":
            if not last_records:
                say("no plans yet", "y")
            for r in last_records or []:
                say(f"  {r.drone}: {r.instruction}", "dim")
                say(f"      raw : {r.raw_output}", "dim")
                say(f"      plan: {describe(r.plan)}", "c")
            continue
        if line.startswith(":speed"):
            parts = line.split()
            if len(parts) == 2:
                try:
                    speed = float(parts[1])
                except ValueError:
                    say("usage: :speed 8.5", "y")
                    continue
                if not 0.5 <= speed <= 20.0:
                    say("keep it between 0.5 and 20 m/s", "y")
                    continue
                old = set_speed(speed)
                say(f"speed {old} -> {speed} m/s   (a 5 s leg is now "
                    f"{speed * 5:.0f} m, was {old * 5:.0f} m)", "m")
                say("the model is told the new speed, so re-plan rather than "
                    ":again -- an old plan's durations assumed the old speed", "y")
            else:
                say(f"speed is {agent.MOVE_SPEED} m/s   (usage: :speed 8.5)", "c")
            continue
        if line.startswith(":drones"):
            parts = line.split()
            if len(parts) == 2 and parts[1].isdigit() and 1 <= int(parts[1]) <= MAX_DRONES:
                count = int(parts[1])
                names = agent.vehicle_names(count)
                agent.reset_world(client)
                agent.forget_ground_reference()
                agent.ensure_vehicles(client, names)
                say(f"roster is now {', '.join(names)}", "m")
                status(client)
            else:
                say(f"usage: :drones N   (1-{MAX_DRONES})", "y")
            continue

        if line == ":again":
            if not last_records:
                say("no plans to repeat", "y")
                continue
            records = last_records
        elif line.startswith(":"):
            say(f"unknown command {line}", "y")
            continue
        else:
            # The typed line is the first drone's instruction; ask for the rest.
            if count == 1:
                instructions = [line]
            else:
                say(f"  '{line}' is for {names[0]}", "dim")
                rest = collect(names[1:])
                if rest is None:
                    continue
                instructions = [line] + rest
            records, bad = plan_all(names, instructions)
            if bad or len(records) != count:
                say("  not flying: at least one plan was rejected", "y")
                continue
            last_records = records

        if confirm:
            try:
                if ask("  fly it? [y/N] ").lower() not in ("y", "yes"):
                    say("  not flown", "dim")
                    continue
            except (EOFError, KeyboardInterrupt):
                print()
                break

        agent.forget_ground_reference()
        try:
            outcomes, separation = agent.fly_plans(client, records)
        except Exception as exc:
            say(f"  flight failed: {type(exc).__name__}: {exc}", "r")
            continue
        report(outcomes, separation)

    say("bye", "dim")
    return 0


if __name__ == "__main__":
    sys.exit(main())
