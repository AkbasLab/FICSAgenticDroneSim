"""What the model is told: the system prompt, two worked examples, the request.

The examples are deliberately NOT missions from the benchmark. A demonstration
that mirrors a benchmark item makes that item score correct because it sits in
the prompt (found and removed 2026-09-24).

Moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 4;
`tests/test_golden.py` proves every planning request and record is unchanged.
"""

from __future__ import annotations

import json

from ..core.protocol import MOVE_SPEED

SYSTEM_PROMPT = f"""You convert a plain-English drone instruction into a flight plan.

Reply with JSON only: {{"plan": [ ... ]}} -- an array of steps, in execution order.

Available actions, and their parameters:
  fly_to        x, y, z    fly to an absolute coordinate
  fly_straight  duration   forward, relative to the drone's heading
  fly_backward  duration   backward
  fly_left      duration   strafe left
  fly_right     duration   strafe right
  hover         duration   hold position
  set_altitude  z          climb or descend
  land                     controlled descent and landing

Rules:
- duration is in seconds. Speed is fixed at {MOVE_SPEED} m/s and cannot be changed.
- z is altitude in NED: NEGATIVE IS UP. 20 metres above ground is z = -20.
- Emit one step per requested manoeuvre, in the order they must be executed,
  which is not always the order they are mentioned.
- "return home" is fly_to with x = 0, y = 0.
- Do not invent actions. Do not add steps that were not asked for.
"""

# Worked examples, chosen so that none of them is a mission from
# docs/BASELINE_MISSIONS.md or a close paraphrase of one. A demonstration that
# mirrors a benchmark item makes that item score correct because it is in the
# prompt, not because the model solved it.
EXAMPLES = [
    (
        "fly left for 2 seconds, then climb to 30 meters",
        {"plan": [
            {"action": "fly_left", "duration": 2},
            {"action": "set_altitude", "z": -30},
        ]},
    ),
    (
        "after hovering for 4 seconds, fly backward for 6 seconds",
        {"plan": [
            {"action": "hover", "duration": 4},
            {"action": "fly_backward", "duration": 6},
        ]},
    ),
]


def build_messages(instruction: str,
                   system_prompt: str | None = None) -> list[dict[str, str]]:
    # `system_prompt` lets a caller supply its own text; the interactive
    # sandbox rewrites the prompt at runtime. None means the study's prompt.
    messages = [{"role": "system",
                 "content": SYSTEM_PROMPT if system_prompt is None else system_prompt}]
    for example_instruction, example_plan in EXAMPLES:
        messages.append({"role": "user", "content": example_instruction})
        messages.append({"role": "assistant", "content": json.dumps(example_plan)})
    messages.append({"role": "user", "content": instruction})
    return messages
