"""A decision as text and back: the channel an LLM's answer comes through (Phase 11; Phase 12's interface).

    text = render_proposal(decision)                 # how a well-behaved model writes a decision
    decision = parse_proposal(text, issued_at=t)     # a Decision -- or Decision.invalid(text, problems)

AUV-11: "The LLM may propose actions. It must not directly control unsafe
behaviour." From Phase 12 a model's answer is text, and text can be anything:
not JSON, JSON of the wrong shape, a skill that does not exist, NaN, a number
written as a word, two commands at once. Nothing here raises. Whatever the
text, the answer is a `Decision`: the one it states, if it states one
exactly, or an INVALID decision carrying the text and every problem found,
which the guardian refuses ("reject and replan") like any unsafe command. A
valid decision is not thereby safe: it goes on to the guardian's checks.

THE FORMAT, one JSON object:

    {"decision": "start", "skill": "GO_TO_WAYPOINT",
     "parameters": {"waypoint": {"x": 80, "y": -40, "altitude_m": 12}, "speed_mps": 5},
     "objective": "reach S1", "reason": "..."}
    {"decision": "continue" | "abort" | "finish", "objective": "...", "reason": "..."}

`parameters` are the skill command's own fields (`control.skills`), by name;
a point is {"x", "y", "altitude_m"}, a region {"x_min", "y_min", "x_max",
"y_max"}, a list of points a JSON array. Omitted parameters take the skill's
defaults. Nothing else is allowed: an unknown key is a problem, not ignored,
so a model cannot slip in a field the reader would silently drop.

PROBLEMS are "[check] what", naming the guardian check they belong to:
"[conflict]" for more than one command in one answer, "[proposal]" for the
rest. `render_proposal` then `parse_proposal` gives back the same decision
(tested over every command the rule policies issue).
"""

from __future__ import annotations

import json
import math
from dataclasses import fields
from typing import Any

from ..control import navigation as nav
from ..control.skills import CONTRACTS, SkillName, command_json
from ..core.geometry import Polygon, Region
from .decision import Decision, DecisionKind

TOP_KEYS = ("decision", "skill", "parameters", "objective", "reason")
KINDS = {k.value: k for k in DecisionKind if k is not DecisionKind.INVALID}
POINT_KEYS = ("x", "y", "altitude_m")
REGION_KEYS = ("x_min", "y_min", "x_max", "y_max")
POINT_FIELDS = ("waypoint", "target")


def render_proposal(decision: Decision) -> str:
    """The decision as the channel's JSON, keys sorted."""
    out: dict[str, Any] = {"decision": decision.kind.value, "objective": decision.objective,
                           "reason": decision.reason}
    if decision.command is not None:
        cmd = decision.command
        out["skill"] = cmd.skill.value
        out["parameters"] = command_json(cmd)    # points and regions become their own fields, by name
    return json.dumps(out, sort_keys=True)


def parse_proposal(text: str, issued_at: float | None = None) -> Decision:
    """The decision `text` states, or an INVALID decision with every problem found. Never raises."""
    problems: list[str] = []
    try:
        data = json.loads(text)
    except (ValueError, TypeError) as exc:
        return Decision.invalid(str(text), [f"[proposal] not JSON: {_clean(exc)}"], issued_at)
    if isinstance(data, list):
        if len(data) > 1:
            return Decision.invalid(text, [f"[conflict] {len(data)} commands in one answer: one at a time"], issued_at)
        return Decision.invalid(text, ["[proposal] an array, not one decision object"], issued_at)
    if not isinstance(data, dict):
        return Decision.invalid(text, [f"[proposal] {data!r} is not a decision object"], issued_at)
    problems += [f"[proposal] unknown key {k!r}" for k in data if k not in TOP_KEYS]
    kind = KINDS.get(data.get("decision")) if isinstance(data.get("decision"), str) else None
    if kind is None:
        problems.append(f"[proposal] decision is {data.get('decision')!r}, not one of {sorted(KINDS)}")
    for k in ("objective", "reason"):
        if data.get(k) is not None and not isinstance(data[k], str):
            problems.append(f"[proposal] {k} is {data[k]!r}, not text")
    command = None
    if kind is DecisionKind.START:
        command = _command(data, problems)
    elif kind is not None and ("skill" in data or "parameters" in data):
        problems.append(f"[conflict] a {kind.value} decision that also names a skill: which is meant")
    if problems:
        return Decision.invalid(text, problems, issued_at)
    return Decision(kind, data.get("objective"), command, data.get("reason") or "", issued_at, text)


def _command(data: dict[str, Any], problems: list[str]) -> Any:
    name = data.get("skill")
    try:
        skill = SkillName(name)
    except ValueError:
        problems.append(f"[proposal] skill {name!r} is not one of the eleven skills")
        return None
    params = data.get("parameters", {})
    if not isinstance(params, dict):
        problems.append(f"[proposal] parameters is {params!r}, not an object")
        return None
    cls = CONTRACTS[skill].command
    known = {f.name for f in fields(cls)}
    unknown = [k for k in params if k not in known]
    problems += [f"[proposal] {skill.value} has no parameter {k!r}" for k in unknown]
    values: dict[str, Any] = {}
    for k, v in params.items():
        if k in known:
            values[k] = _value(f"parameters.{k}", k, v, problems)
    if problems:
        return None
    try:
        return cls(**values)
    except (ValueError, TypeError) as exc:
        problems.append(f"[proposal] {skill.value}: {_clean(exc)}")
        return None


def _number(where: str, v: Any, problems: list[str], allow_none: bool = False) -> Any:
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        problems.append(f"[proposal] {where} is {v!r}, not a number")
        return None
    if not math.isfinite(v):
        problems.append(f"[proposal] {where} is {v!r}: not a number a drone can fly by")
        return None
    return float(v)


def _keys(where: str, v: Any, keys: tuple[str, ...], problems: list[str]) -> dict[str, Any] | None:
    if not isinstance(v, dict) or set(v) != set(keys):
        problems.append(f"[proposal] {where} is {v!r}, not an object with exactly {', '.join(keys)}")
        return None
    out = {k: _number(f"{where}.{k}", v[k], problems) for k in keys}
    return None if any(x is None for x in out.values()) else out


def _value(where: str, name: str, v: Any, problems: list[str]) -> Any:
    try:
        if name in POINT_FIELDS:
            p = _keys(where, v, POINT_KEYS, problems)
            return None if p is None else nav.Waypoint(**p)
        if name == "waypoints":
            if not isinstance(v, list):
                problems.append(f"[proposal] {where} is {v!r}, not a list of points")
                return None
            pts = [_keys(f"{where}[{i}]", p, POINT_KEYS, problems) for i, p in enumerate(v)]
            return None if any(p is None for p in pts) else tuple(nav.Waypoint(**p) for p in pts)
        if name == "region":
            r = _keys(where, v, REGION_KEYS, problems)
            return None if r is None else Region(**r)
        if name == "avoid":
            return _areas(where, v, problems)
    except ValueError as exc:
        problems.append(f"[proposal] {where}: {_clean(exc)}")
        return None
    return _number(where, v, problems, allow_none=True)


def _areas(where: str, v: Any, problems: list[str]) -> tuple[Polygon, ...] | None:
    """A list of {"vertices": [[x, y], ...]}: the areas a search goes round."""
    if not isinstance(v, list):
        problems.append(f"[proposal] {where} is {v!r}, not a list of areas")
        return None
    out = []
    for i, area in enumerate(v):
        here = f"{where}[{i}]"
        if not isinstance(area, dict) or set(area) != {"vertices"} or not isinstance(area["vertices"], list):
            problems.append(f"[proposal] {here} is {area!r}, not an object with exactly vertices, a list")
            return None
        points = []
        for j, p in enumerate(area["vertices"]):
            if not isinstance(p, list) or len(p) != 2:
                problems.append(f"[proposal] {here}.vertices[{j}] is {p!r}, not a point [x, y]")
                return None
            x, y = _number(f"{here}.vertices[{j}][0]", p[0], problems), _number(f"{here}.vertices[{j}][1]", p[1], problems)
            if x is None or y is None:
                return None
            points.append((x, y))
        out.append(Polygon(tuple(points)))
    return tuple(out)


def _clean(exc: BaseException) -> str:
    """An exception's message, safe to join problems with "; "."""
    return str(exc).replace("; ", ", ")
