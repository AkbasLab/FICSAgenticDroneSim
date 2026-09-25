# Sensors and Perception

Cameras and sensors on both the CARLA and AirSim sides, and what the simulator can tell you about visibility, detection and occupancy.

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. Generated from *CarlaAir Command Reference v1.0*; edit that manual and
> regenerate rather than editing this file.

---

## Cameras and sensors

### AirSim: capture from the drone

```python
import airsim, cv2, numpy as np

responses = c.simGetImages([
    airsim.ImageRequest("0", airsim.ImageType.Scene, False, False),
    airsim.ImageRequest("0", airsim.ImageType.DepthPlanar, True),
])

r   = responses[0]
img = np.frombuffer(r.image_data_uint8, dtype=np.uint8).reshape(r.height, r.width, 3)
cv2.imwrite("frame.png", img)
```

The three booleans on `ImageRequest` are, in order,
`camera`, `image_type`, `pixels_as_float` and `compress`.

| **`airsim.ImageType`** | **Gives you** |
|---|---|
| `Scene` | Normal colour image |
| `DepthPlanar` | Depth perpendicular to the camera plane |
| `DepthPerspective` | Depth along the view ray |
| `DepthVis` | Depth, visualised |
| `DisparityNormalized` | Normalised disparity |
| `Segmentation` | Per-object segmentation |
| `SurfaceNormals` | Surface normals |
| `Infrared` | Infrared |
| `OpticalFlow` | Optical flow |
| `OpticalFlowVis` | Optical flow, visualised |

Cameras are declared in `settings.json`. This installation defines two:
`"0"` and `"front_center"`, both at 1280×960.

### Camera control

```python
c.simSetCameraFov("0", 110)
c.simSetCameraPose("0", airsim.Pose(airsim.Vector3r(0.5, 0, 0.1),
                                    airsim.to_quaternion(-0.3, 0, 0)))
print(c.simGetCameraInfo("0"))
```

### CARLA sensors

CARLA sensors attach to an actor and deliver data through a callback:

```text
cam_bp = bp_lib.find("sensor.camera.rgb")
cam_bp.set_attribute("image_size_x", "800")
cam_bp.set_attribute("image_size_y", "600")
cam_bp.set_attribute("fov", "90")

cam = world.spawn_actor(cam_bp,
        carla.Transform(carla.Location(x=1.5, z=2.4)), attach_to=vehicle)

cam.listen(lambda image: image.save_to_disk("out/%06d.png" % image.frame))
# ...
cam.stop()
cam.destroy()
```

| **Blueprint** | **Produces** |
|---|---|
| `sensor.camera.rgb` | Colour images |
| `sensor.camera.depth` | Depth |
| `sensor.camera.semantic_segmentation` | Semantic labels |
| `sensor.camera.instance_segmentation` | Per-instance labels |
| `sensor.lidar.ray_cast` | 3-D point cloud |
| `sensor.lidar.ray_cast_semantic` | Labelled point cloud |
| `sensor.other.radar` | Radar detections |
| `sensor.other.gnss` | GPS |
| `sensor.other.imu` | Accelerometer and gyro |
| `sensor.other.collision` | Collision events |
| `sensor.other.lane_invasion` | Lane crossings |
| `sensor.other.obstacle` | Obstacle ahead |

## Perception: detection, visibility and occupancy

### Object detection from a camera

AirSim can return bounding boxes for named meshes visible to a camera. This is
ground-truth detection — no detector is run, the simulator simply reports what
is in view.

```python
CAM, TYPE = "0", airsim.ImageType.Scene

c.simSetDetectionFilterRadius(CAM, TYPE, 80 * 100)      # centimetres -- 80 m
c.simAddDetectionFilterMeshName(CAM, TYPE, "Car*")      # wildcards allowed
c.simAddDetectionFilterMeshName(CAM, TYPE, "Pedestrian*")

for d in c.simGetDetections(CAM, TYPE):
    print(d.name, d.box2D.min.x_val, d.box2D.min.y_val,
                  d.box2D.max.x_val, d.box2D.max.y_val)
    print("   relative position:", d.relative_pose.position)

c.simClearDetectionMeshNames(CAM, TYPE)
```

> **Note**
>
> **This is the shortest path to a seeing agent**
> It gives labelled, ranged detections without a vision model, without image
> transfer, and without GPU memory. For an agent that needs to know what is
> near me, this is far cheaper than captioning an image with a vision-language
> model — and the radius filter maps naturally onto a sensor range.

### Line of sight

```python
print(c.simTestLineOfSightToPoint(airsim.GeoPoint(47.641, -122.140, 120)))
print(c.simTestLineOfSightBetweenPoints(geo_a, geo_b))
print(c.simGetWorldExtents())      # the playable bounds of the map
```

Line-of-sight tests are how you model a communication link that buildings can
block — exactly the degraded-communications condition a multi-agent
experiment needs.

### Occupancy grid

```text
c.simCreateVoxelGrid(position=airsim.Vector3r(0, 0, 0),
                     x=200, y=200, z=100,     # extent in metres
                     res=1.0,                 # cell size in metres
                     of="D:/Research/occupancy.binvox")
```

Writes a binvox occupancy map of the world — the basis for any planner that
must avoid buildings.

### Segmentation identifiers

```python
c.simSetSegmentationObjectID("Road[\w]*", 22, True)   # regex over mesh names
print(c.simGetSegmentationObjectID("Road_01"))
```

Then capture with `airsim.ImageType.Segmentation` and each object appears in
the colour matching its identifier.

### Camera lens and focus

```python
c.simSetFocalLength(30.0, "0")
c.simEnableManualFocus(True, "0")
c.simSetFocusDistance(25.0, "0")
c.simSetFocusAperture(2.8, "0")
c.simEnableFocusPlane(True, "0")             # visualise the focal plane

print(c.simGetFilmbackSettings("0"))
print(c.simGetLensSettings("0"))
print(c.simGetPresetLensSettings("0"))
c.simSetPresetLensSettings("35mm Prime", "0")
print(c.simGetCurrentFieldOfView("0"))
print(c.simGetDistortionParams("0"))
c.simSetDistortionParam("0", "K1", 0.1)
```
