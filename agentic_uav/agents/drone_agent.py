"""One drone's agent: it plans, then executes, through injected interfaces.

In the open-loop baseline an agent's whole life is: get an instruction, ask the
planner for a plan, execute it. That is exactly what this class does. It holds a
MissionPlanner and a VehicleAdapter but knows the concrete type of neither - so
swapping Gemini for Llama, or the real simulator for the mock, changes nothing
here. Later phases (communication, replanning, roles) will extend this class.
"""

from ..control.action_executor import ActionExecutor
from ..core.models import AgentContext, AgentDecision, VehicleAdapter
from ..planners.base_planner import MissionPlanner


class DroneAgent:
    def __init__(self, vehicle_id: str, planner: MissionPlanner,
                 adapter: VehicleAdapter):
        self.vehicle_id = vehicle_id
        self.planner = planner
        self.adapter = adapter
        self.executor = ActionExecutor(adapter)
        self.decision: AgentDecision | None = None

    def plan(self, instruction: str) -> AgentDecision:
        """Ask the planner for a plan (before anything flies)."""
        context = AgentContext(vehicle_id=self.vehicle_id, instruction=instruction)
        self.decision = self.planner.decide(context)
        return self.decision

    def execute(self):
        """Fly the planned mission. Must be called after plan()."""
        if self.decision is None:
            raise RuntimeError("execute() called before plan()")
        return self.executor.run(self.vehicle_id, self.decision)
