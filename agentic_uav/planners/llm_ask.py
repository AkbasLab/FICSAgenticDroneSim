"""The model behind an LLM policy: Ollama, or a stand-in that needs no GPU (AUV-12, 12.6, 12.7).

    ask = OllamaAsk(config, endpoint)        # the pinned model on a server; calls one at a time
    ask = EchoAsk()                          # answers what the rule policy would: the transparency check
    ask = ReplayAsk(records)                 # answers what was recorded: a flight re-flown exactly, offline
    ask = Recorder(ask)                      # remembers every request and reply, for a later replay

Each is a callable taking the policy's request -- {"messages": [...], "meta": {...}} -- and returning
the reply's text, or raising (a timeout, an unreachable server, a reply not on record). `meta` is never
sent to a model: it carries the rule's own answer, for the echo alone.

ONE CALL AT A TIME (12.7). The four drones' agents ask from their own threads. A server that batches
concurrent requests can give a prompt a different answer than it gives it alone, so the calls are
serialized here: the answer depends on the prompt, not on who else was asking.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any

from ..agents.llm_tools import reply_schema


def request_key(request: dict[str, Any]) -> str:
    """The messages, exactly -- what a recorded reply is looked up by."""
    return hashlib.sha256(json.dumps(request["messages"], sort_keys=True).encode("utf-8")).hexdigest()


def served_digest(endpoint: str, model: str) -> str | None:
    """The digest the server at `endpoint` holds for `model`; None if it does not hold it."""
    import ollama
    for m in ollama.Client(host=endpoint).list()["models"]:
        name = m["model"] if "model" in m else m.get("name")
        if name == model:
            return m["digest"]
    return None


class OllamaAsk:
    """The pinned model on an Ollama server (`LLMConfig`), with a timeout, one call at a time."""

    def __init__(self, model: str, endpoint: str, options: dict[str, Any], timeout_s: float) -> None:
        import ollama
        self.model, self.endpoint, self.options = model, endpoint, dict(options)
        self.client = ollama.Client(host=endpoint, timeout=timeout_s)
        self._lock = threading.Lock()

    def __call__(self, request: dict[str, Any]) -> str:
        with self._lock:
            response = self.client.chat(model=self.model, messages=request["messages"], format=reply_schema(),
                                        options=self.options)
        return response["message"]["content"]


class EchoAsk:
    """Answers what the rule policy would have chosen. With it, an LLM-policy flight must be the rule team's."""

    def __call__(self, request: dict[str, Any]) -> str:
        return request["meta"]["rule_reply"]


class ReplayAsk:
    """Answers each request with the reply recorded for exactly those messages; anything else is an error."""

    def __init__(self, records: dict[str, list[str]]) -> None:
        self.records = {k: list(v) for k, v in records.items()}
        self._lock = threading.Lock()

    def __call__(self, request: dict[str, Any]) -> str:
        key = request_key(request)
        with self._lock:
            replies = self.records.get(key)
            if not replies:
                raise LookupError(f"no recorded reply for request {key[:16]}: the flight has left its record")
            return replies.pop(0)


class Recorder:
    """Wraps an ask; keeps every (request key, reply) in order, for `ReplayAsk`."""

    def __init__(self, ask: Any) -> None:
        self.ask = ask
        self.records: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def __call__(self, request: dict[str, Any]) -> str:
        reply = self.ask(request)
        with self._lock:
            self.records.setdefault(request_key(request), []).append(reply)
        return reply
