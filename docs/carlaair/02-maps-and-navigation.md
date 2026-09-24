# Maps and Navigation

The six towns, switching between them, and the road graph underneath them — waypoints, lanes, junctions and route planning.

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. Generated from *CarlaAir Command Reference v1.0*; edit that manual and
> regenerate rather than editing this file.

---

## Maps

### From the terminal

```powershell
.\CarlaAir.ps1 Town03
```

### From Python, without restarting

```python
print(client.get_available_maps())     # every map this build has
world = client.load_world("Town05")    # switch map, destroys all actors
world = client.reload_world()          # reload the current one
print(world.get_map().name)            # which map am I on?
```

| **Map** | **Character** | **Cost on 4 GB VRAM** |
|---|---|---|
| `Town01` | Small town, river, bridges | light |
| `Town02` | Smaller town | light |
| `Town03` | Large urban, roundabout, tunnel | moderate |
| `Town04` | Highway loop, mountains | moderate |
| `Town05` | Squared grid, multi-lane | moderate |
| `Town10HD` | High-detail city centre | heaviest |

### Layered maps — the `_Opt` variants

Every map also ships as `Town0N_Opt`. These load with layers you can add or
remove at runtime, which is the cheapest way to cut VRAM use:

```python
world = client.load_world("Town10HD_Opt", carla.MapLayer.NONE)   # bare roads only
world.load_map_layer(carla.MapLayer.Buildings)
world.load_map_layer(carla.MapLayer.Foliage)
world.unload_map_layer(carla.MapLayer.ParkedVehicles)
world.unload_map_layer(carla.MapLayer.Props)
```

| **Layer** | **Contents** |
|---|---|
| `NONE` / `All` | Nothing / everything |
| `Buildings` | Building meshes |
| `Decals` | Road markings, stains |
| `Foliage` | Trees, bushes, grass |
| `Ground` | Terrain |
| `ParkedVehicles` | Static parked cars |
| `Particles` | Particle effects |
| `Props` | Street furniture |
| `StreetLights` | Lamp posts and their lights |
| `Walls` | Walls and fences |

## Roads, waypoints and navigation

Every CARLA map carries an OpenDRIVE road network. Waypoints are how you place
anything sensibly on a road rather than guessing coordinates.

### The map object

```python
m = world.get_map()
print(m.name)
spawns = m.get_spawn_points()          # legal, collision-free start points
print(len(spawns))
```

| **Method** | **Returns** |
|---|---|
| `get_spawn_points()` | Recommended vehicle spawn transforms |
| `get_waypoint(location)` | Nearest waypoint on the road network |
| `get_waypoint_xodr(road, lane, s)` | Waypoint by OpenDRIVE identifiers |
| `generate_waypoints(distance)` | Waypoints every `distance` metres, whole map |
| `get_topology()` | List of (start, end) waypoint pairs — the road graph |
| `get_crosswalks()` | Crosswalk polygon points |
| `get_all_landmarks()` | Every signal and sign |
| `get_all_landmarks_of_type(t)` | Landmarks of one OpenDRIVE type |
| `get_all_road_marks()` | Every lane marking |
| `to_opendrive()` | The raw OpenDRIVE XML |
| `save_to_disk(path)` | Write the OpenDRIVE file out |
| `transform_to_geolocation(loc)` | World coordinates to lat/lon |
| `geolocation_to_transform(geo)` | Lat/lon to world coordinates |

### Walking the road network

```python
wp = m.get_waypoint(vehicle.get_location(),
                    project_to_road=True, lane_type=carla.LaneType.Driving)

print(wp.road_id, wp.lane_id, wp.s, wp.lane_width)
print(wp.is_junction, wp.lane_type, wp.lane_change)

nxt  = wp.next(5.0)                 # waypoints 5 m ahead (a list -- junctions branch)
prv  = wp.previous(5.0)
left = wp.get_left_lane()
right= wp.get_right_lane()

# Follow a lane to its end
path = wp.next_until_lane_end(2.0)
```

> **Note**
>
> **`next()` returns a list, not a waypoint**
> At a junction the road branches, so several waypoints are *next*. Taking
> `[0]` blindly is the usual source of a route that quietly turns the wrong
> way.

### Drawing a route

```python
wp = m.get_waypoint(vehicle.get_location())
for _ in range(200):
    world.debug.draw_point(wp.transform.location + carla.Location(z=0.3),
                           size=0.08, color=carla.Color(0,255,255), life_time=30)
    nxt = wp.next(2.0)
    if not nxt: break
    wp = nxt[0]
```

### Lane types and lane changes

| `carla.LaneType` | `Driving`, `Sidewalk`, `Shoulder`, `Biking`, `Parking`, `Border`, `Median`, `Restricted`, `Bidirectional`, `OnRamp`, `OffRamp`, `Entry`, `Exit`, `Any`, `NONE` |
|---|---|
| `carla.LaneChange` | `NONE`, `Left`, `Right`, `Both` |
| `carla.LaneMarkingType` | `Solid`, `Broken`, `SolidSolid`, `SolidBroken`, `BrokenSolid`, `BrokenBroken`, `BottsDots`, `Grass`, `Curb`, `Other`, `NONE` |

### Generating a map from OpenDRIVE

```text
xodr = open("my_road.xodr").read()
params = carla.OpendriveGenerationParameters(
            vertex_distance=2.0, max_road_length=500.0, wall_height=1.0,
            additional_width=0.6, smooth_junctions=True,
            enable_mesh_visibility=True, enable_pedestrian_navigation=True)
world = client.generate_opendrive_world(xodr, params)
```
