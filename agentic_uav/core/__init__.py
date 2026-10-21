"""Plain data shared by every layer. No simulator, no model, no I/O.

`clock` (Phase 3) is the one exception to "plain data": the real and the
simulated time every skill measures its timeout and its result against.
"""

from .clock import Clock, RealClock, SimClock  # noqa: F401
from .models import (  # noqa: F401
    CollisionInfo,
    Position,
    PrimitiveCommand,
    PrimitiveKind,
    PrimitiveResult,
    VehicleState,
)
