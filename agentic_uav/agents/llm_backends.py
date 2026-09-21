"""Model backends, and the record of exactly which model produced a run (12.1, 12.7).

A backend is deliberately tiny: text in, text out, with a timeout.

    complete(system, user, timeout_s) -> str

Everything interesting — the tool schema, the validation, the fallback chain —
lives above this line and is therefore identical across models. That is what
makes "Llama vs Mistral vs Gemini, same architecture" a fair comparison rather
than a comparison of three differently-written integrations.

**One model process, four agents (12.1).** A shared `OllamaBackend` instance
serves every agent, because a backend holds no conversation: each call carries
its whole context. The per-agent state that matters for the research — identity,
belief, task, memory, inbox, decision history — lives in the agent, not here. So
four agents over one Ollama process are four independent agents, and the test
suite asserts it rather than assuming it.

**Pinning (12.7).** `ModelCard` records the exact identifier and sampling
configuration, and `is_pinned` refuses to certify a floating tag like `latest`
for a formal experiment. A paper whose method section says "Gemini" describes a
system that no longer exists.
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


class BackendTimeout(Exception):
    """The model did not answer within the budget."""


class BackendError(Exception):
    """The model could not be reached, or failed."""


# --- reproducibility ---


#: Tags that mean "whatever is current", which is the opposite of reproducible.
FLOATING_TAGS = ("latest", "latest-stable", "preview", "experimental", "auto")


@dataclass
class ModelCard:
    """Exactly what produced a run. Saved next to the results (12.7)."""
    provider: str                       # ollama | gemini | scripted
    model: str                          # the exact identifier
    temperature: float = 0.0
    seed: Optional[int] = None
    max_tokens: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    recorded_at: str = ""

    def __post_init__(self):
        if not self.recorded_at:
            self.recorded_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    @property
    def is_pinned(self) -> bool:
        """Whether this model is fixed enough to base a published result on.

        A local model with a version tag is pinned. `llama3.1:latest` is not:
        it names a moving target, and a reviewer re-running the experiment in
        six months gets different weights with the same command. `scripted` is
        pinned because it is code in this repository.
        """
        m = self.model.lower()
        if self.provider == "scripted":
            return True
        if any(tag in m for tag in FLOATING_TAGS):
            return False
        # a local model identifier should carry an explicit version tag
        if self.provider == "ollama":
            return ":" in m
        # a hosted model should carry a dated or numbered revision
        return any(ch.isdigit() for ch in m)

    def warnings(self) -> List[str]:
        out = []
        if not self.is_pinned:
            out.append(f"{self.provider}:{self.model} is not pinned to a fixed "
                       f"version; results will not be reproducible")
        if self.temperature and self.temperature > 0:
            out.append(f"temperature={self.temperature} is not zero; the same "
                       f"prompt may produce different decisions")
        if self.provider == "gemini":
            out.append("a hosted model may change without notice; use it as a "
                       "comparison, not as the primary result")
        return out

    def as_dict(self):
        d = asdict(self)
        d["is_pinned"] = self.is_pinned
        d["warnings"] = self.warnings()
        return d

    def slug(self):
        return f"{self.provider}-{self.model}".replace(":", "_").replace("/", "_")


# --- scripted backend (no model required) ---


class ScriptedBackend:
    """A backend that replays fixed answers. The `fake_airsim` of Phase 12.

    Every property of this phase that is not "the model is smart" can be tested
    with this: tool validation, the correction path, timeouts, malformed output,
    unsafe actions, per-agent isolation, the guardian still holding. It makes the
    whole phase runnable on a laptop with no GPU, no Ollama and no API key, and
    it makes the tests deterministic — which tests of an LLM system otherwise
    are not.

    Answers may be strings (returned verbatim, including deliberate garbage),
    dicts (serialised), or callables `(system, user) -> str` for responses that
    depend on the context. A callable raising `BackendTimeout` simulates a hang
    without actually waiting.
    """

    provider = "scripted"

    def __init__(self, answers=None, model="scripted-v1", default=None,
                 per_agent=None):
        self.model = model
        self._answers = list(answers or [])
        self._default = default
        #: answers keyed by vehicle id, for multi-agent scripts
        self._per_agent = {k: list(v) for k, v in (per_agent or {}).items()}
        self.calls: List[Dict[str, Any]] = []

    def card(self, temperature=0.0):
        return ModelCard(provider="scripted", model=self.model,
                         temperature=temperature)

    def complete(self, system, user, timeout_s=None, **_):
        self.calls.append({"system": system, "user": user})

        queue = self._answers
        vid = _vehicle_id_in(user)
        if vid and vid in self._per_agent and self._per_agent[vid]:
            queue = self._per_agent[vid]

        if queue:
            answer = queue.pop(0)
        elif self._default is not None:
            answer = self._default
        else:
            raise BackendError("scripted backend has no answer left")

        if callable(answer):
            answer = answer(system, user)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, (dict, list)):
            return json.dumps(answer)
        return str(answer)


def _vehicle_id_in(user_prompt):
    """Pull the vehicle id out of a rendered context, for per-agent scripts."""
    try:
        start = user_prompt.index('"vehicle_id"')
        seg = user_prompt[start:start + 64]
        return seg.split('"')[3]
    except (ValueError, IndexError):
        return None


# --- local model via Ollama ---


DEFAULT_OLLAMA_MODEL = "llama3.1:8b"


class OllamaBackend:
    """A pinned local model. The primary backend for formal experiments (12.7).

    Runs with `num_gpu=0` by default so the GPU stays free for the simulator —
    CARLA-Air and a 8B model competing for the same card is how a run turns into
    a timeout study. `format=` applies the decision schema as a decoding
    constraint, which removes most malformed-output failures at the source.

    One instance is shared by every agent (12.1); it carries no per-agent state.
    """

    provider = "ollama"

    def __init__(self, model=DEFAULT_OLLAMA_MODEL, temperature=0.0,
                 num_gpu=0, seed=0, schema=None, host=None):
        import ollama                                  # lazy: not needed to import
        self._client = ollama.Client(host=host) if host else ollama
        self.model = model
        self.temperature = temperature
        self.num_gpu = num_gpu
        self.seed = seed
        self._schema = schema

    def card(self):
        return ModelCard(provider="ollama", model=self.model,
                         temperature=self.temperature, seed=self.seed,
                         extra={"num_gpu": self.num_gpu})

    def complete(self, system, user, timeout_s=None, schema=None, **_):
        options = {"temperature": self.temperature, "num_gpu": self.num_gpu}
        if self.seed is not None:
            options["seed"] = self.seed
        try:
            kwargs = dict(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                options=options)
            fmt = schema if schema is not None else self._schema
            if fmt is not None:
                kwargs["format"] = fmt
            response = self._client.chat(**kwargs)
        except Exception as e:                     # ollama raises several types
            if "timeout" in str(e).lower():
                raise BackendTimeout(str(e))
            raise BackendError(f"ollama call failed: {e}")
        return response["message"]["content"]


# --- hosted model, for comparison only ---


class GeminiBackend:
    """A hosted model. **Comparison only** — see 12.7.

    Deliberately not the default anywhere. A cloud endpoint can change under a
    fixed name, so a result that only exists there is not reproducible by a
    reviewer. `ModelCard.warnings()` says so in the saved output rather than
    leaving it to the write-up to remember.
    """

    provider = "gemini"

    def __init__(self, model="gemini-2.0-flash-001", temperature=0.0,
                 api_key=None, schema=None):
        import google.generativeai as genai          # lazy import
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise BackendError("GEMINI_API_KEY is not set")
        genai.configure(api_key=key)
        self._genai = genai
        self.model = model
        self.temperature = temperature
        self._schema = schema

    def card(self):
        return ModelCard(provider="gemini", model=self.model,
                         temperature=self.temperature)

    def complete(self, system, user, timeout_s=None, schema=None, **_):
        cfg = {"temperature": self.temperature,
               "response_mime_type": "application/json"}
        try:
            model = self._genai.GenerativeModel(
                self.model, system_instruction=system, generation_config=cfg)
            resp = model.generate_content(
                user, request_options={"timeout": timeout_s} if timeout_s else None)
        except Exception as e:
            if "deadline" in str(e).lower() or "timeout" in str(e).lower():
                raise BackendTimeout(str(e))
            raise BackendError(f"gemini call failed: {e}")
        return resp.text


# --- timeout wrapper ---


def call_with_timeout(backend, system, user, timeout_s, schema=None):
    """Run a backend call under a wall-clock budget.

    A thread is used rather than a signal because agents run in threads under
    the Phase 7 concurrent runner, and `signal.alarm` only works on the main
    thread. The worker is abandoned on timeout rather than killed — Python
    cannot kill a thread — so the model call continues in the background and its
    result is discarded. That is acceptable here and would not be in a real
    aircraft, which is worth stating plainly rather than papering over: the
    agent has already moved on to its fallback.
    """
    if timeout_s is None:
        return backend.complete(system, user, schema=schema)

    import threading
    box = {}

    def _work():
        try:
            box["out"] = backend.complete(system, user, timeout_s=timeout_s,
                                          schema=schema)
        except BaseException as e:                       # noqa: BLE001
            box["err"] = e

    t = threading.Thread(target=_work, daemon=True,
                         name="llm-call")
    started = time.monotonic()
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise BackendTimeout(
            f"model did not answer within {timeout_s}s "
            f"(abandoned after {time.monotonic() - started:.1f}s)")
    if "err" in box:
        raise box["err"]
    return box.get("out")


# --- selection ---


def make_backend(name="scripted", **kwargs):
    """Build a backend by name. `scripted` is the default on purpose.

    Nothing in this repository requires a model to run its tests, which is what
    keeps the suite fast, deterministic and runnable by a reviewer who has
    neither Ollama nor an API key.
    """
    name = (name or "scripted").lower()
    if name in ("scripted", "fake", "none"):
        return ScriptedBackend(**kwargs)
    if name in ("ollama", "llama", "local"):
        return OllamaBackend(**kwargs)
    if name == "mistral":
        kwargs.setdefault("model", "mistral:7b")
        return OllamaBackend(**kwargs)
    if name == "gemini":
        return GeminiBackend(**kwargs)
    raise ValueError(f"unknown backend {name!r}; "
                     f"use scripted, ollama, mistral or gemini")
