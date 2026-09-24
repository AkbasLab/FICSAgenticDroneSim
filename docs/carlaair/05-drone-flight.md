# Drone Flight

The AirSim side: arming, taking off, flying by high-level commands, and low-level control. Read the NED warning before writing any flight code.

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. Generated from *CarlaAir Command Reference v1.0*; edit that manual and
> regenerate rather than editing this file.

---

## Flying the drone

### Connect, arm, take off, land

```python
import airsim
c = airsim.MultirotorClient("127.0.0.1", 41451)
c.confirmConnection()

c.enableApiControl(True)      # take control from the simulator
c.armDisarm(True)             # spin up

c.takeoffAsync().join()
c.moveToZAsync(-30, 3).join() # climb to 30 m -- NED, so z is negative
c.hoverAsync().join()
c.landAsync().join()

c.armDisarm(False)
c.enableApiControl(False)     # always give control back
```

> **Important**
>
> **NED — Z is down**
> Altitude is **negative**. 30 metres up is `z = -30`. A positive Z
> drives the aircraft into the ground.

### Movement commands

| **Method** | **Use** |
|---|---|
| `moveToPositionAsync(x,y,z,v)` | Fly to an absolute point at speed `v` |
| `moveToZAsync(z,v)` | Change altitude only |
| `moveOnPathAsync(path,v)` | Follow a list of `Vector3r` waypoints |
| `moveByVelocityAsync(vx,vy,vz,t)` | World-frame velocity for `t` seconds |
| `moveByVelocityBodyFrameAsync(...)` | **Body**-frame velocity — forward is relative to heading |
| `moveByVelocityZAsync(...)` | Horizontal velocity, altitude held |
| `rotateToYawAsync(deg)` | Turn to an absolute heading |
| `rotateByYawRateAsync(rate,t)` | Spin at a rate |
| `hoverAsync()` | Stop and hold position |
| `goHomeAsync()` | Return to the launch point |
| `moveToGPSAsync(lat,lon,alt,v)` | Fly to a GPS coordinate |
| `cancelLastTask()` | Abort the current movement |

> **Note**
>
> **Two behaviours that catch everyone**
> **Velocity commands do not brake.** They apply for their duration and then
> stop being applied; the aircraft coasts. Follow every velocity command with
> `hoverAsync()` if you want it to stop.
> 
> **`.join()` makes an async call blocking.** Without it the call returns
> immediately and your next line runs while the drone is still moving. That is
> occasionally what you want — it is how several drones fly at once — but it
> is rarely what you meant.

### Reading state

```python
s = c.getMultirotorState()
p = s.kinematics_estimated.position
v = s.kinematics_estimated.linear_velocity
print(p.x_val, p.y_val, p.z_val)
print(s.landed_state)             # Landed / Flying
print(airsim.to_eularian_angles(s.kinematics_estimated.orientation))

print(c.getImuData())
print(c.getGpsData())
print(c.getBarometerData())
print(c.getMagnetometerData())
print(c.getDistanceSensorData())
print(c.getLidarData())
print(c.simGetCollisionInfo())
print(c.getRotorStates())
```

### Multiple drones

Every call takes `vehicle_name`. Threads give you genuine concurrency:

```python
import threading

def fly(name):
    c.enableApiControl(True, vehicle_name=name)
    c.armDisarm(True, vehicle_name=name)
    c.takeoffAsync(vehicle_name=name).join()
    c.moveToZAsync(-25, 3, vehicle_name=name).join()
    c.landAsync(vehicle_name=name).join()

threads = [threading.Thread(target=fly, args=(n,)) for n in c.listVehicles()]
for t in threads: t.start()
for t in threads: t.join()
```

> **Careful**
>
> Stagger thread starts by about 0.25 s. Opening every RPC connection
> simultaneously makes some of them fail.

## Low-level flight control

The commands in the previous section go through AirSim's position and velocity
controllers. Below those sit attitude and motor commands.

| **Method** | **Level** |
|---|---|
| `moveByRollPitchYawZAsync(r,p,y,z,t)` | Attitude, altitude held |
| `moveByRollPitchYawThrottleAsync(...)` | Attitude plus throttle |
| `moveByRollPitchYawrateZAsync(...)` | Attitude with yaw *rate* |
| `moveByRollPitchYawrateThrottleAsync(...)` | Same, with throttle |
| `moveByAngleRatesZAsync(...)` | Body angular rates |
| `moveByAngleRatesThrottleAsync(...)` | Rates plus throttle |
| `moveByMotorPWMsAsync(fr,rl,fl,rr,t)` | **Raw motor PWM** — lowest level |
| `moveByManualAsync(...)` | Manual-mode envelope |
| `moveByRC(rcdata)` | Simulated radio-control input |

> **Important**
>
> These bypass the safety envelope of the higher-level controllers. Motor PWM
> commands in particular will happily flip or crash the aircraft. Use the
> position and velocity commands unless you are specifically studying control.

### Tuning the controllers

```text
c.setVelocityControllerGains(airsim.VelocityControllerGains(...))
c.setPositionControllerGains(airsim.PositionControllerGains(...))
c.setAngleLevelControllerGains(airsim.AngleLevelControllerGains(...))
c.setAngleRateControllerGains(airsim.AngleRateControllerGains(...))
```

### Teleporting and ground truth

```python
# Place the drone instantly, without flying it there
c.simSetVehiclePose(airsim.Pose(airsim.Vector3r(0, 0, -30),
                                airsim.to_quaternion(0, 0, 1.57)),
                    ignore_collision=True)
print(c.simGetVehiclePose())

# Exact simulator state, not the estimator's opinion
print(c.simGetGroundTruthKinematics())
print(c.simGetGroundTruthEnvironment())
print(c.getHomeGeoPoint())
```

> **Note**
>
> **Ground truth versus estimate**
> `getMultirotorState()` returns the *estimated* state, as an onboard
> sensor fusion would produce. `simGetGroundTruthKinematics()` returns what
> the simulator actually knows. For evaluating a navigation algorithm you want
> the first as input and the second as the reference.

### Drawing the flight path

```text
c.simSetTraceLine(color_rgba=[1.0, 0.0, 0.0, 1.0], thickness=8.0)
```
