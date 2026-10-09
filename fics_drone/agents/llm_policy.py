"""The LLM goes in the policy slot, not the control path. LLMAgentPolicy
implements the same one method as SearchAgentPolicy - decide(belief, event) ->
(Objective, next_phase) - so PersistentAgent, the allocator, the message bus
and the Phase 11 SafetyGuardian are completely unchanged and none of them
know a model exists. Everything that made the deterministic system safe still
sits downstream of the model.

The model owns ONE decision point, chosen by a rule: it decides only when
both answers are safe and the choice cannot loop forever or strand a drone.
After an agent has finished its own sector and lingered at least one round, it
picks from a menu of the fifteen tools in llm_tools.py - but only the ones the
CODE offers right now (offered_tools(): preconditions, valid task ids, known
recipients, a hard cap on model actions). Everything else - take-off, climbing,
search legs, retries, low battery, landing, "mission over" - is a FACT, decided
by the deterministic policy.

One tool, go_to_waypoint, carries model-supplied coordinates (world x, y;
altitude stays code-owned). It is the only way model output can ever name a
position, it consumes one of the same code-capped rounds as holding, and the
flight it triggers goes through the SafetyGuardian like every other command -
this is what gives the guardian something real to catch from a model.

Every failure path flies the aircraft: one correction for a correctable
rejection, none for a timeout, then the deterministic policy decides and the
event is recorded. Fallback is the design, not error handling.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .belief import Belief
from .context_builder import build_prompt
from .decision_schema import (CORRECTABLE, Decision, DecisionRejected, RejectionKind,
                              parse_decision)
from .llm_backends import BackendError, BackendTimeout, ModelBackend
from .llm_tools import MAX_MODEL_ACTIONS, offered_tools
from .objectives import Objective, ReplanEvent
from .reasoning_tools import ReasoningTools
from .search_policy import SearchAgentPolicy

DEFAULT_TIMEOUT_S = 20.0
ASSIST_MODES = ("off", "context", "repair")

# What each model-chosen objective means as the agent's next phase.
OBJECTIVE_PHASE = {
    Objective.LISTEN: "listening",
    Objective.RETURN_HOME: "returning",
    Objective.GO_TO_WAYPOINT: "repositioning",
    Objective.SEARCH_SECTOR: "searching",
    Objective.REPORT: "reporting",
    Objective.TOOL_ACTION: "coordinating",
}


@dataclass
class LLMDecisionRecord:
    step: int
    source: str                      # "model" | "fallback"
    objective: Objective
    reason_code: Optional[str] = None
    tool: Optional[str] = None                       # which of the 15 tools the model selected
    args: Dict[str, object] = field(default_factory=dict)   # its validated tool parameters
    waypoint: Optional[Tuple[float, float]] = None   # world (x, y) actually FLOWN, only for go_to_waypoint
    raw_waypoint: Optional[Tuple[float, float]] = None   # what the model asked for (differs only if repaired)
    repaired: bool = False
    repair_distance_m: Optional[float] = None
    assessment: Optional[Dict[str, str]] = None      # Phase 12.3: the model's own three-enum read of the situation
    confidence: Optional[float] = None               # its self-reported 0..1 confidence; logged, never trusted
    messages: List[dict] = field(default_factory=list)   # validated outgoing messages it asked to send
    rejected_as: Optional[str] = None   # RejectionKind value of the FIRST rejection, if any
    corrected: bool = False             # a rejection was fixed by the one correction
    prompts: List[str] = field(default_factory=list)
    raw_outputs: List[str] = field(default_factory=list)


class LLMAgentPolicy:
    def __init__(self, backend: ModelBackend, fallback: Optional[SearchAgentPolicy] = None,
                 timeout_s: float = DEFAULT_TIMEOUT_S, sectors: Sequence = (),
                 spawn_offset: Tuple[float, float, float] = (0.0, 0.0, 0.0),
                 waypoints_enabled: bool = True, assist: str = "off",
                 tools: Optional[ReasoningTools] = None, max_model_actions: int = MAX_MODEL_ACTIONS,
                 zones: Sequence = (), show_zones: bool = False):
        if assist not in ASSIST_MODES:
            raise ValueError(f"assist must be one of {ASSIST_MODES}, got {assist!r}")
        if assist != "off" and tools is None:
            raise ValueError(f"assist={assist!r} needs ReasoningTools")
        self.assist = assist     # off | context (show pre-computed facts) | repair (snap to nearest legal point)
        self.tools = tools
        self.backend = backend
        self.fallback = fallback or SearchAgentPolicy()
        self.timeout_s = timeout_s
        self.sectors = tuple(sectors)           # mission geometry shown in the prompt (no target locations)
        self.spawn_offset = spawn_offset        # this agent's own local->world offset, for the prompt
        self.waypoints_enabled = waypoints_enabled
        # GMB: the scenario's no-fly zones, shown in the prompt (as they are right now) only if show_zones.
        self.zones = tuple(zones)
        self.show_zones = show_zones
        self.max_model_actions = max_model_actions
        self._pending_waypoint: Optional[Tuple[float, float]] = None
        self._pending_action: Optional[Tuple[str, dict]] = None
        self._pending_messages: Tuple = ()
        self.records: List[LLMDecisionRecord] = []   # THIS agent's own history only
        self._step = 0

    # --- the one method PersistentAgent calls ---
    def _zone_lines(self, belief):
        if not self.show_zones:
            return ()
        t = belief.elapsed_s
        lines = []
        for z in self.zones:
            if z.active_at(t):
                x0, x1, y0, y1 = z.bounds_at(t)
                moving = f", moving ({z.vx:+g}, {z.vy:+g}) m/s" if (z.vx or z.vy) else ""
                lines.append(f"- {z.id}: x {x0:.0f}..{x1:.0f}, y {y0:.0f}..{y1:.0f}{moving}")
        return lines

    def decide(self, belief: Belief, event: ReplanEvent) -> Tuple[Objective, str]:
        deterministic = self.fallback.decide(belief, event)
        if not self._is_model_decision_point(belief, event):
            return deterministic

        self._step += 1
        offered = self._offered(belief)
        record = LLMDecisionRecord(step=self._step, source="model", objective=deterministic[0])
        decision = self._ask(belief, event, offered, record)
        if decision is None:
            record.source = "fallback"
            record.objective = deterministic[0]
            self.records.append(record)
            return deterministic

        record.objective, record.reason_code = decision.objective, decision.reason_code
        record.tool, record.args = decision.tool, dict(decision.args)
        self._pending_action = (decision.tool, {**decision.args, "reason_code": decision.reason_code})
        # (only a MODEL decision ever carries an action; a fallback decision never does)
        record.assessment = {"mission_progress": decision.assessment.mission_progress,
                             "communication_status": decision.assessment.communication_status,
                             "current_risk": decision.assessment.current_risk}
        record.confidence = decision.confidence
        record.messages = [{"message_type": m.type.value, "recipients": list(m.recipients),
                            "payload": dict(m.payload)} for m in decision.messages]
        self._pending_messages = decision.messages   # only a MODEL decision ever carries messages
        record.raw_waypoint = decision.waypoint
        flown = decision.waypoint
        if flown is not None and self.assist == "repair":
            # The model's raw point is kept in the record; what gets FLOWN is the nearest point the
            # guardian would accept. If none exists nearby, the raw point goes through and the
            # guardian blocks it - honest, rather than inventing somewhere to fly.
            repaired = self.tools.nearest_legal_point(belief, flown)
            if repaired is not None and repaired != flown:
                record.repaired = True
                record.repair_distance_m = self.tools.distance(flown, repaired)
                flown = repaired
        record.waypoint = flown
        self._pending_waypoint = flown
        self.records.append(record)
        return decision.objective, OBJECTIVE_PHASE[decision.objective]

    def take_waypoint(self) -> Optional[Tuple[float, float]]:
        """Hand the agent the coordinates of the decision just made (world x, y), once.
        Kept out of decide()'s return value so the one-method policy interface that
        SearchAgentPolicy defines doesn't change shape for the deterministic case."""
        waypoint, self._pending_waypoint = self._pending_waypoint, None
        return waypoint

    def take_action(self) -> Optional[Tuple[str, dict]]:
        """Hand the agent (tool name, validated args) for the model decision just made, once. None for
        a fallback decision: if the model's answer was rejected, nothing it asked for happens."""
        action, self._pending_action = self._pending_action, None
        return action

    def take_messages(self) -> Tuple:
        """Hand the agent the validated messages the model asked to send, once. A fallback decision
        never has any: if the model's answer was rejected, nothing it wrote leaves the agent."""
        messages, self._pending_messages = self._pending_messages, ()
        return messages

    # --- what the model is and is not allowed to decide ---
    def _is_model_decision_point(self, belief: Belief, event: ReplanEvent) -> bool:
        if belief.phase not in ("listening", "repositioning", "coordinating"):
            return False
        if event in (ReplanEvent.SKILL_FAILED, ReplanEvent.TARGET_DETECTED):
            return False                                  # facts, not judgments
        if belief.battery_frac_remaining <= self.fallback.low_battery_frac:
            return False                                  # low battery is a fact, never delegated
        return True

    def _offered(self, belief: Belief):
        """The menu, owned by code: which of the fifteen tools are legal right now, and the values each
        parameter may take. A hard cap on model actions guarantees the model cannot loop."""
        return offered_tools(belief, listen_cap=self.fallback.listen_rounds,
                             max_actions=self.max_model_actions, waypoints_enabled=self.waypoints_enabled)

    # --- one turn: ask, validate, correct once if worthwhile, else give up (-> fallback) ---
    def _ask(self, belief: Belief, event: ReplanEvent, offered,
             record: LLMDecisionRecord) -> Optional[Decision]:
        correction = None
        for attempt in (1, 2):
            checked = (self.tools.checked_points(belief)
                       if self.assist == "context" and "go_to_waypoint" in offered else ())
            prompt = build_prompt(belief, event, offered, self.fallback.listen_rounds, correction,
                                  sectors=self.sectors, spawn_offset=self.spawn_offset,
                                  checked_points=checked, active_zones=self._zone_lines(belief))
            record.prompts.append(prompt)
            try:
                raw = self.backend.complete(prompt, self.timeout_s)
                record.raw_outputs.append(raw)
                decision = parse_decision(raw, offered, list(belief.team.teammates))
                record.corrected = attempt == 2
                return decision
            except BackendTimeout:
                rejection = DecisionRejected(RejectionKind.TIMEOUT, f"no answer in {self.timeout_s}s")
            except BackendError as exc:
                rejection = DecisionRejected(RejectionKind.BACKEND_ERROR, str(exc))
            except DecisionRejected as exc:
                rejection = exc

            if record.rejected_as is None:
                record.rejected_as = rejection.kind.value
            if attempt == 2 or rejection.kind not in CORRECTABLE:
                return None
            correction = rejection.detail
        return None

    # --- the number to watch ---
    @property
    def fallback_rate(self) -> float:
        """Share of model-owned decisions the deterministic policy ended up making.
        How much of a reported 'LLM agent' result is the rule agent in a costume."""
        if not self.records:
            return 0.0
        return sum(1 for r in self.records if r.source == "fallback") / len(self.records)


def make_policy_factory(backend: ModelBackend, scenario, **kwargs):
    """One policy per drone over ONE shared backend: identity, belief and decision
    history stay per-agent; only the model process is shared. Returns the factory
    run_team_with_faults() wants, plus the dict it fills in (name -> policy)."""
    offsets = {d.name: d.spawn_offset for d in scenario.drones}
    policies = {}

    def factory(name):
        offset = offsets.get(name, (0.0, 0.0, 0.0))
        extra = {}
        if kwargs.get("assist", "off") != "off":
            extra["tools"] = ReasoningTools(scenario, spawn_offset=offset)   # each drone: its own tools + guardian
        policies[name] = LLMAgentPolicy(backend, sectors=scenario.sectors, spawn_offset=offset,
                                        **kwargs, **extra)
        return policies[name]

    return factory, policies
