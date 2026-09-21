"""The LLM as a persistent agent policy (Phase 12.6).

This implements the *same two-method interface* as the deterministic Phase 5
policy — `next_objective(belief)` and `choose_skill(belief, objective)` — so the
agent loop, the allocator, the message bus and the Phase 11 guardian are
completely unchanged. None of them know or care that a model is involved. That
is the design's main safety property: the LLM is not wired into the control
path, it is wired into the *policy slot*, and everything that made the
deterministic system safe still sits downstream of it.

The turn:

    build bounded context  ->  model  ->  validate  ->  map tool to objective
                                  |
                              rejected
                                  |
                      one structured correction (12.6.1)
                                  |
                              still bad
                                  |
                   deterministic fallback policy (12.6.2)

**Fallback is not failure handling, it is the design.** An airborne drone cannot
wait for a model to get its JSON right. Every path out of a bad decision ends in
the Phase 5 policy flying the aircraft correctly, and the event is recorded
(12.6.3) so the fallback rate is a reported number rather than a hidden one.

One deliberate restriction: the model's chosen tool is mapped to an *objective*,
and the command is then built by the deterministic policy. The model picks
`start_search`; it does not get to hand the executor a hand-written sweep. The
only tool that carries model-supplied coordinates is `go_to_waypoint`, and those
coordinates pass the guardian like anything else.
"""

import time
from typing import Any, Dict, List, Optional

from ..control import skills as sk
from ..core.models import Position3D
from ..experiments.llm_log import LLMDecisionLog, LLMTurn
from . import context_builder, llm_tools, reasoning_tools
from .decision_schema import (
    DecisionError, RejectionReason, parse_decision, response_schema)
from .llm_backends import (
    BackendError, BackendTimeout, ModelCard, ScriptedBackend, call_with_timeout)
from .objectives import Objective
from .search_policy import SearchAgentPolicy

DEFAULT_TIMEOUT_S = 20.0

#: How a chosen tool becomes an objective the existing agent loop understands.
#: Coordination tools mostly resolve to CLAIM_TASK, which the Phase 8 loop
#: already treats as "deliberate, do not fly" - so a model that spends a turn
#: coordinating costs a decision cycle and no flight time, which is correct.
TOOL_OBJECTIVE = {
    "start_search": Objective.SEARCH_SECTOR,
    "go_to_waypoint": Objective.GO_TO_SECTOR,
    "return_home": Objective.RETURN_HOME,
    "hold": Objective.HOLD,
    "act_as_relay": Objective.HOLD,
    "report_target": Objective.REPORT,
    "accept_task": Objective.CLAIM_TASK,
    "claim_task": Objective.CLAIM_TASK,
    "send_bid": Objective.CLAIM_TASK,
    "compute_task_cost": Objective.CLAIM_TASK,
    "announce_task": Objective.CLAIM_TASK,
    "decline_task": Objective.CLAIM_TASK,
    "release_task": Objective.CLAIM_TASK,
    "request_help": Objective.CLAIM_TASK,
    "change_role": Objective.CLAIM_TASK,
}


class LLMAgentPolicy:
    """A persistent per-agent LLM policy.

    One instance per drone. It holds that drone's decision history and its own
    log; the *backend* may be shared with every other drone (12.1), because the
    backend holds nothing.
    """

    def __init__(self, backend, vehicle_id, fallback=None, timeout_s=DEFAULT_TIMEOUT_S,
                 safety_limits=None, allocator=None, capabilities=None,
                 allow_correction=True, log=None, memory_turns=6,
                 use_schema=True):
        self.backend = backend
        self.vehicle_id = vehicle_id
        self.fallback = fallback or SearchAgentPolicy()
        self.timeout_s = timeout_s
        self.safety_limits = safety_limits
        self.allocator = allocator
        self.capabilities = set(capabilities or {"search", "relay", "inspect"})
        self.allow_correction = allow_correction
        self.use_schema = use_schema

        card = backend.card() if hasattr(backend, "card") else None
        self.log = log or LLMDecisionLog(vehicle_id, model_card=card)

        #: this agent's own memory: the last few decisions it made. Bounded, so
        #: it cannot grow into the unbounded transcript 12.4 forbids.
        self.memory: List[Dict[str, Any]] = []
        self.memory_turns = memory_turns

        #: consecutive turns spent coordinating without acquiring a task. The
        #: Phase 11 lesson applied to the policy layer: a loop that is not
        #: converging must terminate itself rather than be asked forever.
        self.coordination_streak = 0
        self.max_coordination_streak = 6

        self.step = 0
        self.last_result = None
        self.last_turn: Optional[LLMTurn] = None
        self._pending: Optional[Any] = None      # the validated decision this turn
        self._inbox: List[Any] = []

    # --- what the agent feeds in ---

    def observe_messages(self, messages):
        """Called by the agent with whatever arrived this step."""
        if messages:
            self._inbox.extend(messages)
            self._inbox = self._inbox[-40:]      # bounded; the prompt takes ~6

    def observe_result(self, result):
        self.last_result = result

    # --- the policy interface ---

    def next_objective(self, belief) -> Objective:
        """Decide. This is where the model is actually called.

        Terminal and safety states are decided *before* the model is consulted,
        not by it. Asking a model whether to keep flying on a critical battery
        invites an interesting answer, and there is no interesting answer: the
        deterministic policy owns that decision, as it has since Phase 5.
        """
        self.step += 1

        if belief.landed:
            return Objective.DONE

        # Getting airborne is not a judgement call. The deterministic policy has
        # owned the take-off since Phase 5, and a model that selects a sweep
        # while the drone is still on the ground would otherwise skip it.
        if not belief.airborne:
            return self._fallback_objective(belief, cause="not_airborne_yet")

        # There is no `land` tool. That is deliberate in 12.2 - and it means the
        # model has no way to end a flight, so the terminal descent belongs to
        # the deterministic policy just as take-off does. Without this the agent
        # arrives home and asks to return home, over and over, until the step
        # cap: correct by the letter of every check, and still a drone hovering
        # over its own pad until the battery runs out.
        if belief.near_home and (belief.reported or belief.task is None):
            return self._fallback_objective(belief, cause="landing_is_deterministic")

        # The mission being over is a fact, not a judgement. Found the hard way:
        # with this check absent, two drones that had finished their sectors saw
        # "no task held", asked to bid, were told there was nothing to bid on,
        # and repeated that 117 times until the step cap - still airborne. A
        # model cannot infer "we are done" from a context that only ever says
        # "you hold no task", and it should not have to.
        if getattr(belief, "no_work_remaining", False):
            return self._fallback_objective(belief, cause="no_work_remaining")

        if belief.critical_battery or belief.low_battery:
            return self._fallback_objective(
                belief, cause="battery_reserved_for_safety")
        if getattr(belief, "rtb_forced", False):
            return self._fallback_objective(belief, cause="rtb_already_forced")

        turn, decision = self._decide(belief)
        self.last_turn = turn

        if decision is None:
            objective = self.fallback.next_objective(belief)
            turn.fallback_objective = objective.value
            self.log.record(turn)
            self._pending = None
            return objective

        self._pending = decision
        objective = TOOL_OBJECTIVE.get(decision.tool_name, Objective.HOLD)

        # A model may only fly toward work it actually holds. Without this, an
        # agent can announce it is searching a sector the team never awarded it,
        # and the Phase 8 allocation results become meaningless.
        if objective in (Objective.SEARCH_SECTOR, Objective.GO_TO_SECTOR) \
                and belief.task is None:
            turn.outcome = "tool required a task; none held -> claim first"
            objective = Objective.CLAIM_TASK

        # bounded deliberation: coordinating is a legitimate use of a turn, but
        # a run of them with no task to show for it is a stuck agent, not a
        # thoughtful one.
        if objective is Objective.CLAIM_TASK and belief.task is None:
            self.coordination_streak += 1
            if self.coordination_streak > self.max_coordination_streak:
                turn.used_fallback = True
                turn.fallback_cause = "coordination_not_converging"
                objective = self.fallback.next_objective(belief)
                turn.fallback_objective = objective.value
                self._pending = None
                self.coordination_streak = 0
        else:
            self.coordination_streak = 0

        turn.outcome = turn.outcome or objective.value
        self.log.record(turn)
        self._remember(turn, objective)
        return objective

    def choose_skill(self, belief, objective):
        """Turn the decision into a command.

        Commands are built by the deterministic policy wherever possible. The
        model chose *what*; the proven code decides *how*, with the constants
        (speed, lane spacing, tolerances) that the skill contracts expect.
        """
        decision = self._pending

        if decision is None:
            return self.fallback.choose_skill(belief, objective)

        name = decision.tool_name

        if name == "go_to_waypoint":
            return self._waypoint_command(belief, decision)

        if name == "hold":
            duration = decision.parameters.get("duration_s", 5.0)
            return sk.HoldPositionCommand(duration_s=float(duration))

        if name == "act_as_relay":
            return self._relay_command(belief)

        # everything else defers to the deterministic command builder
        return self.fallback.choose_skill(belief, objective)

    # --- the model call ---

    def _decide(self, belief):
        """One model call, one optional correction. Returns (turn, decision|None)."""
        ctx = context_builder.build(
            belief, step=self.step, task=belief.task, messages=self._inbox,
            last_result=self.last_result, allocator=self.allocator,
            safety_limits=self.safety_limits, capabilities=self.capabilities)
        system = context_builder.SYSTEM_PROMPT
        user = self._with_memory(ctx.to_prompt())

        turn = LLMTurn(step=self.step, time_s=belief.now,
                       vehicle_id=self.vehicle_id,
                       system_prompt=system, user_prompt=user)

        peers = set(belief.team.teammates) | {belief.vehicle_id}
        schema = response_schema() if self.use_schema else None

        raw, err = self._ask(system, user, schema, turn)
        if err is None:
            try:
                decision = parse_decision(raw, known_peers=peers)
                self._fill(turn, decision)
                return turn, decision
            except DecisionError as e:
                err = e

        # --- 12.6.1: one structured correction, when it can help ---
        correctable = (self.allow_correction and isinstance(err, DecisionError)
                       and err.reason.correctable)
        turn.rejection_reason = getattr(err, "reason",
                                        RejectionReason.BACKEND_ERROR).value
        turn.rejection_detail = str(err)

        if correctable:
            turn.attempts = 2
            corrected_user = (user + "\n\n"
                              + context_builder.correction_prompt(err.hint))
            raw2, err2 = self._ask(system, corrected_user, schema, turn)
            if err2 is None:
                try:
                    decision = parse_decision(raw2, known_peers=peers)
                    self._fill(turn, decision)
                    turn.corrected = True
                    return turn, decision
                except DecisionError as e2:
                    err2 = e2
            turn.rejection_detail = (f"{turn.rejection_detail} | after correction: "
                                     f"{err2}")

        # --- 12.6.2: the deterministic policy takes over ---
        turn.used_fallback = True
        turn.fallback_cause = turn.rejection_reason
        return turn, None

    def _ask(self, system, user, schema, turn):
        """Call the backend under its timeout. Returns (text, error)."""
        started = time.monotonic()
        try:
            raw = call_with_timeout(self.backend, system, user,
                                    self.timeout_s, schema=schema)
            turn.latency_s += time.monotonic() - started
            turn.raw_response = raw if turn.raw_response is None else turn.raw_response
            return raw, None
        except BackendTimeout as e:
            turn.latency_s += time.monotonic() - started
            return None, DecisionError(RejectionReason.TIMEOUT, str(e))
        except BackendError as e:
            turn.latency_s += time.monotonic() - started
            return None, DecisionError(RejectionReason.BACKEND_ERROR, str(e))
        except Exception as e:                                   # noqa: BLE001
            # A backend that raises something unexpected must not take the
            # aircraft down with it. Fall through to the deterministic policy.
            turn.latency_s += time.monotonic() - started
            return None, DecisionError(RejectionReason.BACKEND_ERROR,
                                       f"{type(e).__name__}: {e}")

    def _fill(self, turn, decision):
        turn.parsed = decision.as_dict()
        turn.tool = decision.tool_name
        turn.reason_code = decision.reason_code
        turn.confidence = decision.confidence
        turn.assessment = decision.assessment.as_dict()

    # --- memory (12.1: each agent keeps its own) ---

    def _remember(self, turn, objective):
        self.memory.append({"step": turn.step, "tool": turn.tool,
                            "reason_code": turn.reason_code,
                            "objective": objective.value})
        self.memory = self.memory[-self.memory_turns:]

    def _with_memory(self, prompt):
        if not self.memory:
            return prompt
        import json
        return (prompt + "\n\nYour recent decisions (most recent last):\n"
                + json.dumps(self.memory, default=str))

    # --- command builders for model-chosen tools ---

    def _waypoint_command(self, belief, decision):
        """The one place model-supplied coordinates enter the system.

        They are bounded by the tool schema, then checked by `route_feasible`,
        then checked again by the guardian. Three layers for one number, which
        is proportionate: this is the single value a model can write that moves
        an aircraft.
        """
        p = decision.parameters
        z = p.get("z", belief.cruise_altitude)
        target = Position3D(float(p["x"]), float(p["y"]), float(z))
        speed = float(p.get("speed_mps", 4.0))
        return sk.GoToWaypointCommand(waypoint=target, speed_mps=speed,
                                      tolerance_m=1.5, timeout_s=600.0)

    def _relay_command(self, belief):
        """Hold a position between the team and base.

        Deterministic: the midpoint between this drone and home, at cruise
        altitude. The model decides *that* relaying is the right call; where to
        sit to relay is geometry, and geometry is not the model's job (12.5).
        """
        here, home = belief.position, belief.home
        mid = Position3D((here.x + home.x) / 2.0, (here.y + home.y) / 2.0,
                         belief.cruise_altitude)
        if here.horizontal_distance_to(mid) < 2.0:
            return sk.HoldPositionCommand(duration_s=10.0)
        return sk.GoToWaypointCommand(waypoint=mid, speed_mps=4.0,
                                      tolerance_m=2.0, timeout_s=300.0)

    # --- helpers ---

    def _fallback_objective(self, belief, cause):
        objective = self.fallback.next_objective(belief)
        turn = LLMTurn(step=self.step, time_s=belief.now,
                       vehicle_id=self.vehicle_id, system_prompt="", user_prompt="",
                       used_fallback=True, fallback_cause=cause,
                       fallback_objective=objective.value,
                       outcome="deterministic policy retained control")
        self.log.record(turn)
        self._pending = None
        return objective

    # anything the agent asks for that this policy does not define
    def __getattr__(self, item):
        return getattr(self.__dict__.get("fallback") or SearchAgentPolicy(), item)

    # --- reporting ---

    def stats(self):
        return self.log.stats()

    def model_card(self) -> Optional[ModelCard]:
        return self.log.model_card
