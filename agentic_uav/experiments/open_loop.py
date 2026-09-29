"""Architecture E: the original preflight action list (Phase 13).

The system this project started as. A plan is fixed before the drone leaves the
ground and executed step by step, with no reaction to anything that happens
afterwards: not a failed skill, not a low battery, not a teammate going silent,
not a message from anyone.

It is kept as a *historical* baseline, and the paper should say so. Comparing
the proposed system against open-loop control is not a strong result - the
comparison is nearly rigged, because open-loop cannot respond to the very
disturbances the study introduces. Its value is showing the platform's
evolution, and giving a floor: any architecture that cannot beat a fixed action
list under degradation is not worth reporting.

Implemented as a policy rather than as a separate program so that E runs through
the same agent loop, the same skills, the same executor and the same guardian as
A-D. Only the decision rule differs, which is the whole point of Phase 13.
"""

from ..agents.objectives import Objective

#: The fixed sequence, decided before flight and never revisited.
PREFLIGHT_PLAN = (
    Objective.TAKE_OFF,
    Objective.GO_TO_SECTOR,
    Objective.SEARCH_SECTOR,
    Objective.REPORT,
    Objective.RETURN_HOME,
    Objective.LAND,
)


class OpenLoopPolicy:
    """Steps through a fixed plan, ignoring belief entirely.

    Implements the same two-method interface as every other policy, so the
    agent cannot tell the difference. The one thing it does read from belief is
    `landed`, and only to terminate - without that the agent would keep issuing
    commands to a drone sitting on the ground, which is an artefact of the
    harness rather than a property of open-loop control.
    """

    def __init__(self, plan=PREFLIGHT_PLAN):
        self.plan = tuple(plan)
        self.index = 0
        self.skipped_events = 0          # how much it ignored, for the write-up

    def next_objective(self, belief) -> Objective:
        # Everything the closed-loop policies would react to is counted and
        # discarded. Reporting that count is more informative than reporting
        # only that E did badly: it says *how many* chances to adapt were passed
        # up, which is the actual mechanism behind the result.
        if belief.has_events():
            self.skipped_events += 1

        if belief.landed or self.index >= len(self.plan):
            return Objective.DONE

        objective = self.plan[self.index]
        self.index += 1
        return objective

    def choose_skill(self, belief, objective):
        """Build the command with the same deterministic builder the others use.

        The difference between E and the rest is *when* decisions are made, not
        how a sweep is flown. Using a different command builder here would make
        E worse for an uninteresting second reason.
        """
        from ..agents.search_policy import SearchAgentPolicy
        return SearchAgentPolicy().choose_skill(belief, objective)

    def stats(self):
        return {"plan_length": len(self.plan),
                "plan_position": self.index,
                "events_ignored": self.skipped_events}
