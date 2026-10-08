"""A real local model behind the same ModelBackend interface the scripted fake
implements - nothing else in the system changes to use it. Standard library
only (urllib), so there is no new dependency and the scripted default still
needs nothing installed.

Two properties make a run reproducible rather than anecdotal:
  * the model is identified by tag AND digest (a floating tag like
    "llama3.1:latest" names a moving target - someone re-running this in six
    months gets different weights from the same command), and
  * decoding is greedy (temperature 0) with a fixed seed.
`ModelCard.warnings()` says out loud when a run is not certifiable that way.

Decoding is also schema-constrained: Ollama is handed the JSON schema of the
decision contract, so "valid JSON in the wrong shape" is structurally hard to
produce. The strict validator in decision_schema.py still runs on every output
- constraining the decoder is a convenience, not a substitute for checking.
"""

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from typing import List, Optional

from .decision_schema import (COMMUNICATION_STATUS, CURRENT_RISK, MAX_OUTGOING_MESSAGES, MISSION_PROGRESS,
                              MODEL_MESSAGE_TYPES, REASON_CODES, decision_json)
from .llm_backends import BackendError, BackendTimeout, ModelBackend
from .llm_tools import ROLES, TOOLS

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_SEED = 17
MAX_NEW_TOKENS = 450   # one structured decision; 220 truncated answers that listed a message per teammate (unterminated JSON -> forced fallback), so the cap must clear the longest legitimate answer


def _enum(values):
    return {"type": "string", "enum": list(values)}


# Every one of the fifteen tools the contract can ever carry; which are LEGAL right now is the validator's call (and the
# prompt's menu), not the decoder's. Constraining the decoder is a convenience - the strict validator in
# decision_schema.py still runs on every output.
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "situation_assessment": {
            "type": "object",
            "properties": {"mission_progress": _enum(MISSION_PROGRESS),
                           "communication_status": _enum(COMMUNICATION_STATUS),
                           "current_risk": _enum(CURRENT_RISK)},
            "required": ["mission_progress", "communication_status", "current_risk"],
            "additionalProperties": False,
        },
        "selected_tool": _enum(t.name for t in TOOLS),
        "parameters": {
            "type": "object",
            # the union of every parameter any tool can take; WHICH tool takes which, and which VALUES are
            # valid right now, is the validator's call (decision_schema.parse_decision), not the decoder's
            "properties": {"reason_code": _enum(REASON_CODES), "x": {"type": "number"}, "y": {"type": "number"},
                           "task_id": {"type": "string"}, "target_id": {"type": "string"},
                           "new_role": _enum(ROLES),
                           "recipients": {"type": "array", "items": {"type": "string"}, "minItems": 1}},
            "required": ["reason_code"],
            "additionalProperties": False,
        },
        "outgoing_messages": {
            "type": "array", "maxItems": MAX_OUTGOING_MESSAGES,
            "items": {
                "type": "object",
                "properties": {
                    "message_type": _enum(t.value for t in MODEL_MESSAGE_TYPES),
                    "recipients": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "payload": {"type": "object", "properties": {"reason_code": _enum(REASON_CODES)},
                                "required": ["reason_code"], "additionalProperties": False},
                },
                "required": ["message_type", "recipients", "payload"],
                "additionalProperties": False,
            },
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["situation_assessment", "selected_tool", "parameters", "outgoing_messages", "confidence"],
    "additionalProperties": False,
}


@dataclass
class ModelCard:
    backend: str
    model: str
    digest: Optional[str]
    temperature: float
    seed: int

    @property
    def is_pinned(self) -> bool:
        tag = self.model.split(":", 1)[1] if ":" in self.model else ""
        return bool(self.digest) and tag not in ("", "latest")

    def warnings(self) -> List[str]:
        out = []
        if not self.is_pinned:
            out.append(f"model {self.model!r} is not pinned (floating tag or unknown digest)")
        if self.temperature != 0.0:
            out.append(f"temperature {self.temperature} is not 0 - runs are not repeatable")
        return out

    def to_dict(self) -> dict:
        d = asdict(self)
        d["is_pinned"] = self.is_pinned
        d["warnings"] = self.warnings()
        return d


class OllamaBackend(ModelBackend):
    def __init__(self, model: str, host: str = DEFAULT_HOST, temperature: float = 0.0,
                 seed: int = DEFAULT_SEED):
        self.model = model
        self.host = host.rstrip("/")
        self.temperature = temperature
        self.seed = seed
        self._digest: Optional[str] = None

    # --- identity ---
    def card(self) -> ModelCard:
        if self._digest is None:
            try:
                tags = self._get("/api/tags", timeout_s=5.0)
                for m in tags.get("models", []):
                    if m.get("name") == self.model:
                        self._digest = m.get("digest", "")[:12]
            except (BackendError, BackendTimeout):
                pass
        return ModelCard("ollama", self.model, self._digest or None, self.temperature, self.seed)

    def warm_up(self, timeout_s: float = 120.0) -> float:
        """Load the model into memory before any drone is airborne, so the first real
        decision isn't a cold start that blows its time budget. Returns seconds taken."""
        import time
        start = time.monotonic()
        self.complete("Reply with exactly this JSON object: " + decision_json("return_home"), timeout_s)
        return time.monotonic() - start

    # --- ModelBackend ---
    def complete(self, prompt: str, timeout_s: float) -> str:
        body = {
            "model": self.model, "prompt": prompt, "stream": False, "format": DECISION_SCHEMA,
            "options": {"temperature": self.temperature, "seed": self.seed, "num_predict": MAX_NEW_TOKENS},
        }
        reply = self._post("/api/generate", body, timeout_s)
        text = reply.get("response")
        if not isinstance(text, str):
            raise BackendError("ollama reply had no 'response' text")
        return text

    # --- transport ---
    def _post(self, path: str, body: dict, timeout_s: float) -> dict:
        request = urllib.request.Request(self.host + path, data=json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
        return self._send(request, timeout_s)

    def _get(self, path: str, timeout_s: float) -> dict:
        return self._send(urllib.request.Request(self.host + path), timeout_s)

    @staticmethod
    def _send(request, timeout_s: float) -> dict:
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except socket.timeout:
            raise BackendTimeout(f"no reply within {timeout_s}s")
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, socket.timeout):
                raise BackendTimeout(f"no reply within {timeout_s}s")
            raise BackendError(f"ollama unreachable: {exc.reason}")
        except (OSError, ValueError) as exc:
            raise BackendError(f"bad ollama reply: {exc}")
