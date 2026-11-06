"""An LLM as one drone's persistent mission-level policy (AUV-12, Phase 12).

    policy = LLMPolicy(RecoveryPolicy(...), ask)      # ask: the model, injected -- Ollama, echo or replay
    agent = DroneAgent(..., policy, coordinator=policy.inner)
    policy.log                                        # every decision: who made it, the context, the reply

THE SPLIT (plan, recommendation 2). The rule team's policy (Phase 9's
`RecoveryPolicy`) stays the drone's PROTOCOL and its PROCEDURE: it runs the
contract-net, the failure ladder and the roles every tick, as coordinator, and
it handles what is procedure, not choice -- the take-off when the team mission
is given, bookkeeping when a search ends, retries after a failed skill, the way
home and the landing once begun, anything on the ground. Every other decision
-- what to do next, in the air, on a message, a sighting, a link change, the
periodic check, a refusal of its own last choice -- is the MODEL's, through the
tools (`llm_tools`), which run on the rule policy's own primitives.

EACH DECISION THE MODEL MAKES:

  1. what the rule policy would choose is worked out on COPIES of its state and
     the belief (nothing it does there is kept): it is the echo model's answer,
     and how often the model agrees with it is measured;
  2. the drone's context is built from its own belief and policy only
     (`llm_context`): this is its distinct, persistent agent context (12.1);
  3. the model is asked (`ask`) -- once; if its reply cannot be used (malformed,
     not a tool, not possible now) it is told why and asked ONCE more (12.6);
  4. still unusable, or no reply at all (a timeout, the server gone): the rule
     policy decides, and the fallback is recorded with why (12.6);
  5. usable: if it is the rule's own choice, the rule policy's decision is taken
     -- the same path, so the echo model flies the rule team's flight exactly;
     otherwise the tool is executed on the rule policy's primitives.

Whatever it decides then goes to the agent loop, and through the guardian
(Phase 11): a refusal comes back as GUARD_REJECTED, and the model is asked
again with the guardian's reasons in its context.

THE LOG (12.7: "save all prompts and structured outputs"): every decision --
procedural, the model's, corrected, fallen back -- with the context, a digest of
the exact messages sent, every raw reply, the tool, the rule's tool, whether
they agree, the problems found, and how long the model took.

What the model is told is this drone's own: its belief, its policy, its memory.
Nothing here reads another drone's state; the boundary test holds this module
to the agents' rules.
"""

from __future__ import annotations

import copy
import hashlib
import json
import time
from typing import Any, Callable

from ..core.events import Event, Trigger
from .belief_state import BeliefState
from .decision import Decision
from .llm_context import build_context, render
from .llm_tools import check, execute, parse_reply, reply_for, rule_tool
from .rule_policy import Stage

CORRECTIONS = 1                     # 12.6: one structured correction, then the fallback
PROCEDURE_TRIGGERS = (Trigger.TASK_ASSIGNED, Trigger.SKILL_FAILED, Trigger.SKILL_ABORTED)
PROCEDURE_STAGES = (Stage.TAKING_OFF, Stage.GOING_HOME, Stage.LANDING, Stage.DONE)


def digest(messages: list[dict[str, str]]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode("utf-8")).hexdigest()[:16]


class LLMPolicy:
    def __init__(self, inner: Any, ask: Callable[[dict[str, Any]], str], clock: Callable[[], float] = time.perf_counter,
                 memory: bool = True) -> None:
        self.inner = inner                  # the rule policy: protocol, procedure, primitives, fallback
        self.ask = ask
        self.remember = memory              # Phase 13's ablation: off, its context never holds its own past decisions
        self._clock = clock                 # wall clock, for latency only -- never in a decision
        self.log: list[dict[str, Any]] = []
        self.memory: list[dict[str, Any]] = []
        self._last: tuple[float, str] | None = None     # (when, who) the last decision was made

    # -------------------------------------------------------------- decide

    def decide(self, belief: BeliefState, events: tuple[Event, ...]) -> Decision:
        now = belief.self_.updated_at
        if self._procedural(belief, events, now):
            decision = self.inner.decide(belief, events)
            self._record(now, "procedural", events, decision)
            return decision
        shadow = copy.deepcopy(self.inner)
        rule = shadow.decide(copy.deepcopy(belief), events)
        rule_choice = rule_tool(rule, shadow)
        context = build_context(belief, self.inner, events, self.memory)    # empty when memory is off: see below
        messages = render(context)
        replies, problems, latencies, tool, params, parsed = [], [], [], None, {}, {}
        for attempt in range(CORRECTIONS + 1):
            started = self._clock()
            try:
                raw = self.ask({"messages": messages, "meta": {"rule_reply": reply_for(*rule_choice),
                                                               "drone": belief.self_.vehicle_id}})
            except Exception as exc:          # no reply at all: a timeout, the server gone -- recorded, then fallback
                latencies.append(round(self._clock() - started, 3))
                problems = [f"no reply: {exc!r}"]
                break
            latencies.append(round(self._clock() - started, 3))
            replies.append(raw)
            tool, params, problems = parse_reply(raw)
            if not problems and tool is not None:
                problems = check(tool, params, self.inner, belief)
            if not problems:
                parsed = json.loads(raw)
                break
            if attempt < CORRECTIONS:
                messages = messages + [{"role": "assistant", "content": raw},
                                       {"role": "user", "content": "That answer cannot be used: " + "; ".join(problems)
                                        + ". Answer again with one JSON object, choosing from \"actions\"."}]
        if problems:
            decision = self.inner.decide(belief, events)
            self._record(now, "fallback", events, decision, context, messages, replies, latencies, None, {},
                         rule_choice, problems)
            return decision
        reason = f"LLM {parsed.get('reason_code', '')}".strip()
        if (tool, params) == rule_choice or (tool == rule_choice[0] and _same(params, rule_choice[1])):
            decision = self.inner.decide(belief, events)          # the rule's own path: exactly its decision
        else:
            decision = execute(tool, params, self.inner, belief, reason)
            self._after(belief)
        kind = "llm" if len(replies) == 1 else "corrected"
        self._record(now, kind, events, decision, context, messages, replies, latencies, tool, params, rule_choice,
                     [], parsed)
        if self.remember:
            self.memory.append({"at": now, "tool": tool, "parameters": params,
                                "reason_code": parsed.get("reason_code", "")})
        return decision

    def _procedural(self, belief: BeliefState, events: tuple[Event, ...], now: float) -> bool:
        triggers = {e.trigger for e in events}
        if Trigger.GUARD_REJECTED in triggers:
            # The model's own choice refused: it chooses again, with the reasons. The rule's, procedure.
            return not (self._last is not None and abs(self._last[0] - now) < 1e-9 and self._last[1] != "procedural")
        if triggers & set(PROCEDURE_TRIGGERS) or not belief.self_.airborne:
            return True
        if self.inner.stage in PROCEDURE_STAGES and not self.inner.waiting:
            return True
        if Trigger.SKILL_SUCCEEDED in triggers and self.inner.stage is Stage.SEARCHING:
            return True                       # a search done: its bookkeeping is the protocol's
        return False

    def _after(self, belief: BeliefState) -> None:
        """What the rule policy's own `decide` does after choosing, for a choice made by a tool."""
        inner = self.inner
        if inner.sector is not None and inner.stage is not Stage.DONE:
            inner._assume_teammates(belief)
        progress = belief.mission.progress
        progress.update(stage=inner.stage.value, sector=None if inner.sector is None else inner.sector.id,
                        retries=inner.retries)
        if inner.gave_up:
            progress["gave_up"] = inner.gave_up
        if inner.waiting:
            progress["stage"] = "waiting"
        progress["task"] = inner.task_id

    # ------------------------------------------------------------- the log

    def _record(self, now: float, kind: str, events: tuple[Event, ...], decision: Decision,
                context: dict[str, Any] | None = None, messages: list[dict[str, str]] | None = None,
                replies: list[str] | None = None, latencies: list[float] | None = None, tool: str | None = None,
                params: dict[str, Any] | None = None, rule_choice: tuple[str, dict[str, Any]] | None = None,
                problems: list[str] | None = None, parsed: dict[str, Any] | None = None) -> None:
        self._last = (now, kind)
        entry: dict[str, Any] = {"at": round(now, 3), "kind": kind, "events": [e.trigger.value for e in events],
                                 "decision": decision.as_json()}
        if kind != "procedural":
            entry.update(context=context, prompt_digest=digest(messages or []), replies=replies or [],
                         latency_s=latencies or [], tool=tool, parameters=params or {},
                         rule={"tool": rule_choice[0], "parameters": rule_choice[1]} if rule_choice else None,
                         agreed=tool is not None and rule_choice is not None and tool == rule_choice[0]
                         and _same(params or {}, rule_choice[1]),
                         problems=problems or [])
            if parsed:
                entry.update(assessment=parsed.get("situation_assessment"), confidence=parsed.get("confidence"),
                             reason_code=parsed.get("reason_code"), outgoing_messages=parsed.get("outgoing_messages"))
        self.log.append(entry)

    def as_json(self) -> dict[str, Any]:
        kinds: dict[str, int] = {}
        for e in self.log:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
        return {"decisions": kinds, "agreed": sum(1 for e in self.log if e.get("agreed")), "log": self.log}


def _same(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Parameters equal, numbers compared as numbers (a reply's 10 is the rule's 10.0)."""
    if a.keys() != b.keys():
        return False
    for k in a:
        x, y = a[k], b[k]
        if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool):
            if float(x) != float(y):
                return False
        elif x != y:
            return False
    return True
