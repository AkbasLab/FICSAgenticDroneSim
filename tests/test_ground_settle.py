"""The ground reference must only be recorded once the drone has stopped moving.
No simulator: the adapter is built without __init__ and its two RPC reads are faked."""

from types import SimpleNamespace

import pytest

from fics_drone.simulator.airsim_adapter import AirSimVehicleAdapter


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, dt):
        self.t += dt


def make_adapter(clock, z_of_t, speed_of_t):
    a = AirSimVehicleAdapter.__new__(AirSimVehicleAdapter)
    a.vehicle_name = "Drone1"
    a._get_position_ned = lambda: SimpleNamespace(z_val=z_of_t(clock.now()))
    a.get_speed = lambda: speed_of_t(clock.now())
    return a


def test_waits_out_a_fall_and_records_the_final_ground():
    clock = FakeClock()
    # falling (speed 4 m/s, z shrinking toward 29.25) until t=3, then still
    z = lambda t: 29.25 if t >= 3 else 29.25 - 4.0 * (3 - t)
    speed = lambda t: 0.0 if t >= 3 else 4.0
    a = make_adapter(clock, z, speed)
    assert a._wait_until_settled(sleep=clock.sleep, clock=clock.now) == pytest.approx(29.25)


def test_a_drone_already_at_rest_settles_after_the_window():
    clock = FakeClock()
    a = make_adapter(clock, lambda t: 10.0, lambda t: 0.0)
    assert a._wait_until_settled(sleep=clock.sleep, clock=clock.now) == 10.0
    assert clock.now() >= 1.0  # it did not accept the very first sample


def test_slow_sink_without_speed_is_not_settled():
    """Speed under the threshold but z still creeping more than the drift limit
    must keep resetting the streak, then time out."""
    clock = FakeClock()
    a = make_adapter(clock, lambda t: 10.0 + 0.2 * t, lambda t: 0.1)
    with pytest.raises(TimeoutError):
        a._wait_until_settled(sleep=clock.sleep, clock=clock.now)


def test_never_settling_times_out_instead_of_recording_a_bad_ground():
    clock = FakeClock()
    a = make_adapter(clock, lambda t: 5.0, lambda t: 3.0)
    with pytest.raises(TimeoutError, match="never settled"):
        a._wait_until_settled(sleep=clock.sleep, clock=clock.now)
