"""Smoke test for validate_plan() - no simulator, no LLM, just the four checks
Arshad reasoned through: known action, required params, numeric, positive."""

from fics_drone.planners.base_planner import PlanError, validate_plan


def test_known_good_plan_passes():
    commands = validate_plan([
        {"action": "hover", "params": {"duration": 2.0}},
        {"action": "land", "params": {}},
    ])
    assert len(commands) == 2
    assert commands[0].action == "hover"
    assert commands[0].params["duration"] == 2.0
    assert commands[1].action == "land"
    print("  ok    known-good plan validates")


def test_unknown_action_rejected():
    try:
        validate_plan([{"action": "fly_upward", "params": {"seconds": 5}}])
        assert False, "should have raised PlanError"
    except PlanError as e:
        assert "unknown action" in str(e)
        print("  ok    unknown action rejected, before params are even checked")


def test_missing_param_rejected():
    try:
        validate_plan([{"action": "fly_to", "params": {"x": 0.0, "y": 0.0}}])  # missing z
        assert False, "should have raised PlanError"
    except PlanError as e:
        assert "missing 'z'" in str(e)
        print("  ok    missing required param rejected")


def test_non_positive_duration_rejected():
    try:
        validate_plan([{"action": "hover", "params": {"duration": -1.0}}])
        assert False, "should have raised PlanError"
    except PlanError as e:
        assert "must be positive" in str(e)
        print("  ok    non-positive duration rejected")


def test_empty_plan_rejected():
    try:
        validate_plan([])
        assert False, "should have raised PlanError"
    except PlanError:
        print("  ok    empty plan rejected")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)} passed, 0 failed")
