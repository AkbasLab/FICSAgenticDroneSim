"""The Ollama planner: a language model served by Ollama, locally or remotely.

Llama and Mistral models both run through it; the model is a constructor
argument. `plan_for` is the function the baseline always used. `OllamaPlanner`
is the same thing behind the `MissionPlanner` protocol.

Moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 4;
`tests/test_golden.py` proves every planning request and record is unchanged.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..core.errors import PlanError
from .base_planner import PlanRecord
from .endpoint import MODEL, OLLAMA_ENDPOINT, is_transport_error, normalise_endpoint
from .plan_schema import PLAN_SCHEMA, validate
from .prompt import build_messages

# DEFAULT inference options for running the agent directly. The authoritative
# values for a scored series live in configs/missions/*.toml under
# [protocol.options] and are passed in -- see plan_for(). These are part of the
# measurement protocol, not preferences.
#
# num_gpu is the number of layers offloaded to the GPU, and it is PER REQUEST.
# Zero is correct on this laptop, where the simulator already owns 4 GB of
# VRAM -- but sending zero to a remote GPU server makes that server reload the
# model onto CPU cores. Measured 2026-10-06: a 70B sitting entirely on an H100
# would be thrown off it by this one value.
#
# num_ctx matters more than it looks. Left unset, Ollama uses the model's own
# maximum, which for llama3.3 is 131072 -- and the KV cache for a 70B at that
# length is about 43 GB on top of 42 GB of weights, so the model does not fit
# in an 80 GB card and gets split 67%/33% CPU/GPU. Pinning it small puts the
# whole model on the GPU and makes the number comparable between machines
# instead of depending on each Ollama version's default.
OLLAMA_OPTIONS = {
    # The LAPTOP's defaults, not the study's. The runner always sends the
    # protocol block from the mission config, which since 2026-10-19 asks for
    # num_ctx 98304 on one H100 (briefly 131072 on two, superseded the same
    # day). These values are what a bare import gets on a machine whose
    # VRAM belongs to the simulator.
    "num_gpu": 0,
    "num_ctx": 4096,
    "temperature": 0,
    "num_predict": 512,
    "num_thread": 12,
}


def plan_for(instruction: str, drone: str, model: str = MODEL,
             endpoint: str = OLLAMA_ENDPOINT,
             options: dict[str, Any] | None = None,
             system_prompt: str | None = None) -> PlanRecord:
    """Ask the model for a plan and validate it. Never raises; records instead.

    An explicit `ollama.Client(host=...)` rather than the module-level
    `ollama.chat`, because the module-level call silently honours OLLAMA_HOST
    from the environment. That is convenient and dangerous in equal measure: a
    stale environment variable would send planning calls somewhere other than
    where the record claims, and nothing would look wrong.
    """
    import ollama  # imported here so --plan-only works without AirSim installed

    endpoint = normalise_endpoint(endpoint)
    # The options that actually ran, not the ones a config happens to declare.
    options = dict(OLLAMA_OPTIONS if options is None else options)
    client = ollama.Client(host=endpoint)
    started = time.time()
    raw = ""
    try:
        response = client.chat(
            model=model,
            messages=build_messages(instruction, system_prompt),
            format=PLAN_SCHEMA,
            options=options,
        )
        raw = response["message"]["content"]
        elapsed = time.time() - started
        steps, notes = validate(json.loads(raw))
        return PlanRecord(drone, instruction, raw, steps, elapsed, True, None,
                          notes, model, endpoint)
    except (PlanError, json.JSONDecodeError) as exc:
        return PlanRecord(drone, instruction, raw, None, time.time() - started,
                          False, str(exc), [], model, endpoint)
    except Exception as exc:
        # Separated deliberately: "the endpoint was unreachable" and "the model
        # produced nonsense" are different findings, and only the second is
        # about the model. See is_transport_error().
        transport = is_transport_error(exc)
        if transport:
            print(f"[{drone}] ENDPOINT UNREACHABLE at {endpoint}: "
                  f"{type(exc).__name__}: {exc}", flush=True)
        return PlanRecord(
            drone, instruction, raw, None, time.time() - started, False,
            f"{type(exc).__name__}: {exc}", [], model, endpoint, transport,
        )


class OllamaPlanner:
    """`plan_for` with its settings fixed: one model, one endpoint, one option set.

    `system_prompt` defaults to the study's. The sandbox passes its own.
    """

    def __init__(self, model: str = MODEL, endpoint: str = OLLAMA_ENDPOINT,
                 options: dict[str, Any] | None = None,
                 system_prompt: str | None = None) -> None:
        self.model = model
        self.endpoint = endpoint
        self.options = options
        self.system_prompt = system_prompt

    def plan(self, instruction: str, drone: str) -> PlanRecord:
        return plan_for(instruction, drone, self.model, self.endpoint,
                        self.options, self.system_prompt)
