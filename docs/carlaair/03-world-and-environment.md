# World and Environment

Weather, time of day, street lighting, and querying the static scene — everything about the world that is not an actor.

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. Generated from *CarlaAir Command Reference v1.0*; edit that manual and
> regenerate rather than editing this file.

---

## Weather and time of day

### CARLA presets — all 23

```python
world.set_weather(carla.WeatherParameters.WetCloudySunset)
print(world.get_weather())
```

| 4@l**`carla.WeatherParameters.<name>`** |  |  |  |
|---|---|---|---|
| `Default` | `ClearNoon` | `ClearSunset` | `ClearNight` |
| `CloudyNoon` | `CloudySunset` | `CloudyNight` | `WetNoon` |
| `WetSunset` | `WetNight` | `WetCloudyNoon` | `WetCloudySunset` |
| `WetCloudyNight` | `SoftRainNoon` | `SoftRainSunset` | `SoftRainNight` |
| `MidRainyNoon` | `MidRainSunset` | `MidRainyNight` | `HardRainNoon` |
| `HardRainSunset` | `HardRainNight` | `DustStorm` |  |

### CARLA weather, tuned by hand

```python
w = carla.WeatherParameters(
        cloudiness=80.0, precipitation=60.0, precipitation_deposits=70.0,
        wind_intensity=40.0, sun_azimuth_angle=120.0, sun_altitude_angle=25.0,
        fog_density=10.0, fog_distance=60.0, wetness=50.0)
world.set_weather(w)
```

| **Field** | **Range and meaning** |
|---|---|
| `cloudiness` | 0--100 |
| `precipitation` | 0--100, rain intensity |
| `precipitation_deposits` | 0--100, puddles on the ground |
| `wind_intensity` | 0--100 |
| `sun_azimuth_angle` | 0--360, sun compass bearing |
| `sun_altitude_angle` | -90--90; negative is night |
| `fog_density` | 0--100 |
| `fog_distance` | metres before fog starts |
| `fog_falloff` | fog density falloff with height |
| `wetness` | 0--100, surface wetness |
| `dust_storm` | 0--100 |
| `scattering_intensity`, `mie_scattering_scale`, `rayleigh_scattering_scale` | atmospheric scattering |

### AirSim weather — affects the drone's view

AirSim has its own weather layer, which must be enabled first:

```text
c.simEnableWeather(True)
c.simSetWeatherParameter(airsim.WeatherParameter.Rain,        0.6)
c.simSetWeatherParameter(airsim.WeatherParameter.Fog,         0.3)
c.simSetWeatherParameter(airsim.WeatherParameter.Snow,        0.0)
c.simSetWeatherParameter(airsim.WeatherParameter.Roadwetness, 0.8)
```

Values run 0.0--1.0. Available parameters: `Rain`, `Roadwetness`,
`Snow`, `RoadSnow`, `MapleLeaf`, `RoadLeaf`, `Dust`,
`Fog`, `Enabled`.

### Time of day and wind

```text
c.simSetTimeOfDay(True, start_datetime="2026-09-15 18:30:00",
                  celestial_clock_speed=1, update_interval_secs=60, move_sun=True)

c.simSetWind(airsim.Vector3r(5.0, 0.0, 0.0))   # 5 m/s wind blowing north
```

## Street lights and appearance

### The light manager

Every street lamp, building light and vehicle light in the city is addressable.

```python
lm = world.get_lightmanager()

lights = lm.get_all_lights(carla.LightGroup.Street)
print(len(lights), "street lights")

lm.turn_on(lights)
lm.turn_off(lights)
lm.set_intensity(lights, 2000.0)
lm.set_color(lights, carla.Color(255, 180, 80))
lm.set_day_night_cycle(False)          # stop lights reacting to the sun
```

| **Method** | **Effect** |
|---|---|
| `get_all_lights(group)` | Every light in a group |
| `get_turned_on_lights(g)` / `get_turned_off_lights(g)` | Filtered by state |
| `turn_on(lights)` / `turn_off(lights)` | Switch |
| `set_intensity` / `set_intensities` | One value, or one per light |
| `set_color` / `set_colors` | Colour |
| `set_light_group` / `set_light_groups` | Reassign group |
| `set_light_state` / `set_light_states` | Everything at once |
| `set_day_night_cycle(bool)` | Automatic switching with the sun |
| `is_active` / `set_active` | Query or set activation |

Light groups: `Street`, `Building`, `Vehicle`, `Other`,
`NONE`.

### Retexturing objects

```python
print(world.get_names_of_all_objects()[:20])

world.apply_color_texture_to_object("Building_01",
        carla.MaterialParameter.Diffuse, texture)
world.apply_color_texture_to_objects(["Road_01","Road_02"],
        carla.MaterialParameter.Diffuse, texture)
```

### Environment objects

Static scenery — buildings, poles, fences — can be hidden individually,
which is a cheap way to simplify a scene:

```python
objs = world.get_environment_objects(carla.CityObjectLabel.Buildings)
for o in objs[:5]:
    print(o.id, o.name, o.type, o.bounding_box)

world.enable_environment_objects([o.id for o in objs], False)   # hide them
```

`carla.CityObjectLabel` includes `Buildings`, `Fences`,
`Poles`, `RoadLines`, `Roads`, `Sidewalks`, `Vegetation`,
`Walls`, `TrafficSigns`, `Bridge`, `GuardRail`, `Ground`,
`Static`, `Dynamic`, `Car`, `Bus`, `Bicycle`,
`Motorcycle`, `Any`, `NONE`.

## Scene objects and world queries

### AirSim: listing, spawning and moving objects

```python
print(c.simListSceneObjects(".*"))          # regex over everything in the level
print(c.simListAssets())                    # what can be spawned

c.simSpawnObject(object_name="Marker_A", asset_name="Cube",
                 pose=airsim.Pose(airsim.Vector3r(10, 0, -5)),
                 scale=airsim.Vector3r(1, 1, 1),
                 physics_enabled=False, is_blueprint=False)

c.simSetObjectPose("Marker_A", airsim.Pose(airsim.Vector3r(20, 0, -5)), teleport=True)
c.simSetObjectScale("Marker_A", airsim.Vector3r(2, 2, 2))
print(c.simGetObjectPose("Marker_A"))
print(c.simGetObjectScale("Marker_A"))

c.simSetObjectMaterial("Marker_A", "MyMaterial")
c.simSetObjectMaterialFromTexture("Marker_A", "D:/textures/target.png")
c.simSwapTextures("targetmesh", tex_id=1)
c.simSetLightIntensity("StreetLight_03", 4000.0)

c.simDestroyObject("Marker_A")
```

> **Note**
>
> **Spawned objects are how you place mission targets**
> For a search mission, spawn a distinctly named object, add its name to the
> camera's detection filter, and the drone can genuinely find it. No perception
> model required.

### CARLA: ray casting and projection

```python
# What does a ray hit between two points?
for hit in world.cast_ray(carla.Location(0, 0, 50), carla.Location(0, 0, 0)):
    print(hit.label, hit.location)

# Drop a point onto the first surface below it
lp = world.project_point(carla.Location(30, 20, 50),
                         carla.Vector3D(0, 0, -1), search_distance=100.0)

gp = world.ground_projection(carla.Location(30, 20, 50), search_distance=100.0)
print(gp.location, gp.label)
```

These are the CARLA equivalent of a line-of-sight test, and the practical way to
find ground height at an arbitrary coordinate.

### Bounding boxes of everything

```python
boxes = world.get_level_bbs(carla.CityObjectLabel.Buildings)
for b in boxes[:5]:
    print(b.location, b.extent)
    world.debug.draw_box(b, carla.Rotation(), 0.1,
                         carla.Color(0,255,0), life_time=30)
```

### World snapshots and callbacks

```python
snap = world.get_snapshot()
print(snap.frame, snap.timestamp.elapsed_seconds)
for actor_snap in snap:
    print(actor_snap.id, actor_snap.get_transform().location)

# Run a function on every server tick
def on_frame(snapshot):
    print("frame", snapshot.frame)

cb_id = world.on_tick(on_frame)
world.remove_on_tick(cb_id)

world.wait_for_tick()      # block until the next frame (asynchronous mode)
```

### Version and file utilities

```python
print(client.get_client_version(), client.get_server_version())
print(client.get_required_files())
client.set_files_base_folder("D:/Research/assets")
client.request_file("some_map.umap")
```
