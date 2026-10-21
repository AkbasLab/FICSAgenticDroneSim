"""Where planning calls go, and whether that place can be trusted.

The model may run on this laptop or on a GPU server reached by SSH tunnel. These
functions make the endpoint explicit, check before anything flies that it serves
exactly the model the record will name, and tell a dead network apart from a
model that answered badly.

Moved verbatim from `baseline/open_loop_agent.py` in Phase 2 step 4;
`tests/test_golden.py` proves every planning request and record is unchanged.
"""

from __future__ import annotations

import os
from typing import Any

MODEL = "llama3.2:3b"

# Where planning calls are sent. Ollama's own default is http://127.0.0.1:11434,
# and the library reads OLLAMA_HOST from the environment -- which is a trap when
# the model is meant to be running somewhere else, because a plan can come from
# a completely different machine than the data implies. So the endpoint is
# resolved once, here, and recorded with every planning call.
#
# For a remote model, point this at the local end of an SSH tunnel:
#
#     ssh -N -L 11435:gpu01:11434 user@vega.erau.edu
#     --ollama-host http://127.0.0.1:11435
#
# Deliberately NOT port 11434 for a tunnel: that is where a local Ollama
# listens, so if the tunnel dies the agent would silently fall back to whatever
# small model is installed locally and the results would be mislabelled.
OLLAMA_ENDPOINT = os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"


def is_transport_error(exc: BaseException) -> bool:
    """True if the endpoint was unreachable, rather than the model misbehaving.

    THE DISTINCTION IS NOT COSMETIC. plan_for() records any failure as an
    invalid plan, so without this a dropped network link lands in the
    `all_valid` column as the model having produced something unflyable. Over a
    VPN to a cluster that will happen, and it would quietly understate the
    model -- scoring our own connectivity as its failure.

    Classified by type rather than by message: ollama talks over httpx, so a
    dead endpoint surfaces as an httpx or httpcore exception, a socket error,
    or a plain ConnectionError depending on how it died. Matching on module and
    on the usual words in the class name covers those without importing httpx
    here, which matters because --plan-only has to work on a machine with a
    minimal install.
    """
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    module = type(exc).__module__.split(".")[0]
    if module in ("httpx", "httpcore", "socket", "ssl", "urllib3", "requests"):
        return True
    name = type(exc).__name__
    if any(word in name for word in
           ("Connect", "Timeout", "Transport", "Unreachable", "Protocol")):
        return True
    # OSError last: ConnectionError is a subclass, but so are unrelated file
    # errors, so this is a fallback rather than a first test.
    return isinstance(exc, OSError)


def normalise_endpoint(endpoint: str) -> str:
    """Accept `host:port` as well as a full URL, since both get typed."""
    endpoint = (endpoint or "").strip()
    if endpoint and "://" not in endpoint:
        endpoint = "http://" + endpoint
    return endpoint or "http://127.0.0.1:11434"


def server_version(endpoint: str = OLLAMA_ENDPOINT) -> str | None:
    """The Ollama server's own version string, or None if it cannot be read.

    Recorded with every series because the server is part of the apparatus and
    was previously invisible: the provenance named the ENDPOINT but not what was
    running there, so two blocks produced by different Ollama versions looked
    identical in the record. Found 2026-10-19, while upgrading 0.35.1 to 0.40.6
    between two sets of runs that are meant to be compared.

    Never fatal. A version that cannot be read is recorded as None, which is
    still better than a number nobody checked.
    """
    import json
    import urllib.request

    try:
        url = normalise_endpoint(endpoint).rstrip("/") + "/api/version"
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8")).get("version")
    except Exception:
        return None


class EndpointError(Exception):
    """The model endpoint is not usable. Raised before anything flies."""


def check_endpoint(model: str = MODEL,
                   endpoint: str = OLLAMA_ENDPOINT) -> dict[str, Any]:
    """Confirm the endpoint answers AND is serving the model we asked for.

    WHY THIS RUNS BEFORE EVERY SERIES
    ---------------------------------
    The failure it prevents is specific and silent. This laptop runs Ollama on
    port 11434 with a 3B model. A remote model is reached through an SSH tunnel
    on a different port. If that tunnel is not up -- or quietly died -- and the
    endpoint falls back to the default, planning calls are answered by the
    LOCAL 3B while every record still carries the model name that was
    requested. The plans would look plausible, the scores would compute, and
    the results would be wrong in a way nothing in the data could reveal.

    Checking that the model is PRESENT at the endpoint, rather than merely that
    something answered, is the whole point. "Something answered on 11434" is
    exactly what a dead tunnel looks like.

    Returns what it found, so the series can record it. Raises EndpointError
    rather than returning a flag, because flying a scored series against the
    wrong model is not a degraded run -- it is a worthless one, and it should
    stop before the first takeoff rather than after twenty-four of them.
    """
    import ollama

    endpoint = normalise_endpoint(endpoint)
    try:
        listing = ollama.Client(host=endpoint).list()
    except Exception as exc:
        raise EndpointError(
            "no model endpoint at {}: {}: {}".format(
                endpoint, type(exc).__name__, exc)
            + "\n  If this should be a remote model, is the SSH tunnel up?"
            + "\n    ssh -N -L 11435:<gpu-node>:11434 <user>@<cluster>"
        ) from exc

    # The ollama client returns objects in newer versions and plain dicts in
    # older ones, and this has to work on whatever is installed on the machine
    # flying the missions. So read both shapes rather than pinning a version.
    available = []
    entries = (listing.get("models", []) if isinstance(listing, dict)
               else getattr(listing, "models", []))
    for entry in entries:
        if isinstance(entry, dict):
            name = entry.get("model") or entry.get("name")
        else:
            name = getattr(entry, "model", None) or getattr(entry, "name", None)
        if name:
            available.append(name)

    # Ollama reports a fully qualified tag such as "llama3.3:70b", while a
    # config may name the family only. A bare family name is accepted as a
    # prefix, but NEVER the reverse: asking for llama3.3:70b must not be
    # satisfied by llama3.2:3b happening to be installed.
    if not any(name == model or name.startswith(model + ":") for name in available):
        raise EndpointError(
            "endpoint {} is answering, but does NOT serve {!r}.".format(endpoint, model)
            + "\n  available there: " + (", ".join(sorted(available)) or "(none)")
            + "\n  Refusing to fly: a different model would be recorded under"
            + "\n  the requested name. If this is a tunnel it may point at the"
            + "\n  wrong host, or have died leaving a local Ollama answering."
        )

    found = {"endpoint": endpoint, "model": model,
             "models_available": sorted(available)}
    print("endpoint: {} serving {}  ({} model(s) available)".format(
        endpoint, model, len(available)))
    return found
