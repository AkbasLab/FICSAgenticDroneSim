"""Integration tests on the mock adapter (Phase 16.2).

One test per scenario named in 16.2, each a full end-to-end run of a real team
through the real allocator, bus, roles, guardian and executor. Nothing is
stubbed except the vehicle.

These exist as a separate file from the per-phase suites on purpose. The
per-phase tests ask "does this component obey its contract"; these ask "does
the assembled system still do the thing the component was built for". A defect
that lives in the wiring between two correct components can only be caught
here, and the exit criterion for Phase 16 is specifically that such defects are
found without launching CARLA-Air.

Scenarios, in the order 16.2 lists them:
  1. two agents allocate two tasks
  2. four agents allocate four tasks
  3. one agent disappears and its task is reassigned
  4. a partition divides the team
  5. delayed claims create a conflict and are resolved
  6. the relay agent fails and another agent assumes the role
  7. malformed LLM output triggers fallback

Run: python tests/test_integration.py
"""

import dataclasses
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.coordination import comms_conditions as cc
from agentic_uav.coordination.tasks import TaskStatus
from agentic_uav.experiments.team_runner import (
    build_allocating_team, run_team, run_team_with_faults)
from agentic_uav.simulator.mock_adapter import MockVehicleAdapter
from agentic_uav.simulator.scenario_manager import load_scenario

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIO = os.path.join(ROOT, "configs", "missions", "search_relay_001.yaml")

#: The lease must outlast the longest skill (a ~70 s sweep) or a healthy drone
#: loses its sector mid-flight. Phase 9 established this; it is repeated here
#: because an integration test that gets it wrong fails for the wrong reason.
LEASE_S = 150.0
HEARTBEAT_S = 15.0

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append((name, detail))


def _adapter(_vid):
    return MockVehicleAdapter(0.0)


def scenario(vehicles=None, sectors=None):
    """The canonical scenario, optionally trimmed to fewer drones and sectors.

    Trimming rather than writing a second YAML keeps every other property - the
    base, the targets, the no-fly zone, the separation minimum - identical to
    the scenario the rest of the project uses, so a two-drone result is
    comparable with a four-drone one.
    """
    sc = load_scenario(SCENARIO)
    if vehicles is None and sectors is None:
        return sc
    return dataclasses.replace(
        sc,
        vehicles=sc.vehicles[:vehicles] if vehicles else sc.vehicles,
        sectors=sc.sectors[:sectors] if sectors else sc.sectors)


def team(sc, network=None, seed=17, lease_s=LEASE_S, heartbeat_s=HEARTBEAT_S,
         policy_factory=None):
    return build_allocating_team(
        sc, _adapter, network=network, seed=seed, lease_s=lease_s,
        heartbeat_interval_s=heartbeat_s, policy_factory=policy_factory)


def completed(agents):
    """{task_id: holder} for tasks any agent believes are complete."""
    out = {}
    for a in agents:
        for t in a.allocator.board.all():
            if t.status is TaskStatus.COMPLETE:
                out.setdefault(t.task_id, t.assigned_agent)
    return out


def flown_by(agents):
    """{sector_id: {vehicle_ids}} counting only sectors a drone actually flew.

    `local_map.searched_regions` also contains sectors learned from a peer's
    report, so `by_vehicle` is what separates work done from work heard about.
    Using the former would let gossip count as coverage.
    """
    out = {}
    for a in agents:
        for r in a.belief.local_map.searched_regions:
            if r.by_vehicle == a.vehicle_id:
                out.setdefault(r.region_id, set()).add(a.vehicle_id)
    return out


# --- 1. two agents allocate two tasks -------------------------------------

def test_two_agents_allocate_two_tasks():
    """The smallest case that can still deadlock.

    Worth testing separately from the four-drone case: with two agents and two
    tasks every agent wins exactly one, so any off-by-one in the claim or
    release path shows up as one agent holding both or neither, where with four
    drones it can hide as a reassignment.
    """
    sc = scenario(vehicles=2, sectors=2)
    agents, tasks, bus, _t = team(sc)
    run_team(agents, tasks, bus)

    done = completed(agents)
    check("both tasks are completed", len(done) == 2, f"{done}")
    check("each agent completed one", sorted(done.values()) ==
          sorted(a.vehicle_id for a in agents), f"{done}")
    check("no sector was flown twice",
          all(len(v) == 1 for v in flown_by(agents).values()),
          f"{flown_by(agents)}")
    check("both agents landed",
          all(a.report().landed for a in agents),
          f"{ {a.vehicle_id: a.report().landed for a in agents} }")
    check("the team used two drones, not the scenario's four", len(agents) == 2)


# --- 2. four agents allocate four tasks -----------------------------------

def test_four_agents_allocate_four_tasks():
    agents, tasks, bus, _t = team(scenario())
    run_team(agents, tasks, bus)

    done = completed(agents)
    check("all four tasks are completed", len(done) == 4, f"{done}")
    check("one holder per task", len(set(done.values())) == 4, f"{done}")
    check("every sector was flown exactly once",
          sorted(len(v) for v in flown_by(agents).values()) == [1, 1, 1, 1],
          f"{flown_by(agents)}")
    check("every drone landed", all(a.report().landed for a in agents))
    # No central assignment exists to check against, so the property is that
    # every agent that has an opinion about a task has the same opinion.
    disagreements = []
    for a in agents:
        mine = completed([a])
        for task_id, holder in mine.items():
            if done[task_id] != holder:
                disagreements.append((a.vehicle_id, task_id, holder,
                                      done[task_id]))
    check("no two agents disagree about who completed a task",
          not disagreements, f"{disagreements[:3]}")


# --- 3. one agent disappears and its task is reassigned -------------------

def test_a_lost_agents_task_is_reassigned():
    sc = scenario()
    agents, tasks, bus, _t = team(sc)
    report = run_team_with_faults(agents, tasks, bus, stop_at={"Drone2": 5.0})

    done = completed(agents)
    survivors = [a for a in agents if a.vehicle_id != "Drone2"]
    check("the mission still completes every sector", len(done) == 4, f"{done}")
    check("the lost drone's sector was finished by someone else",
          done.get("SEARCH_SECTOR_S2") not in (None, "Drone2"),
          f"S2 held by {done.get('SEARCH_SECTOR_S2')}")
    check("every surviving drone landed",
          all(a.report().landed for a in survivors))
    check("the lost drone did not land", not any(
        a.report().landed for a in agents if a.vehicle_id == "Drone2"))
    check("no human command was needed after launch",
          getattr(report, "human_commands", 0) == 0)


# --- 4. a partition divides the team --------------------------------------

def test_a_partition_divides_the_team():
    """Two groups that cannot hear each other for most of the mission.

    The interesting property is not that it still works - it is that the two
    halves must not both claim the same sector while they are blind to each
    other, and must converge once the partition lifts. A system that silently
    duplicated the whole mission would still report full coverage, which is why
    the duplicate count is asserted and not just the coverage.
    """
    profile = cc.partitioned(group_a=("Drone1", "Drone2"),
                             group_b=("Drone3", "Drone4"),
                             start_s=5.0, end_s=120.0, base_side="a")
    agents, tasks, bus, _t = team(scenario(), network=profile)
    run_team(agents, tasks, bus)

    done = completed(agents)
    dup = {k: v for k, v in flown_by(agents).items() if len(v) > 1}
    stats = bus.stats()

    check("the partition actually blocked traffic",
          stats.get("drop_reasons", {}).get("partitioned", 0) > 0,
          f"{stats.get('drop_reasons')}")
    check("the mission still completes under a partition",
          len(done) == 4, f"{done}")
    check("every drone landed", all(a.report().landed for a in agents))

    # Duplicated work under a partition is not a defect and must not be
    # asserted away: two halves that cannot hear each other cannot divide work
    # between them, so some sectors get flown twice. The first version of this
    # test asserted zero duplication and failed, which was the test being wrong
    # about the system rather than the system being wrong.
    #
    # What is worth asserting is that the duplication is *caused* by the
    # partition and is bounded - the halves are not each flying the whole
    # mission independently.
    nominal_agents, nominal_tasks, nominal_bus, _n = team(scenario())
    run_team(nominal_agents, nominal_tasks, nominal_bus)
    nominal_dup = {k: v for k, v in flown_by(nominal_agents).items()
                   if len(v) > 1}
    check("the same scenario duplicates nothing when nobody is partitioned",
          not nominal_dup, f"{nominal_dup}")
    check("the partition is what causes the duplication", bool(dup),
          "no duplication under a partition - check the partition is active")
    check("the halves do not each re-fly the whole mission",
          len(dup) < len(flown_by(agents)),
          f"{len(dup)} of {len(flown_by(agents))} sectors duplicated")

    # What actually happened is sound: every sector was flown by somebody.
    check("every sector was flown by someone despite the partition",
          len(flown_by(agents)) == len(scenario().sectors),
          f"{sorted(flown_by(agents))}")
    check("the team collectively knows the work is done",
          len(done) == 4, f"{done}")

    # The task boards, however, do not reconcile once the partition lifts.
    # Pinned rather than asserted away, because it is a real limitation: there
    # is no anti-entropy step, so each half keeps whatever it last believed.
    # Observed on this run: one half has sectors still UNASSIGNED that the other
    # half completed, one sector is attributed to a drone that did not fly it,
    # and one is left CLAIMED by a drone that never flew it - so a longer
    # mission would have it fly that sector again.
    #
    # If reconciliation is implemented later, this test fails and should be
    # replaced with a convergence assertion.
    views = {a.vehicle_id: {t.task_id: (t.status.name, t.assigned_agent)
                            for t in a.allocator.board.all()} for a in agents}
    task_ids = sorted({k for v in views.values() for k in v})
    divergent = [tid for tid in task_ids
                 if len({views[v].get(tid) for v in views}) > 1]
    check("the boards are known not to reconcile after a partition",
          divergent, "the boards converged - reconciliation may now exist, "
                     "so replace this test with a convergence assertion")
    check("divergence is confined to the task board, not to the flying",
          all(len(v) >= 1 for v in flown_by(agents).values()))
    truth = {sid: sorted(v) for sid, v in flown_by(agents).items()}
    check("no sector is believed incomplete by every agent",
          all(any(views[v].get(tid, ("", None))[0] == "COMPLETE"
                  for v in views) for tid in task_ids),
          f"flown: {truth}")


# --- 5. delayed claims create a conflict and are resolved -----------------

def test_delayed_claims_conflict_and_resolve():
    """High latency makes two drones claim the same sector before either hears
    the other. The rules then have to pick the same winner on both sides."""
    profile = dataclasses.replace(cc.condition("nominal"),
                                  latency_ms_mean=60_000.0,
                                  latency_ms_jitter=0.0)
    agents, tasks, bus, _t = team(scenario(), network=profile)
    run_team(agents, tasks, bus)

    conflicts = [c for a in agents for c in a.allocator.conflicts]
    check("the delay really did produce colliding claims",
          conflicts, "no conflicts occurred, so the test proved nothing")

    # Every agent that saw a conflict must have resolved it the same way, or
    # two drones carry on believing they own the same sector.
    disagreements = []
    for a in agents:
        for t in a.allocator.board.all():
            for b in agents:
                other = next((x for x in b.allocator.board.all()
                              if x.task_id == t.task_id), None)
                if other is None or t.assigned_agent is None \
                        or other.assigned_agent is None:
                    continue
                if t.version == other.version \
                        and t.assigned_agent != other.assigned_agent:
                    disagreements.append(
                        (t.task_id, a.vehicle_id, t.assigned_agent,
                         b.vehicle_id, other.assigned_agent))
    check("agents at the same task version agree on the holder",
          not disagreements, f"{disagreements[:3]}")
    check("every conflict was logged with the rule that settled it",
          all(getattr(c, "rule", None) for c in conflicts),
          f"{[getattr(c, 'rule', None) for c in conflicts[:3]]}")
    check("every drone landed", all(a.report().landed for a in agents))


# --- 6. the relay agent fails and another assumes the role ----------------

def test_a_partitioned_drone_takes_the_relay_role():
    """A drone cut off from base must take the relay role on its own.

    This is the test that found the defect it now guards. Base reachability was
    computed from distance alone, so a partitioned drone sitting well within
    range still believed base was reachable - and RELAY is selected on exactly
    that flag. The role that exists to keep the team connected could not be
    triggered by losing communication, only by flying too far away.
    `NetworkModel.base_reachable_for` had been written for this and was called
    by nothing except its own unit test. The sensor now consults it.
    """
    profile = cc.partitioned(group_a=("Drone1", "Drone2"),
                             group_b=("Drone3", "Drone4"),
                             start_s=5.0, end_s=600.0, base_side="a")
    agents, tasks, bus, _t = team(scenario(), network=profile)
    run_team(agents, tasks, bus)

    roles = {a.vehicle_id: [h[2] for h in a.roles.history] for a in agents}
    cut_off = ["Drone3", "Drone4"]
    with_base = ["Drone1", "Drone2"]

    check("a drone cut off from base takes the relay role",
          any("relay" in roles[v] for v in cut_off), f"{roles}")
    check("the reason given is the loss of base contact",
          any("base unreachable" in h[3]
              for a in agents for h in a.roles.history), f"{roles}")
    check("drones that still have base contact do not become relays",
          not any("relay" in roles[v] for v in with_base), f"{roles}")
    check("the mission still completes", len(completed(agents)) == 4,
          f"{completed(agents)}")

    # The control: with no partition, nobody has any reason to relay.
    plain_agents, plain_tasks, plain_bus, _p = team(scenario())
    run_team(plain_agents, plain_tasks, plain_bus)
    check("nobody relays when communication is fine",
          not any("relay" in [h[2] for h in a.roles.history]
                  for a in plain_agents),
          f"{ {a.vehicle_id: a.roles.history for a in plain_agents} }")


def test_relay_takeover_is_only_reachable_at_component_level():
    """Documents a gap rather than asserting a capability.

    16.2 asks for "the relay agent fails and another agent assumes the role".
    The rule exists and works: a RESERVE drone that believes the relay is lost
    takes the role, and `test_roles_recovery.py` covers it directly.

    It cannot currently be reached in an assembled run, and the reason is worth
    recording. A drone with no task concludes there is no work remaining and
    lands - so by the time a relay is declared failed, roughly a minute of
    missed heartbeats later, the only drone that could have covered it is on the
    ground and has left the loop. RESERVE is therefore a role no agent holds
    while airborne for any length of time, which makes "available for failed or
    high-priority work" weaker in practice than it reads.

    Both halves are asserted below, so if the lifecycle is later changed to
    keep a spare loitering, this test fails and the gap gets revisited on
    purpose instead of by accident.
    """
    from agentic_uav.coordination.role_manager import RoleManager
    from agentic_uav.coordination.roles import HealthMonitor, Role

    # (a) the rule itself holds
    hm = HealthMonitor("Drone4", heartbeat_interval_s=10.0)
    hm.note_heard("Drone3", now=0.0)
    hm.tick(now=90.0, roster=[])
    rm = RoleManager("Drone4", hm)
    rm.role = Role.RESERVE
    sc = scenario()
    agents, tasks, bus, _t = team(sc)
    belief = agents[-1].belief
    # Base stays reachable on purpose: rule 1 ("base unreachable and no relay
    # active") is checked first and would mask the rule actually under test.
    belief.communication.base_reachable = True
    belief.receive_teammate_report("Drone3", role="relay", sent_at=0.0)
    decision = rm.decide(belief, open_task_count=0)
    check("a spare drone covers a relay it believes is lost",
          decision.role is Role.RELAY, f"chose {decision.role}")
    check("the decision names the drone it is covering for",
          "Drone3" in decision.reason, decision.reason)

    # (b) and in an assembled run the spare has already landed
    sc3 = scenario(sectors=3)                 # four drones, three sectors
    profile = cc.partitioned(group_a=("Drone1", "Drone2"),
                             group_b=("Drone3", "Drone4"),
                             start_s=5.0, end_s=600.0, base_side="a")
    agents, tasks, bus, _t = team(sc3, network=profile)
    run_team_with_faults(agents, tasks, bus, stop_at={"Drone3": 30.0})

    spare = next(a for a in agents if a.vehicle_id == "Drone4")
    relay = next(a for a in agents if a.vehicle_id == "Drone3")
    check("the relay role was held before the failure",
          "relay" in [h[2] for h in relay.roles.history],
          f"{relay.roles.history}")
    check("the spare drone has landed rather than standing by",
          spare.report().landed, "the spare was still airborne - "
          "the lifecycle may have changed, so revisit the gap")
    check("so no surviving drone takes over the relay role",
          "relay" not in [h[2] for h in spare.roles.history],
          f"{spare.roles.history} - takeover now happens, update this test")


# --- 7. malformed LLM output triggers fallback ----------------------------

def test_malformed_llm_output_falls_back_in_a_live_mission():
    """A backend that only ever returns rubbish, inside a real four-drone run.

    The unit tests cover each malformed shape. What this adds is that the
    fallback holds for an entire mission: the aircraft still fly, still divide
    the work and still land, with every decision coming from the deterministic
    policy.
    """
    from agentic_uav.agents.llm_backends import BackendError
    from agentic_uav.agents.llm_policy import LLMAgentPolicy

    class Rubbish:
        """Never returns a usable decision."""
        name = "rubbish"
        model = "rubbish-v0"

        def __init__(self):
            self.calls = 0

        def complete(self, system, user, **kw):
            self.calls += 1
            if self.calls % 3 == 0:
                raise BackendError("backend unreachable")
            return "I am afraid I cannot do that." if self.calls % 3 == 1 \
                else '{"objective": "FLY_TO_MOON", "tool":'

    backend = Rubbish()

    def policy_factory(vehicle_id, allocator):
        return LLMAgentPolicy(backend, vehicle_id, allocator=allocator,
                              timeout_s=None)

    agents, tasks, bus, _t = team(scenario(), policy_factory=policy_factory)
    run_team(agents, tasks, bus)

    check("the model was actually called", backend.calls > 0)
    done = completed(agents)
    check("the mission completes on the fallback alone", len(done) == 4,
          f"{done}")
    check("every drone landed", all(a.report().landed for a in agents))

    logs = [a.policy.log for a in agents if hasattr(a.policy, "log")]
    turns = [t for l in logs for t in l.turns]
    check("every decision is recorded as a fallback",
          turns and all(getattr(t, "used_fallback", False) for t in turns),
          f"{sum(1 for t in turns if getattr(t, 'fallback', False))}"
          f"/{len(turns)} fell back")
    # Every fallback must be explainable, but not every fallback is a
    # rejection: take-off, landing and end-of-mission are deterministic by
    # design and are recorded with a cause rather than a rejection reason.
    # Requiring a rejection reason for those conflated two different things.
    unexplained = [t for t in turns
                   if getattr(t, "used_fallback", False)
                   and not getattr(t, "rejection_reason", None)
                   and not getattr(t, "fallback_cause", None)]
    check("every fallback is explained, as a rejection or a stated cause",
          not unexplained,
          f"{len(unexplained)} unexplained of {len(turns)}")
    rejected = [t for t in turns if getattr(t, "rejection_reason", None)]
    check("the model's failures are named specifically",
          {str(t.rejection_reason) for t in rejected} >= {"malformed_json"},
          f"{ {str(t.rejection_reason) for t in rejected} }")
    check("a backend that ignores the interface is treated as a backend error",
          any("backend" in str(t.rejection_reason) for t in rejected),
          f"{ {str(t.rejection_reason) for t in rejected} }")
    # The point of the guardian is that it does not have to be involved here:
    # a malformed decision never becomes a command at all.
    interventions = sum(len(a.guardian_log.interventions()) for a in agents)
    check("no unsafe command reached the guardian", interventions == 0,
          f"{interventions} interventions")


def main():
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    print("Phase 16.2 integration (mock adapter)\n")
    for name, _ in PASS:
        print(f"  ok    {name}")
    for name, detail in FAIL:
        print(f"  FAIL  {name}" + (f"  [{detail}]" if detail else ""))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
