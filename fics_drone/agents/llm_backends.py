"""Where the text comes from. A backend is text-in/text-out and holds no
conversation, so ONE backend object can serve every drone - what stays
separate per agent is identity, belief and decision history (those live in
each agent's own LLMAgentPolicy, never here).

ScriptedBackend is this phase's fake_airsim: every property that is not "the
model is smart" - validation, the correction path, timeouts, fallback, the
guardian still holding - is testable against scripted answers,
deterministically, with no GPU and no Ollama installed.
"""

import re
import threading
from abc import ABC, abstractmethod
from typing import Callable, Optional, Sequence, Union

from .decision_schema import decision_json


class BackendTimeout(Exception):
    """The model did not answer within the time budget."""


class BackendError(Exception):
    """The model server is unreachable or returned something unusable at the transport level."""


class ModelBackend(ABC):
    @abstractmethod
    def complete(self, prompt: str, timeout_s: float) -> str:
        """Return the raw model text, or raise BackendTimeout / BackendError."""


def default_script(prompt: str) -> str:
    """A sensible stand-in for a model, reading the same prompt a real model would (no side channel).
    Waits while nobody has reported a target to us yet (if waiting is offered); otherwise takes an
    unheld task if the menu offers one; otherwise goes home."""
    if "- hold:" in prompt and "second_hand_targets: 0" in prompt:
        return decision_json("hold", "waiting_for_report")
    claim = re.search(r"- claim_task:.*?one of \['([^']+)'", prompt)
    if claim:
        return decision_json("claim_task", "teammate_may_need_help", params={"task_id": claim.group(1)})
    return decision_json("return_home", "my_work_is_done")


class ScriptedBackend(ModelBackend):
    """Pass `answers` to feed exact outputs in order (a str is returned, an
    Exception instance is raised), falling back to `respond(prompt)` once the
    list runs out. Thread-safe - four agent threads share one instance."""

    def __init__(self, answers: Sequence[Union[str, Exception]] = (),
                 respond: Optional[Callable[[str], str]] = default_script):
        self._answers = list(answers)
        self._respond = respond
        self._lock = threading.Lock()
        self.prompts = []
        self.calls = 0

    def complete(self, prompt: str, timeout_s: float) -> str:
        with self._lock:
            self.calls += 1
            self.prompts.append(prompt)
            item = self._answers.pop(0) if self._answers else None
        if item is None:
            if self._respond is None:
                raise BackendError("scripted backend has no answer left")
            return self._respond(prompt)
        if isinstance(item, Exception):
            raise item
        return item
