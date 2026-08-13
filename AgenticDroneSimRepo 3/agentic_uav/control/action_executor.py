"""Runs a decided plan on a drone, through the simulator adapter.

This is the piece that replaces the baseline's execute_mission loop. It never
touches AirSim itself - it only issues SkillCommands to a VehicleAdapter, so the
same executor drives the real simulator or the mock.
"""

from ..core.enums import ActionType, SkillStatus
from ..core.models import AgentDecision, SkillCommand, VehicleAdapter


class ActionExecutor:
    def __init__(self, adapter: VehicleAdapter):
        self.adapter = adapter

    def run(self, vehicle_id: str, decision: AgentDecision):
        """Arm+take off, run every step of the plan, then release control.

        This preserves the baseline lifecycle: automatic startup, then the
        planned actions in order, then shutdown - regardless of which planner
        produced the plan.
        """
        results = []

        # Automatic startup (arm, record ground level, take off, climb).
        self.adapter.execute_skill(vehicle_id, SkillCommand(ActionType.ARM_TAKEOFF.value))

        for command in decision.plan:
            result = self.adapter.execute_skill(vehicle_id, command)
            results.append(result)
            if result.status is SkillStatus.FAILED:
                # A failed skill stops this drone's plan (its own concern; other
                # drones are unaffected). Future work may replan instead.
                break

        # Always release control at the end, even if a step failed.
        self.adapter.stop(vehicle_id)
        return results
