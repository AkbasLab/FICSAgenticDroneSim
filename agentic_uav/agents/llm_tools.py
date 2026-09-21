"""The only actions an LLM agent may take (Phase 12.2).

The model does not write code. It does not call AirSim. It does not emit
waypoints of its own invention into the executor. It selects **one tool by
name** from this registry and supplies parameters that are checked against a
declared schema before anything happens.

This is the difference between "an LLM flying a drone" and "an LLM choosing
among vetted actions". Everything downstream — the guardian, the allocator, the
skill contracts — was built assuming commands are well-formed. A free-form model
would violate that assumption on its first hallucination. A closed tool set means
the worst a model can do is pick the wrong legal action, which is a research
result rather than a crash.

Two kinds of tool:

  * FLIGHT tools become a `SkillCommand` and go through the Phase 11 guardian
    exactly like any deterministic command. The guardian does not know or care
    that an LLM proposed them.
  * COORDINATION tools act on the agent's own belief, task board or role. They
    never touch the vehicle, so they are validated here rather than by the
    guardian.

Adding a tool means adding a schema entry here and a handler in
`llm_policy.py`. A tool without both is unreachable by construction.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# --- parameter types ------------------------------------------------------


class ParamError(ValueError):
    """A tool call whose parameters do not match the declared schema."""


@dataclass(frozen=True)
class Param:
    """One declared parameter.

    `kind` is deliberately a small closed vocabulary rather than arbitrary
    Python types: it is what gets rendered into the prompt, so it has to be
    something a model can read as well as something the code can enforce.
    """
    name: str
    kind: str                       # "string" | "number" | "integer" | "bool" | "id"
    required: bool = True
    choices: Optional[Tuple[str, ...]] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    description: str = ""

    def coerce(self, value):
        """Return the value in its proper type, or raise ParamError.

        Coercion is permitted where it is unambiguous (the string "4.0" for a
        number, because JSON from a model routinely quotes numbers). It is not
        permitted where it would paper over a real mistake: a bool is never
        accepted as a number, because `True` silently becoming `1.0` is how a
        nonsense altitude reaches a vehicle.
        """
        if isinstance(value, bool) and self.kind != "bool":
            raise ParamError(f"{self.name}: expected {self.kind}, got a boolean")

        if self.kind in ("number", "integer"):
            try:
                out = float(value)
            except (TypeError, ValueError):
                raise ParamError(f"{self.name}: expected a number, got {value!r}")
            if out != out or out in (float("inf"), float("-inf")):
                raise ParamError(f"{self.name}: {value!r} is not a finite number")
            if self.kind == "integer":
                if abs(out - round(out)) > 1e-9:
                    raise ParamError(f"{self.name}: expected an integer, got {value!r}")
                out = int(round(out))
            if self.minimum is not None and out < self.minimum:
                raise ParamError(f"{self.name}: {out} below the minimum {self.minimum}")
            if self.maximum is not None and out > self.maximum:
                raise ParamError(f"{self.name}: {out} above the maximum {self.maximum}")
            return out

        if self.kind == "bool":
            if isinstance(value, bool):
                return value
            raise ParamError(f"{self.name}: expected true or false, got {value!r}")

        # string / id
        if not isinstance(value, str):
            raise ParamError(f"{self.name}: expected a string, got {value!r}")
        out = value.strip()
        if not out:
            raise ParamError(f"{self.name}: must not be empty")
        if self.choices is not None and out not in self.choices:
            raise ParamError(f"{self.name}: {out!r} is not one of "
                             f"{', '.join(self.choices)}")
        return out


# --- tools ----------------------------------------------------------------

FLIGHT = "flight"
COORDINATION = "coordination"


@dataclass(frozen=True)
class Tool:
    name: str
    category: str
    purpose: str
    params: Tuple[Param, ...] = ()

    def validate(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Check a parameter dict against this tool's schema.

        Unknown parameters are an error rather than something to ignore. A model
        that invents `altitude_m` when the tool takes `altitude` has
        misunderstood the tool, and silently dropping the extra key would
        execute a command the model did not intend.
        """
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ParamError(f"parameters must be an object, got {type(raw).__name__}")

        declared = {p.name for p in self.params}
        unknown = set(raw) - declared
        if unknown:
            raise ParamError(f"{self.name}: unknown parameter(s) "
                             f"{', '.join(sorted(unknown))}; "
                             f"accepts {', '.join(sorted(declared)) or 'nothing'}")

        out = {}
        for p in self.params:
            if p.name not in raw or raw[p.name] is None:
                if p.required:
                    raise ParamError(f"{self.name}: missing required parameter "
                                     f"{p.name!r}")
                continue
            out[p.name] = p.coerce(raw[p.name])
        return out

    def signature(self) -> str:
        """One line, for the prompt. This is the model's entire API reference."""
        if not self.params:
            return f"{self.name}()  — {self.purpose}"
        parts = []
        for p in self.params:
            s = f"{p.name}:{p.kind}"
            if p.choices:
                s += "(" + "|".join(p.choices) + ")"
            if not p.required:
                s += "?"
            parts.append(s)
        return f"{self.name}({', '.join(parts)})  — {self.purpose}"


ROLE_CHOICES = ("searcher", "relay", "idle")

#: Reason codes. A short code rather than free prose, so that decisions are
#: groupable and countable across a whole experiment — "how often did agents
#: change role because the base link dropped" is a question you can only answer
#: if the answer is an enum. `OTHER` exists so the model is never forced to lie.
REASON_CODES = (
    "BASE_LINK_LOST", "PEER_UNREACHABLE", "TASK_COMPLETE", "TASK_INFEASIBLE",
    "LOW_BATTERY", "BETTER_BID_EXISTS", "NO_WORK_REMAINING", "TARGET_FOUND",
    "COVERAGE_GAP", "SAFETY_CONCERN", "TEAM_REQUEST", "OTHER",
)

TOOLS: Tuple[Tool, ...] = (
    # --- task lifecycle ---
    Tool("accept_task", COORDINATION,
         "take on a task that has been offered or awarded to this drone",
         (Param("task_id", "id", description="the task being accepted"),
          Param("reason_code", "string", required=False, choices=REASON_CODES))),
    Tool("decline_task", COORDINATION,
         "refuse a task this drone should not take",
         (Param("task_id", "id"),
          Param("reason_code", "string", choices=REASON_CODES))),
    Tool("compute_task_cost", COORDINATION,
         "ask the deterministic cost model what a task would cost this drone",
         (Param("task_id", "id"),)),
    Tool("announce_task", COORDINATION,
         "tell the team about a task that needs doing",
         (Param("task_id", "id"),
          Param("reason_code", "string", required=False, choices=REASON_CODES))),
    Tool("send_bid", COORDINATION,
         "bid for an open task; the cost is computed, never chosen by the model",
         (Param("task_id", "id"),)),
    Tool("claim_task", COORDINATION,
         "claim a task this drone has won",
         (Param("task_id", "id"),)),
    Tool("release_task", COORDINATION,
         "give up the current task so another drone can take it",
         (Param("task_id", "id"),
          Param("reason_code", "string", choices=REASON_CODES))),

    # --- team ---
    Tool("change_role", COORDINATION,
         "change this drone's role in the team",
         (Param("new_role", "string", choices=ROLE_CHOICES),
          Param("reason_code", "string", choices=REASON_CODES))),
    Tool("request_help", COORDINATION,
         "ask the team for assistance",
         (Param("reason_code", "string", choices=REASON_CODES),
          Param("task_id", "id", required=False))),
    Tool("report_target", COORDINATION,
         "report a target this drone has detected",
         (Param("target_id", "id"),)),

    # --- flight ---
    Tool("start_search", FLIGHT,
         "fly the sweep for the currently held search task"),
    Tool("go_to_waypoint", FLIGHT,
         "fly to a point inside the operating area",
         (Param("x", "number", minimum=-1000.0, maximum=1000.0),
          Param("y", "number", minimum=-1000.0, maximum=1000.0),
          Param("z", "number", required=False, minimum=-200.0, maximum=0.0,
                description="altitude, NEGATIVE is up; omit for cruise altitude"),
          Param("speed_mps", "number", required=False,
                minimum=0.1, maximum=30.0))),
    Tool("act_as_relay", FLIGHT,
         "hold a position that keeps the team in contact with base",
         (Param("reason_code", "string", required=False, choices=REASON_CODES),)),
    Tool("return_home", FLIGHT, "fly back to base at cruise altitude"),
    Tool("hold", FLIGHT, "stay where you are for a bounded time",
         (Param("duration_s", "number", required=False,
                minimum=1.0, maximum=120.0),)),
)

BY_NAME: Dict[str, Tool] = {t.name: t for t in TOOLS}
TOOL_NAMES: Tuple[str, ...] = tuple(t.name for t in TOOLS)


def get(name) -> Tool:
    """Look up a tool, with an error a model can actually act on."""
    if not isinstance(name, str):
        raise ParamError(f"selected_tool must be a string, got {name!r}")
    tool = BY_NAME.get(name.strip())
    if tool is None:
        raise ParamError(f"{name!r} is not an available tool; choose one of: "
                         + ", ".join(TOOL_NAMES))
    return tool


def validate_call(name, parameters) -> Tuple[Tool, Dict[str, Any]]:
    """Resolve a tool by name and check its parameters. Raises ParamError."""
    tool = get(name)
    return tool, tool.validate(parameters)


def catalogue(categories=None) -> str:
    """The tool list as it appears in the prompt."""
    lines = []
    for t in TOOLS:
        if categories and t.category not in categories:
            continue
        lines.append("  " + t.signature())
    return "\n".join(lines)


def flight_tools() -> Tuple[str, ...]:
    return tuple(t.name for t in TOOLS if t.category == FLIGHT)


def coordination_tools() -> Tuple[str, ...]:
    return tuple(t.name for t in TOOLS if t.category == COORDINATION)
