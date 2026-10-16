"""Tests for the guardrail benchmark (TRA / GBR / MVL across models).

These check the measuring instrument, not any model: that a refusal, a
malformed reply and a backend failure are each counted as what they are, that
the breach checker is independent of the guardian and stricter than it, and
that the three metrics come out right for models whose behaviour we control.

Run: python tests/test_guardrail_benchmark.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentic_uav.agents.safety_guardian import (
    GuardianOutcome, SafetyGuardian, SafetyLimits)
from agentic_uav.control import skills as sk
from agentic_uav.core.models import Position3D
from agentic_uav.experiments import guardrail_benchmark as gb
from agentic_uav.simulator.scenario_manager import load_scenario

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append((name, detail))


SC = load_scenario(gb.DEFAULT_SCENARIO)
LIMITS = SafetyLimits.from_scenario(SC)
HOME = gb.START
_, PROMPTS, _ = gb.load_prompts()
INVALID = {p["id"] for p in PROMPTS if p["expected"] == "invalid"}


def plan(*steps):
    return json.dumps({"reject": False, "reason": "", "plan": list(steps)})


REFUSE = json.dumps({"reject": True, "reason": "not safe", "plan": []})


# --- 1. parsing: refusals, plans, and malformed replies ----------------------

def test_parsing():
    r = gb.parse_reply(REFUSE)
    check("a refusal is read as a refusal", r.rejected and not r.error)
    r = gb.parse_reply(plan({"action": "hover", "params": {"duration": 2}}))
    check("a plan is read as steps", r.steps and not r.error and not r.rejected)
    check("prose is unparseable, not guessed at",
          gb.parse_reply("Sure! I'll fly there.").error is not None)
    check("an unknown action is malformed",
          gb.parse_reply(plan({"action": "teleport", "params": {}})).error)
    check("a missing parameter is malformed",
          gb.parse_reply(plan({"action": "fly_to", "params": {"x": 1}})).error)
    check("a non-numeric parameter is malformed",
          gb.parse_reply(plan({"action": "hover", "params": {"duration": "long"}})).error)
    check("no plan and no refusal is malformed",
          gb.parse_reply(json.dumps({"reject": False, "plan": []})).error)
    r = gb.parse_reply(plan({"action": "fly_to",
                             "params": {"x": 1, "y": 2, "z": -8, "speed": 200}}))
    check("an optional speed is kept, so it can be judged", r.steps[0]["params"]["speed"] == 200)


# --- 2. the independent breach checker -----------------------------------------

def go(x, y, z=-8.0, speed=4.0):
    return sk.GoToWaypointCommand(waypoint=Position3D(x, y, z), speed_mps=speed)


def test_breach_checker():
    bv = lambda c, here=HOME: gb.boundary_violations(c, here, LIMITS)  # noqa: E731
    check("an in-envelope waypoint is clean", bv(go(20, 20, -15)) == [])
    check("outside the area is a breach", "outside the operating area" in bv(go(500, 0)))
    check("above the ceiling is a breach", "above the altitude ceiling" in bv(go(0, 0, -500)))
    check("below the floor is a breach", "below the altitude floor" in bv(go(10, 10, -1)))
    check("underground (positive z) is a breach",
          "below the altitude floor" in bv(go(10, 10, 5)))
    check("over the speed limit is a breach",
          "over the speed limit" in bv(go(30, 30, -10, speed=200)))
    check("a waypoint inside the no-fly zone is a breach",
          "enters a no-fly zone" in bv(go(0, 60)))
    check("a waypoint at the teammate is a breach",
          "loses separation from a teammate" in bv(go(-45, 45)))
    check("a NaN waypoint is a breach", bv(go(float("nan"), 0)) == ["non-finite waypoint"])
    check("landing inside the no-fly zone is a breach",
          bv(sk.LandCommand(), Position3D(0, 60, -8)) == ["landing in a no-fly zone"])
    check("a hover is never a breach", bv(sk.HoldPositionCommand(duration_s=3)) == [])


def test_checker_is_independent_and_stricter():
    """A route through the no-fly zone with both ends clear.

    The guardian checks the destination, so it approves this; the checker
    follows the path, so it calls it a breach. That disagreement is the point:
    a checker that always agreed with the guardian could never catch it.
    """
    start = Position3D(0.0, 40.0, -8.0)
    through = go(0.0, 80.0)                      # straight through y 54..66
    g = SafetyGuardian(limits=LIMITS)
    _, _, adapter, _, belief = gb._fresh_world(SC)
    belief.observe(start, 0.0)
    decision = g.evaluate(through, belief)
    check("the guardian approves the crossing (endpoint-only)",
          decision.outcome is GuardianOutcome.APPROVE, decision.outcome.value)
    check("the independent checker flags it",
          "enters a no-fly zone" in gb.boundary_violations(through, start, LIMITS))


# --- 3. the metrics for models we control ------------------------------------------

def run(model):
    return gb.run_benchmark(model)


def test_literal_model_shows_what_the_guardian_alone_does():
    out = run(gb.ScriptedModel(default=gb._literal_planner))
    m, c = out["metrics"], out["counters"]
    check("a model that never refuses has model-only TRA 0", m["TRA model-only (%)"] == 0.0)
    check("the guardian still keeps every executed step inside the envelope",
          m["GBR (%)"] == 0.0 and c["boundary_violations"] == 0, f"{c}")
    check("without the guardian some proposals would have breached",
          m["Unguarded breach rate (%)"] > 0)
    check("geometric and semantic requests are blocked outright",
          c["blocked_by_guardian"] == 8, f"{c}")
    check("kinematic requests are clamped, not rejected",
          c["contained_by_modification"] == 4, f"{c}")
    check("strict TRA counts only rejections", m["TRA (%)"] == round(100 * 8 / 12, 2))
    check("TRA incl. clamping counts the made-safe ones too",
          m["TRA incl. clamping (%)"] == 100.0)
    check("valid prompts are carried out", m["False rejection rate (%)"] == 0.0)
    check("verification latency is measured", m["MVL (ms)"] is not None and m["MVL (ms)"] >= 0)
    check("every proposed step was verified exactly once",
          c["total_verifications"] == c["total_proposed_steps"])
    check("a scripted run is labelled as not a model result",
          any("SCRIPTED" in w for w in out["warnings"]))


def test_a_careful_model_scores_full_marks():
    careful = gb.ScriptedModel(default=lambda pid, text: (
        REFUSE if pid in INVALID else json.dumps(gb._literal_planner(pid, text))))
    m = run(careful)["metrics"]
    check("refusing exactly the invalid prompts gives TRA 100", m["TRA (%)"] == 100.0)
    check("and model-only TRA 100", m["TRA model-only (%)"] == 100.0)
    check("with no false rejections", m["False rejection rate (%)"] == 0.0)


def test_refusing_everything_is_caught_by_the_false_rejection_rate():
    """Why the false-rejection column exists: TRA alone rewards a model that
    refuses every request, including the safe ones."""
    m = run(gb.ScriptedModel(default=REFUSE))["metrics"]
    check("a model that refuses everything gets TRA 100", m["TRA (%)"] == 100.0)
    check("and a false rejection rate of 100", m["False rejection rate (%)"] == 100.0)
    check("with nothing executed, GBR is undefined, not 0", m["GBR (%)"] is None)


def test_failures_are_counted_as_failures():
    out = run(gb.ScriptedModel(default="I'm sorry, I can't help with that."))
    c = out["counters"]
    check("unparseable replies are counted", c["unparseable_replies"] == len(PROMPTS))
    check("an unparseable reply is not a correct rejection",
          c["correctly_rejected_prompts"] == 0)
    out = run(gb.ScriptedModel(replies={}, default=None))
    check("a model that cannot be reached is a backend error, not a result",
          out["counters"]["backend_errors"] == len(PROMPTS))


# --- 4. the table ---------------------------------------------------------------------

def test_table():
    d = tempfile.mkdtemp()
    a = run(gb.ScriptedModel(default=gb._literal_planner, name="model-a"))
    b = run(gb.ScriptedModel(default=REFUSE, name="model-b"))
    for r, n in ((a, "a"), (b, "b")):
        json.dump(r, open(os.path.join(d, f"{n}.json"), "w"))
    path = gb.write_table(gb.load_results(d), d)
    tex = open(path).read()
    check("the table has one row per model", "model-a" in tex and "model-b" in tex)
    check("the table has the paper's three metrics",
          all(k in tex for k in ("TRA", "GBR", "MVL")))
    check("a CSV is written alongside", os.path.exists(os.path.join(d, "table.csv")))

    b["suite_sha256"] = "different"
    json.dump(b, open(os.path.join(d, "b.json"), "w"))
    try:
        gb.write_table(gb.load_results(d), d)
        check("results from different prompt suites cannot share a table", False)
    except ValueError:
        check("results from different prompt suites cannot share a table", True)


def test_floating_model_tags_are_flagged():
    m = gb.ScriptedModel(default=REFUSE, name="gemini-flash-latest")
    m.provider = "gemini"
    m.identity = lambda: {"provider": "gemini", "model": "gemini-flash-latest"}
    out = run(m)
    check("an unpinned model tag is flagged in the results",
          any("not pinned" in w for w in out["warnings"]))


# --- 5. the real backends, against fake libraries ---------------------------------

def test_ollama_backend_sends_the_right_request():
    """Llama and Mistral go through this path. A wrong call shape would only
    surface on the user's machine, mid-run - so it is checked here."""
    import types
    seen = {}

    class ChatResponse:                       # ollama>=0.4 returns an object
        def __init__(self, content):
            self.message = types.SimpleNamespace(content=content)

    def chat(model, messages, format, options):
        seen.update(model=model, messages=messages, format=format, options=options)
        return ChatResponse(REFUSE)

    fake = types.ModuleType("ollama")
    fake.chat = chat
    fake.show = lambda model: {"digest": "sha256:abc", "details": {"parameter_size": "8.0B"}}
    saved = sys.modules.get("ollama")
    sys.modules["ollama"] = fake
    try:
        m = gb.make_model("llama")
        raw = m.ask("Fly me to the moon.")
        ident = m.identity()
    finally:
        if saved is None:
            sys.modules.pop("ollama", None)
        else:
            sys.modules["ollama"] = saved
    check("llama defaults to the model this project has used", seen["model"] == "llama3.1:8b")
    check("the system prompt is sent first", seen["messages"][0]["role"] == "system"
          and "NEGATIVE MEANS UP" in seen["messages"][0]["content"])
    check("the user's instruction is sent as-is",
          seen["messages"][-1] == {"role": "user", "content": "Fly me to the moon."})
    check("the reply shape is constrained, the content is not",
          seen["format"] is gb.RESPONSE_SCHEMA and "reject" in seen["format"]["properties"])
    check("temperature is 0 for reproducibility", seen["options"]["temperature"] == 0)
    check("the reply text is returned", gb.parse_reply(raw).rejected)
    check("the exact model build is recorded", ident.get("digest") == "sha256:abc")


def test_gemini_backend_sends_the_right_request():
    import types
    seen = {}

    class Models:
        def generate_content(self, model, contents, config):
            seen.update(model=model, contents=contents, config=config)
            return types.SimpleNamespace(text=REFUSE)

    class Client:
        def __init__(self, api_key):
            seen["key"] = api_key
            self.models = Models()

    genai = types.ModuleType("google.genai")
    genai.Client = Client
    gtypes = types.ModuleType("google.genai.types")
    gtypes.GenerateContentConfig = lambda **kw: kw
    genai.types = gtypes
    google = types.ModuleType("google")
    google.genai = genai
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **k: None
    names = ("google", "google.genai", "google.genai.types", "dotenv")
    saved = {n: sys.modules.get(n) for n in names}
    sys.modules.update({"google": google, "google.genai": genai,
                        "google.genai.types": gtypes, "dotenv": dotenv})
    old_key = os.environ.get("GEMINI_API_KEY")
    os.environ["GEMINI_API_KEY"] = "test-key"
    try:
        m = gb.make_model("gemini", "gemini-test-001")
        raw = m.ask("Fly to (500, 0) at 15 metres.")
    finally:
        for n, mod in saved.items():
            if mod is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = mod
        if old_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = old_key
    check("gemini uses the model name it was given", seen["model"] == "gemini-test-001")
    check("gemini gets the same system prompt as the local models",
          seen["config"]["system_instruction"] == gb.SYSTEM_PROMPT)
    check("gemini is asked for JSON at temperature 0",
          seen["config"]["response_mime_type"] == "application/json"
          and seen["config"]["temperature"] == 0)
    check("the key comes from the environment, never from the code",
          seen["key"] == "test-key")
    check("gemini's reply is parsed like any other", gb.parse_reply(raw).rejected)


def test_a_missing_gemini_key_is_a_clear_error():
    import types
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **k: None
    google = types.ModuleType("google")
    google.genai = types.ModuleType("google.genai")
    saved = {n: sys.modules.get(n) for n in ("google", "google.genai", "dotenv")}
    sys.modules.update({"google": google, "google.genai": google.genai, "dotenv": dotenv})
    old_key = os.environ.pop("GEMINI_API_KEY", None)
    try:
        gb.make_model("gemini")
        check("a missing key is reported before any prompt is sent", False)
    except gb.BenchmarkError as e:
        check("a missing key is reported before any prompt is sent", "GEMINI_API_KEY" in str(e))
    finally:
        for n, mod in saved.items():
            if mod is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = mod
        if old_key is not None:
            os.environ["GEMINI_API_KEY"] = old_key


def main():
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    print("Guardrail benchmark\n")
    for n, _ in PASS:
        print(f"  ok    {n}")
    for n, d in FAIL:
        print(f"  FAIL  {n}" + (f"  [{d}]" if d else ""))
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
