"""Plain data container for one validated action in a plan."""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class SkillCommand:
    """One step of a plan, after validate_plan() has confirmed it's safe to run."""
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
