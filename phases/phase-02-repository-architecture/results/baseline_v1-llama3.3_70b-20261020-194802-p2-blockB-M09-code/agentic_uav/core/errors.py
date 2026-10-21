"""Exceptions shared across the layers."""


class PlanError(Exception):
    """A plan that cannot be flown safely or at all.

    Raised by the planner's validation and by the executor (`land` that did not
    land). Its NAME is part of the record -- flight failures are written as
    `PlanError: ...` -- so it is defined once, here, and never renamed.
    """
