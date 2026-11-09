# NAVRL_PROFILE=<name> loads a named set of NAVRL_* settings (configs/navrl_profiles.json) before anything below reads them.
from .navrl_profile import apply_profile as _apply_navrl_profile

_apply_navrl_profile()
