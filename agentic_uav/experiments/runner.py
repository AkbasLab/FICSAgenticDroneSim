"""The Phase 1-2 open-loop mission runner.

An instruction in English becomes a plan, and the plan is flown start to finish
with no replanning. Every mission is bookended by the same lifecycle:

    arm_takeoff  ...the planned actions...  stop

which is what `test_behavior_preservation.py` pins. That test has guarded this
behaviour since Phase 2 and is the reason it still exists unchanged: the later
phases rebuilt everything above the adapter, and the invariant proving the
rebuild did not alter flight behaviour is that these exact action sequences
still come out.

This is also Architecture E in the Phase 13 comparison, where it is reached
through `experiments/open_loop.py` rather than through this function - that
version runs inside the agent loop so it shares the guardian and executor with
the other architectures. This module is kept for the original entry point
(`scripts/run_single_mission.py`) and for the behaviour-preservation test.
"""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from ..core.enums import ActionType
from ..core.models import AgentContext, SkillCommand


def plan_for(planner_factory, vehicle_id, instruction):
    """Build a planner and ask it for a plan.

    `planner_factory` may be a class, a zero-argument factory, or an already
    built planner; the Phase 1 scripts pass all three.
    """
    planner = planner_factory() if callable(planner_factory) else planner_factory
    decision = planner.decide(AgentContext(vehicle_id=vehicle_id,
                                           instruction=instruction))
    return decision.plan


def fly_plan(adapter, vehicle_id, plan):
    """Execute one plan, bookended by the baseline lifecycle.

    The arm/takeoff is issued by the runner rather than planned, so that a
    planner cannot forget it, and `stop` is issued whatever happened - an
    aircraft is not left armed because a step raised.
    """
    adapter.execute_skill(vehicle_id,
                          SkillCommand(action=ActionType.ARM_TAKEOFF.value))
    try:
        for command in plan:
            adapter.execute_skill(vehicle_id, command)
    finally:
        adapter.stop(vehicle_id)
    return True


def run_one(adapter, planner_factory, vehicle_id, instruction):
    plan = plan_for(planner_factory, vehicle_id, instruction)
    fly_plan(adapter, vehicle_id, plan)
    return {"vehicle_id": vehicle_id, "steps": len(plan)}


def run_mission(adapter, planner_factory, instructions: Dict[str, str],
                concurrent: bool = True) -> Dict[str, Any]:
    """Fly one instruction per drone.

    Returns `{vehicle_id: result_or_exception}`. A drone that fails does not
    stop the others - the exception is returned in its slot, which is what
    `metrics.summarize` counts. Sequential mode exists because the
    behaviour-preservation test needs a deterministic action order.
    """
    results: Dict[str, Any] = {}

    if not concurrent or len(instructions) == 1:
        for vehicle_id, instruction in instructions.items():
            try:
                results[vehicle_id] = run_one(adapter, planner_factory,
                                              vehicle_id, instruction)
            except Exception as e:                              # noqa: BLE001
                results[vehicle_id] = e
        return results

    with ThreadPoolExecutor(max_workers=max(1, len(instructions))) as pool:
        futures = {
            vehicle_id: pool.submit(run_one, adapter, planner_factory,
                                    vehicle_id, instruction)
            for vehicle_id, instruction in instructions.items()}
        for vehicle_id, future in futures.items():
            try:
                results[vehicle_id] = future.result()
            except Exception as e:                              # noqa: BLE001
                results[vehicle_id] = e
    return results
