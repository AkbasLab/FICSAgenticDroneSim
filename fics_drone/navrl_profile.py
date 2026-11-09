"""Named NavRL settings, read from configs/navrl_profiles.json, instead of eight loose environment switches.

Set NAVRL_PROFILE=<name> before starting Python. The profile's values are written into the environment only where
the variable is not already set, so an explicit NAVRL_* variable still wins. This runs when `fics_drone` is first
imported, before the modules that read those variables at import time (the guardian's tree margin, the agent's lane
inset). With no NAVRL_PROFILE nothing changes."""

import json
import os

PROFILES_PATH = os.path.join(os.path.dirname(__file__), "..", "configs", "navrl_profiles.json")


def apply_profile(name=None, environ=None, path=PROFILES_PATH):
    """Write the named profile's settings into `environ` (default os.environ) where unset. Returns what it set."""
    environ = os.environ if environ is None else environ
    name = name if name is not None else environ.get("NAVRL_PROFILE")
    if not name:
        return {}
    with open(path) as f:
        profiles = json.load(f)
    if name not in profiles:
        raise KeyError(f"NAVRL_PROFILE={name!r} is not in {os.path.normpath(path)}; known: {sorted(profiles)}")
    applied = {}
    for key, value in profiles[name].items():
        if key.startswith("_"):
            continue
        if key not in environ:
            environ[key] = str(value)
            applied[key] = str(value)
    return applied
