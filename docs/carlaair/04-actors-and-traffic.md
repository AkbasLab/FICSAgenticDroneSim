# Actors and Traffic

Spawning and controlling vehicles and pedestrians, driving a car manually, and the traffic light system.

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. Generated from *CarlaAir Command Reference v1.0*; edit that manual and
> regenerate rather than editing this file.

---

## Adding agents

### The quickest route — the traffic generator

```powershell
conda activate carlaAir
cd D:\Research\CarlaAirSetup\CarlaAir-v0.1.7-Windows11-x86_64
python auto_traffic.py --vehicles 50 --walkers 80
```

| **Option** | **Short** | **Default** |
|---|---|---|
| `--vehicles` | `-n` | 30 |
| `--walkers` | `-w` | 50 |
| `--port` | `-p` | 2000 |
| `--tm-port` | — | 8000 |

The launcher runs this automatically unless you pass `--no-traffic`.

### Spawning a vehicle by hand

```text
bp_lib = world.get_blueprint_library()
spawns = world.get_map().get_spawn_points()

bp = bp_lib.find("vehicle.tesla.model3")
bp.set_attribute("color", "255,0,0")

vehicle = world.spawn_actor(bp, spawns[0])        # raises if blocked
vehicle = world.try_spawn_actor(bp, spawns[0])    # returns None if blocked

vehicle.set_autopilot(True, 8000)                 # hand it to the traffic manager
```

### Finding blueprints

```python
for bp in bp_lib.filter("vehicle.*"):   print(bp.id)
for bp in bp_lib.filter("walker.pedestrian.*"): print(bp.id)
for bp in bp_lib.filter("sensor.*"):    print(bp.id)
print(bp_lib.find("vehicle.audi.tt").get_attribute("color").recommended_values)
```

### Spawning many vehicles at once

`apply_batch_sync` is far faster than a loop of `spawn_actor`, because
it is one round trip instead of N:

```python
import random
SpawnActor  = carla.command.SpawnActor
SetAutopilot= carla.command.SetAutopilot
FutureActor = carla.command.FutureActor

batch = []
for sp in random.sample(spawns, 30):
    bp = random.choice(bp_lib.filter("vehicle.*"))
    batch.append(SpawnActor(bp, sp).then(SetAutopilot(FutureActor, True, 8000)))

ids = [r.actor_id for r in client.apply_batch_sync(batch, True) if not r.error]
print(len(ids), "vehicles spawned")
```

### Spawning pedestrians

Pedestrians need two actors: the walker, and an AI controller attached to it.

```text
walker_bp = random.choice(bp_lib.filter("walker.pedestrian.*"))
ctrl_bp   = bp_lib.find("controller.ai.walker")

loc   = world.get_random_location_from_navigation()
walker= world.spawn_actor(walker_bp, carla.Transform(loc))
ctrl  = world.spawn_actor(ctrl_bp, carla.Transform(), attach_to=walker)

ctrl.start()
ctrl.go_to_location(world.get_random_location_from_navigation())
ctrl.set_max_speed(1.4)                       # m/s
```

Two world-level knobs govern crowd behaviour:

```python
world.set_pedestrians_cross_factor(0.3)   # fraction willing to jaywalk
world.set_pedestrians_seed(42)            # reproducible crowds
```

### Adding drones at runtime

Drones normally come from `settings.json`, read only at process start. To
add one to a running simulation:

```python
c.simAddVehicle(vehicle_name="Drone2",
                vehicle_type="SimpleFlight",
                pose=airsim.Pose(airsim.Vector3r(4.0, 0.0, 0.0),
                                 airsim.to_quaternion(0, 0, 0)))
print(c.listVehicles())
```

Then address it by name on every call:

```text
c.enableApiControl(True, vehicle_name="Drone2")
c.armDisarm(True,        vehicle_name="Drone2")
c.takeoffAsync(vehicle_name="Drone2").join()
```

> **Careful**
>
> **Runtime spawning versus `settings.json`**
> A drone added with `simAddVehicle` exists only until the simulator
> restarts, and gets no camera configuration. Drones declared in
> `settings.json` persist and carry their cameras — but that file is read
> only at startup, so changing it means restarting the simulator. Use
> `settings.json` for the fleet you always want and `simAddVehicle` for
> ad-hoc additions.

### Traffic Manager — shaping how the traffic behaves

```text
tm = client.get_trafficmanager(8000)
tm.set_global_distance_to_leading_vehicle(2.5)
tm.global_percentage_speed_difference(-20)      # negative = faster than the limit
tm.set_random_device_seed(42)                   # reproducible traffic
tm.set_hybrid_physics_mode(True)                # physics only near the ego vehicle
tm.set_hybrid_physics_radius(70.0)

tm.ignore_lights_percentage(vehicle, 50)        # per-vehicle recklessness
tm.auto_lane_change(vehicle, False)
tm.distance_to_leading_vehicle(vehicle, 4.0)
tm.vehicle_percentage_speed_difference(vehicle, 30)
tm.set_desired_speed(vehicle, 12.0)             # m/s
```

| **Global** | **Per vehicle** |
|---|---|
| `set_global_distance_to_leading_vehicle` | `distance_to_leading_vehicle` |
| `global_percentage_speed_difference` | `vehicle_percentage_speed_difference` |
| `global_lane_offset` | `vehicle_lane_offset` |
| `set_random_device_seed` | `ignore_lights_percentage` |
| `set_synchronous_mode` | `ignore_signs_percentage` |
| `set_hybrid_physics_mode` | `ignore_vehicles_percentage` |
| `set_hybrid_physics_radius` | `ignore_walkers_percentage` |
| `set_respawn_dormant_vehicles` | `auto_lane_change` |
| `update_vehicle_lights` | `force_lane_change` |
| `set_osm_mode` | `set_path` / `set_route` |
| `shut_down` | `set_desired_speed` |

### Listing and removing actors

```python
for a in world.get_actors():
    print(a.id, a.type_id)

print(len(world.get_actors().filter("vehicle.*")), "vehicles")
print(len(world.get_actors().filter("walker.*")),  "pedestrians")

world.get_actor(actor_id).destroy()

# Remove everything at once
client.apply_batch([carla.command.DestroyActor(a)
                    for a in world.get_actors().filter("vehicle.*")])
```

## Driving vehicles manually

`set_autopilot(True)` hands a vehicle to the traffic manager. To drive it
yourself, apply control every frame instead.

### Standard control

```python
ctrl = carla.VehicleControl()
ctrl.throttle          = 0.6      # 0.0 -- 1.0
ctrl.steer             = -0.2     # -1.0 (full left) -- 1.0 (full right)
ctrl.brake             = 0.0      # 0.0 -- 1.0
ctrl.hand_brake        = False
ctrl.reverse           = False
ctrl.manual_gear_shift = False
ctrl.gear              = 1
vehicle.apply_control(ctrl)

print(vehicle.get_control())
```

> **Careful**
>
> Control persists until replaced. Apply it once and the vehicle keeps that
> throttle indefinitely. A driving loop should call `apply_control` every
> tick.

### Ackermann control — speed instead of throttle

Easier for path following, because you ask for a speed rather than a pedal
position:

```text
vehicle.apply_ackermann_controller_settings(
    carla.AckermannControllerSettings(speed_kp=0.15, speed_ki=0.0, speed_kd=0.25,
                                      accel_kp=0.01, accel_ki=0.0, accel_kd=0.01))

vehicle.apply_ackermann_control(
    carla.VehicleAckermannControl(steer=0.0, steer_speed=0.5,
                                  speed=12.0, acceleration=1.0, jerk=0.5))
```

### Reading the vehicle

```python
print(vehicle.get_location(), vehicle.get_transform())
print(vehicle.get_velocity(), vehicle.get_acceleration())
print(vehicle.get_angular_velocity())
print(vehicle.get_speed_limit())              # km/h for the current road
print(vehicle.is_at_traffic_light())
print(vehicle.get_traffic_light_state())
print(vehicle.get_failure_state())
print(vehicle.get_wheel_steer_angle(carla.VehicleWheelLocation.FL_Wheel))
```

### Lights and doors

```python
vehicle.set_light_state(carla.VehicleLightState(
    carla.VehicleLightState.LowBeam | carla.VehicleLightState.RightBlinker))
print(vehicle.get_light_state())

vehicle.open_door(carla.VehicleDoor.FL)
vehicle.close_door(carla.VehicleDoor.All)
```

Light flags: `NONE`, `Position`, `LowBeam`, `HighBeam`,
`Brake`, `RightBlinker`, `LeftBlinker`, `Reverse`, `Fog`,
`Interior`, `Special1`, `Special2`, `All`.
Doors: `FL`, `FR`, `RL`, `RR`, `All`.

### Physics

```python
pc = vehicle.get_physics_control()
print(pc.mass, pc.max_rpm, pc.drag_coefficient, pc.center_of_mass)
pc.mass = 1600.0
pc.drag_coefficient = 0.28
vehicle.apply_physics_control(pc)

vehicle.set_simulate_physics(False)     # kinematic only -- much cheaper
vehicle.enable_constant_velocity(carla.Vector3D(10, 0, 0))
vehicle.disable_constant_velocity()
vehicle.show_debug_telemetry(True)
print(vehicle.get_telemetry_data())
```

### Driving a pedestrian by hand

```text
wc = carla.WalkerControl()
wc.direction = carla.Vector3D(1.0, 0.0, 0.0)   # unit vector
wc.speed     = 1.4                             # m/s
wc.jump      = False
walker.apply_control(wc)
```

This replaces the AI controller — use one or the other, not both.

## Traffic lights

```python
lights = world.get_actors().filter("traffic.traffic_light*")

for tl in lights:
    print(tl.id, tl.get_state(), tl.get_green_time(), tl.get_red_time())

tl = lights[0]
tl.set_state(carla.TrafficLightState.Green)
tl.set_green_time(20.0)
tl.set_yellow_time(3.0)
tl.set_red_time(10.0)
tl.freeze(True)                     # hold this state indefinitely
print(tl.is_frozen(), tl.get_elapsed_time())
```

States: `Red`, `Yellow`, `Green`, `Off`, `Unknown`.

### Whole-city control

```python
world.freeze_all_traffic_lights(True)    # every light holds its state
world.reset_all_traffic_lights()         # back to normal cycling
```

### Junction groups and affected lanes

Lights at one junction form a group that cycles together:

```python
group = tl.get_group_traffic_lights()
tl.reset_group()

print(tl.get_pole_index(), tl.get_opendrive_id())
for wp in tl.get_stop_waypoints():        print(wp.transform.location)
for wp in tl.get_affected_lane_waypoints(): print(wp.lane_id)

print(world.get_traffic_lights_in_junction(junction_id))
print(world.get_traffic_light_from_opendrive_id("123"))
```

> **Note**
>
> **Useful for experiments**
> `freeze_all_traffic_lights(True)` removes a large source of run-to-run
> variance. Combined with `tm.set_random_device_seed()` and synchronous mode,
> it is most of what you need for a reproducible traffic scenario.
