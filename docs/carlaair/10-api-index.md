# API Index

Every public method of the principal classes, as installed. The method lists were produced by introspecting the modules on the reference machine, so nothing present in the build is missing here.

> Part of the CarlaAir reference set — see [`README.md`](README.md) for the
> index. Generated from *CarlaAir Command Reference v1.0*; edit that manual and
> regenerate rather than editing this file.

---

## Complete API index

Every public method of the six principal classes, as installed. The method
lists were produced by introspecting the modules on this machine, so nothing
present in the build is missing from this table.

### `carla.Client` — 25 methods

| **Method** | **Purpose** |
|---|---|
| `apply_batch` | Send many commands in one round trip, without waiting for results |
| `apply_batch_sync` | Same, but wait and return a result per command |
| `generate_opendrive_world` | Build a map at runtime from OpenDRIVE XML |
| `get_available_maps` | Every map this build ships |
| `get_client_version` | Client library version |
| `get_required_files` | Files the server expects the client to hold |
| `get_server_version` | Server version. A mismatch causes subtle, confusing failures |
| `get_trafficmanager` | Handle to the traffic manager on a given port (default 8000) |
| `get_world` | The current world object |
| `load_world` | Switch map. Destroys every actor |
| `load_world_if_different` | Switch only if not already on that map — avoids a needless reload |
| `reload_world` | Reload the current map, destroying all actors |
| `replay_file` | Play back a recording (file, start, duration, follow_id) |
| `request_file` | Download a file from the server |
| `set_files_base_folder` | Where requested files are written |
| `set_replayer_ignore_hero` | Do not replay the hero vehicle, so you can drive it live |
| `set_replayer_ignore_spectator` | Do not move the spectator camera during playback |
| `set_replayer_time_factor` | Playback speed multiplier |
| `set_timeout` | RPC timeout in seconds. Raise it on a slow machine |
| `show_recorder_actors_blocked` | Actors that stopped moving, from a recording |
| `show_recorder_collisions` | Collisions recorded in a file |
| `show_recorder_file_info` | Summary of a recording |
| `start_recorder` | Begin recording the whole world to a log |
| `stop_recorder` | Stop recording |
| `stop_replayer` | End playback |

### `carla.World` — 54 methods

| **Method** | **Purpose** |
|---|---|
| `apply_color_texture_to_object` | Paint one object with a colour texture |
| `apply_color_texture_to_objects` | Paint several objects at once |
| `apply_float_color_texture_to_object` | As above, with floating-point colour data |
| `apply_float_color_texture_to_objects` | Several objects, floating-point colour |
| `apply_settings` | Commit a WorldSettings object — synchronous mode, timestep, rendering |
| `apply_textures_to_object` | Apply a full texture set (diffuse, normal, ORM) to an object |
| `apply_textures_to_objects` | Apply a texture set to several objects |
| `cast_ray` | Every surface a ray crosses between two points |
| `debug` | The debug drawing helper (points, lines, boxes, strings) |
| `enable_environment_objects` | Show or hide static scenery by identifier |
| `export_cosmos_crosswalks` | Export crosswalk geometry in NVIDIA Cosmos format |
| `export_cosmos_lane_lines` | Export lane lines in Cosmos format |
| `export_cosmos_road_boundaries` | Export road boundaries in Cosmos format |
| `export_cosmos_road_markings` | Export road markings in Cosmos format |
| `export_cosmos_traffic_signs` | Export traffic signs in Cosmos format |
| `export_cosmos_wait_lines` | Export stop/wait lines in Cosmos format |
| `freeze_all_traffic_lights` | Hold every traffic light in its current state |
| `get_actor` | One actor by identifier |
| `get_actors` | Every actor; filter with `.filter("vehicle.*")` |
| `get_blueprint_library` | Everything that can be spawned |
| `get_environment_objects` | Static scenery, optionally filtered by CityObjectLabel |
| `get_imui_sensor_gravity` | Gravity constant used by the IMU sensor |
| `get_level_bbs` | Bounding boxes of every object of a given label |
| `get_lightmanager` | Handle to street, building and vehicle lights |
| `get_map` | The road network object |
| `get_names_of_all_objects` | Every nameable object in the level |
| `get_random_location_from_navigation` | A random point on the pedestrian navigation mesh |
| `get_settings` | Current WorldSettings |
| `get_snapshot` | A frozen frame: every actor's transform at one instant |
| `get_spectator` | The free camera actor |
| `get_traffic_light` | The traffic light governing a landmark |
| `get_traffic_light_from_opendrive_id` | Traffic light by its OpenDRIVE identifier |
| `get_traffic_lights_from_waypoint` | Lights affecting a waypoint within a distance |
| `get_traffic_lights_in_junction` | Every light in one junction |
| `get_traffic_sign` | The sign actor for a landmark |
| `get_vehicles_light_states` | Light state of every vehicle at once |
| `get_weather` | Current WeatherParameters |
| `ground_projection` | Drop a point onto the first surface below it |
| `id` | The world's identifier |
| `load_map_layer` | Add a layer to an `_Opt` map |
| `on_tick` | Register a callback run on every server frame; returns an id |
| `project_point` | Cast a point along a direction until it hits something |
| `remove_on_tick` | Unregister a tick callback |
| `reset_all_traffic_lights` | Return every light to normal cycling |
| `set_annotations_traverse_translucency` | Whether semantic annotation sees through glass |
| `set_imui_sensor_gravity` | Set the IMU gravity constant |
| `set_pedestrians_cross_factor` | Fraction of pedestrians willing to jaywalk |
| `set_pedestrians_seed` | Seed the pedestrian generator for reproducible crowds |
| `set_weather` | Apply a weather preset or a tuned WeatherParameters |
| `spawn_actor` | Create an actor; raises if the point is blocked |
| `tick` | Advance one step. Synchronous mode only |
| `try_spawn_actor` | Create an actor; returns None if the point is blocked |
| `unload_map_layer` | Remove a layer from an `_Opt` map — the cheapest VRAM saving |
| `wait_for_tick` | Block until the next frame. Asynchronous mode |

### `carla.Map` — 21 methods

| **Method** | **Purpose** |
|---|---|
| `cook_in_memory_map` | Pre-process the map into a binary cache for faster loads |
| `generate_waypoints` | Waypoints every N metres across the whole network |
| `geolocation_to_transform` | Latitude/longitude to world coordinates |
| `get_all_landmarks` | Every signal and sign in the network |
| `get_all_landmarks_from_id` | Landmarks sharing one OpenDRIVE identifier |
| `get_all_landmarks_of_type` | Landmarks of a single OpenDRIVE type |
| `get_all_road_marks` | Every lane marking |
| `get_all_road_marks_of_type` | Lane markings of one type |
| `get_crosswalks` | Crosswalk polygon vertices |
| `get_geoprojection` | The PROJ projection string for this map |
| `get_georeference` | The georeference header from the OpenDRIVE file |
| `get_landmark_group` | Landmarks that operate together, such as a signal group |
| `get_road_marks_from_id` | Road markings for one road identifier |
| `get_spawn_points` | Recommended, collision-free vehicle start transforms |
| `get_topology` | The road graph, as (start, end) waypoint pairs |
| `get_waypoint` | Nearest waypoint to a location |
| `get_waypoint_xodr` | Waypoint addressed by road, lane and s-offset |
| `name` | Map name |
| `save_to_disk` | Write the OpenDRIVE file out |
| `to_opendrive` | The OpenDRIVE XML as a string |
| `transform_to_geolocation` | World coordinates to latitude/longitude |

### `carla.TrafficManager` — 31 methods

| **Method** | **Purpose** |
|---|---|
| `auto_lane_change` | Allow or forbid a vehicle changing lane on its own |
| `collision_detection` | Enable or disable collision checks between two specific actors |
| `distance_to_leading_vehicle` | Following distance for one vehicle, in metres |
| `force_lane_change` | Force one vehicle left or right now |
| `get_all_actions` | The full planned action list for a vehicle |
| `get_next_action` | The next action a vehicle will take |
| `get_port` | Which port this traffic manager listens on |
| `global_lane_offset` | Shift every vehicle sideways within its lane |
| `global_percentage_speed_difference` | Global speed offset; negative is faster |
| `ignore_lights_percentage` | How often one vehicle runs a red light |
| `ignore_signs_percentage` | How often one vehicle ignores signs |
| `ignore_vehicles_percentage` | How often one vehicle ignores other vehicles |
| `ignore_walkers_percentage` | How often one vehicle ignores pedestrians |
| `keep_slow_lane_rule_percentage` | How strictly a vehicle keeps to the slow lane |
| `random_left_lanechange_percentage` | Chance of a spontaneous left lane change |
| `random_right_lanechange_percentage` | Chance of a spontaneous right lane change |
| `set_boundaries_respawn_dormant_vehicles` | Distance band in which dormant vehicles respawn |
| `set_desired_speed` | Target speed for one vehicle, in m/s |
| `set_global_distance_to_leading_vehicle` | Default following distance for all vehicles |
| `set_hybrid_physics_mode` | Full physics only near the ego vehicle — a large saving |
| `set_hybrid_physics_radius` | Radius within which full physics applies |
| `set_osm_mode` | Treat the map as imported OpenStreetMap data |
| `set_path` | Give one vehicle an explicit list of locations to follow |
| `set_random_device_seed` | Seed the traffic manager — required for reproducible runs |
| `set_respawn_dormant_vehicles` | Recycle vehicles that have gone dormant |
| `set_route` | Give one vehicle a sequence of turn decisions |
| `set_synchronous_mode` | Must match the world's synchronous mode or traffic desynchronises |
| `shut_down` | Stop this traffic manager |
| `update_vehicle_lights` | Let the traffic manager drive indicators and brake lights |
| `vehicle_lane_offset` | Sideways offset within the lane for one vehicle |
| `vehicle_percentage_speed_difference` | Speed offset for one vehicle |

### `carla.LightManager` — 20 methods

| **Method** | **Purpose** |
|---|---|
| `get_all_lights` | Every light, optionally filtered by group |
| `get_color` | Colour of the given lights |
| `get_intensity` | Intensity of the given lights |
| `get_light_group` | Which group each light belongs to |
| `get_light_state` | Full state (active, colour, intensity, group) |
| `get_turned_off_lights` | Lights currently off |
| `get_turned_on_lights` | Lights currently on |
| `is_active` | Whether each light is switched on |
| `set_active` | Switch lights on or off individually |
| `set_color` | One colour for all given lights |
| `set_colors` | A colour per light |
| `set_day_night_cycle` | Whether lights follow the sun automatically |
| `set_intensities` | An intensity per light |
| `set_intensity` | One intensity for all given lights |
| `set_light_group` | Reassign lights to a group |
| `set_light_groups` | A group per light |
| `set_light_state` | Set every property at once |
| `set_light_states` | A full state per light |
| `turn_off` | Switch off |
| `turn_on` | Switch on |

### `airsim.MultirotorClient` — 129 methods

| **Method** | **Purpose** |
|---|---|
| `armDisarm` | Arm or disarm the motors |
| `cancelLastTask` | Abort the movement currently running |
| `confirmConnection` | Block until the server answers; prints a banner |
| `enableApiControl` | Take control from the simulator, or hand it back |
| `getBarometerData` | Barometric altitude |
| `getClientVersion` | AirSim client library version |
| `getDistanceSensorData` | Distance sensor reading |
| `getGpsData` | GPS fix |
| `getHomeGeoPoint` | The launch point as latitude/longitude/altitude |
| `getImuData` | Accelerometer and gyroscope |
| `getLidarData` | Lidar point cloud |
| `getMagnetometerData` | Magnetometer |
| `getMinRequiredClientVersion` | Oldest client the server accepts |
| `getMinRequiredServerVersion` | Oldest server the client accepts |
| `getMultirotorState` | **Estimated** state — position, velocity, orientation, landed state |
| `getRotorStates` | Per-rotor speed, thrust and torque |
| `getServerVersion` | AirSim server version |
| `getSettingsString` | The settings.json the server actually loaded — the fastest way to prove which file was read |
| `goHomeAsync` | Return to the launch point |
| `hoverAsync` | Stop and hold position. The only way to brake a velocity command |
| `isApiControlEnabled` | Whether the script currently holds control |
| `isRecording` | Whether AirSim recording is running |
| `landAsync` | Controlled descent |
| `listVehicles` | Every vehicle name the server knows |
| `moveByAngleRatesThrottleAsync` | Body angular rates plus throttle |
| `moveByAngleRatesZAsync` | Body angular rates, altitude held |
| `moveByAngleThrottleAsync` | Pitch/roll angles plus throttle (deprecated form) |
| `moveByAngleZAsync` | Pitch/roll angles, altitude held (deprecated form) |
| `moveByManualAsync` | Manual-mode flight envelope |
| `moveByMotorPWMsAsync` | **Raw motor PWM** — no safety envelope |
| `moveByRC` | Simulated radio-control stick input |
| `moveByRollPitchYawThrottleAsync` | Attitude plus throttle |
| `moveByRollPitchYawZAsync` | Attitude with altitude held |
| `moveByRollPitchYawrateThrottleAsync` | Attitude with yaw rate, plus throttle |
| `moveByRollPitchYawrateZAsync` | Attitude with yaw rate, altitude held |
| `moveByVelocityAsync` | World-frame velocity for a duration |
| `moveByVelocityBodyFrameAsync` | Body-frame velocity — forward is relative to heading |
| `moveByVelocityZAsync` | World-frame horizontal velocity, altitude held |
| `moveByVelocityZBodyFrameAsync` | Body-frame horizontal velocity, altitude held |
| `moveOnPathAsync` | Follow a list of waypoints |
| `moveToGPSAsync` | Fly to a latitude/longitude/altitude |
| `moveToPositionAsync` | Fly to an absolute point at a given speed |
| `moveToZAsync` | Change altitude only. Remember Z is negative upward |
| `ping` | Round-trip check |
| `reset` | Return the vehicle to its start pose and clear state |
| `rotateByYawRateAsync` | Spin at a rate for a duration |
| `rotateToYawAsync` | Turn to an absolute heading |
| `setAngleLevelControllerGains` | PID gains for attitude hold |
| `setAngleRateControllerGains` | PID gains for angular rate |
| `setPositionControllerGains` | PID gains for position hold |
| `setVelocityControllerGains` | PID gains for velocity tracking |
| `simAddDetectionFilterMeshName` | Add a mesh name (wildcards allowed) to a camera's detection filter |
| `simAddVehicle` | Spawn a vehicle at runtime. Lost on restart, and it gets no cameras |
| `simClearDetectionMeshNames` | Empty a camera's detection filter |
| `simContinueForFrames` | While paused, advance exactly N frames |
| `simContinueForTime` | While paused, advance N seconds of simulated time |
| `simCreateVoxelGrid` | Write a binvox occupancy map of a region — the basis for obstacle-aware planning |
| `simDestroyObject` | Remove a spawned object |
| `simEnableFocusPlane` | Draw the focal plane, for setting up depth of field |
| `simEnableManualFocus` | Switch a camera from autofocus to manual |
| `simEnableWeather` | Master switch for AirSim's weather layer. Nothing happens until this is on |
| `simFlushPersistentMarkers` | Clear everything drawn by the simPlot calls |
| `simGetCameraInfo` | Pose, field of view and projection matrix of a camera |
| `simGetCollisionInfo` | Most recent collision — object, position, penetration depth |
| `simGetCurrentFieldOfView` | Current field of view in degrees |
| `simGetDetections` | **Ground-truth bounding boxes** for filtered meshes visible to a camera |
| `simGetDistortionParams` | Lens distortion coefficients |
| `simGetFilmbackSettings` | Sensor size settings |
| `simGetFocalLength` | Focal length in millimetres |
| `simGetFocusAperture` | Aperture (f-stop) |
| `simGetFocusDistance` | Manual focus distance |
| `simGetGroundTruthEnvironment` | True air density, pressure, temperature and gravity |
| `simGetGroundTruthKinematics` | **True** state — use this as the reference when evaluating an estimator |
| `simGetImage` | One image, returned compressed |
| `simGetImages` | Several images in one call — always prefer this to repeated simGetImage |
| `simGetLensSettings` | Current lens configuration |
| `simGetLidarSegmentation` | Per-point semantic labels for the last lidar scan |
| `simGetMeshPositionVertexBuffers` | Raw vertex buffers of scene meshes, for offline geometry work |
| `simGetObjectPose` | Pose of a named scene object |
| `simGetObjectScale` | Scale of a named scene object |
| `simGetPresetFilmbackSettings` | Available filmback presets |
| `simGetPresetLensSettings` | Available lens presets |
| `simGetSegmentationObjectID` | The segmentation identifier assigned to a mesh |
| `simGetVehiclePose` | Vehicle pose as the simulator holds it |
| `simGetWorldExtents` | The playable bounds of the level |
| `simIsPause` | Whether the simulation is paused |
| `simListAssets` | Every asset available to spawn |
| `simListSceneObjects` | Objects in the level, filtered by regular expression |
| `simLoadLevel` | Load a different level by name, without restarting the process |
| `simPause` | Freeze or resume the entire simulation |
| `simPlotArrows` | Draw arrows in the world |
| `simPlotLineList` | Draw disconnected line segments, in pairs |
| `simPlotLineStrip` | Draw a connected polyline |
| `simPlotPoints` | Draw points |
| `simPlotStrings` | Draw text at world positions |
| `simPlotTransforms` | Draw coordinate frames |
| `simPlotTransformsWithNames` | Draw coordinate frames with labels |
| `simPrintLogMessage` | Print into the simulator's on-screen log |
| `simRunConsoleCommand` | Run an Unreal console command such as `stat fps` |
| `simSetCameraFov` | Set a camera's field of view |
| `simSetCameraPose` | Move a camera relative to its vehicle |
| `simSetDetectionFilterRadius` | Detection range in **centimetres** |
| `simSetDistortionParam` | Set one distortion coefficient |
| `simSetDistortionParams` | Set all distortion coefficients at once |
| `simSetFilmbackSettings` | Set sensor width and height |
| `simSetFocalLength` | Set focal length in millimetres |
| `simSetFocusAperture` | Set aperture, which controls depth of field |
| `simSetFocusDistance` | Set manual focus distance |
| `simSetKinematics` | Force a vehicle's velocity and acceleration directly |
| `simSetLightIntensity` | Brightness of a named light in the level |
| `simSetObjectMaterial` | Assign a material to an object |
| `simSetObjectMaterialFromTexture` | Assign a material built from an image file |
| `simSetObjectPose` | Move a named object, optionally teleporting through geometry |
| `simSetObjectScale` | Resize a named object |
| `simSetPresetFilmbackSettings` | Apply a filmback preset |
| `simSetPresetLensSettings` | Apply a lens preset such as a 35mm prime |
| `simSetSegmentationObjectID` | Assign a segmentation identifier, optionally by regular expression |
| `simSetTimeOfDay` | Sun position, with an optional accelerated clock |
| `simSetTraceLine` | Draw the vehicle's flight path continuously |
| `simSetVehiclePose` | **Teleport** the vehicle to a pose |
| `simSetWeatherParameter` | One weather parameter, 0.0 to 1.0. Requires simEnableWeather first |
| `simSetWind` | Wind as a world-frame vector, in m/s |
| `simSpawnObject` | Spawn an asset into the level — how you place a mission target |
| `simSwapTextures` | Swap textures on objects carrying a tag |
| `simTestLineOfSightBetweenPoints` | Whether two points can see each other — models a blockable radio link |
| `simTestLineOfSightToPoint` | Whether the vehicle can see a point |
| `startRecording` | Begin AirSim's own recording |
| `stopRecording` | Stop it |
| `takeoffAsync` | Take off to the default hover height |

### `carla.Actor` — 44 members

| **Member** | **Purpose** |
|---|---|
| `actor_state` | Active, Dormant or Invalid |
| `add_angular_impulse` | Instantaneous change in angular momentum |
| `add_force` | Continuous force at the centre of mass, this frame |
| `add_force_at_location` | Continuous force applied at a point, so it also creates torque |
| `add_impulse` | Instantaneous change in linear momentum |
| `add_impulse_at_location` | Instantaneous impulse at a point |
| `add_torque` | Continuous torque this frame |
| `attributes` | The blueprint attributes this actor was created with |
| `bounding_box` | Local-space bounding box |
| `destroy` | Remove from the world. Always destroy sensors before exiting |
| `disable_constant_velocity` | Stop holding a fixed velocity |
| `disable_for_ros` | Stop publishing this actor on the ROS bridge |
| `enable_constant_velocity` | Hold a fixed velocity regardless of physics |
| `enable_for_ros` | Publish this actor on the ROS bridge |
| `get_acceleration` | Current acceleration vector |
| `get_angular_velocity` | Current angular velocity |
| `get_bone_names` | Skeleton bone names, for skeletal meshes |
| `get_bone_relative_transforms` | Bone transforms relative to the actor |
| `get_bone_world_transforms` | Bone transforms in world space |
| `get_component_names` | Names of the actor's Unreal components |
| `get_component_relative_transform` | One component's transform relative to the actor |
| `get_component_world_transform` | One component's transform in world space |
| `get_location` | World position |
| `get_socket_names` | Attachment socket names on the mesh |
| `get_socket_relative_transforms` | Socket transforms relative to the actor |
| `get_socket_world_transforms` | Socket transforms in world space |
| `get_transform` | Position and rotation together |
| `get_velocity` | Current linear velocity |
| `get_world` | The world this actor belongs to |
| `id` | Unique actor identifier |
| `is_active` | Whether the actor is simulating |
| `is_alive` | Whether it still exists on the server |
| `is_dormant` | Whether it has been put to sleep by distance culling |
| `is_enabled_for_ros` | Whether it is published on the ROS bridge |
| `parent` | The actor it is attached to, if any |
| `semantic_tags` | Semantic segmentation labels this actor carries |
| `set_collisions` | Enable or disable collision response |
| `set_enable_gravity` | Enable or disable gravity for this actor |
| `set_location` | Teleport to a position, keeping rotation |
| `set_simulate_physics` | Full physics, or kinematic only — kinematic is far cheaper |
| `set_target_angular_velocity` | Drive angular velocity directly, bypassing forces |
| `set_target_velocity` | Drive linear velocity directly, bypassing forces |
| `set_transform` | Teleport to a position and rotation |
| `type_id` | Blueprint identifier, such as `vehicle.tesla.model3` |

### `carla.Vehicle` — 72 members

Inherits the whole of `carla.Actor`; the members specific to this
class are marked in bold.

| **Member** | **Purpose** |
|---|---|
| `actor_state` | Active, Dormant or Invalid |
| `add_angular_impulse` | Instantaneous change in angular momentum |
| `add_force` | Continuous force at the centre of mass, this frame |
| `add_force_at_location` | Continuous force applied at a point, so it also creates torque |
| `add_impulse` | Instantaneous change in linear momentum |
| `add_impulse_at_location` | Instantaneous impulse at a point |
| `add_torque` | Continuous torque this frame |
| **`apply_ackermann_control`** | Command a speed and steering angle instead of pedals |
| **`apply_ackermann_controller_settings`** | PID gains for the Ackermann controller |
| **`apply_control`** | Apply throttle, steer, brake. Must be reapplied every tick |
| **`apply_physics_control`** | Commit a modified VehiclePhysicsControl |
| `attributes` | The blueprint attributes this actor was created with |
| `bounding_box` | Local-space bounding box |
| **`close_door`** | Close one door or all of them |
| `destroy` | Remove from the world. Always destroy sensors before exiting |
| `disable_constant_velocity` | Stop holding a fixed velocity |
| `disable_for_ros` | Stop publishing this actor on the ROS bridge |
| **`enable_carsim`** | Hand physics to the CarSim external solver |
| **`enable_chrono_physics`** | Hand physics to the Project Chrono solver |
| `enable_constant_velocity` | Hold a fixed velocity regardless of physics |
| `enable_for_ros` | Publish this actor on the ROS bridge |
| `get_acceleration` | Current acceleration vector |
| **`get_ackermann_controller_settings`** | Current Ackermann PID gains |
| `get_angular_velocity` | Current angular velocity |
| `get_bone_names` | Skeleton bone names, for skeletal meshes |
| `get_bone_relative_transforms` | Bone transforms relative to the actor |
| `get_bone_world_transforms` | Bone transforms in world space |
| `get_component_names` | Names of the actor's Unreal components |
| `get_component_relative_transform` | One component's transform relative to the actor |
| `get_component_world_transform` | One component's transform in world space |
| **`get_control`** | The control currently applied |
| **`get_failure_state`** | Rollover or other failure condition |
| **`get_light_state`** | Which lights are on |
| `get_location` | World position |
| **`get_physics_control`** | Mass, drag, gears, wheels, centre of mass |
| `get_socket_names` | Attachment socket names on the mesh |
| `get_socket_relative_transforms` | Socket transforms relative to the actor |
| `get_socket_world_transforms` | Socket transforms in world space |
| **`get_speed_limit`** | Speed limit of the current road, in km/h |
| **`get_telemetry_data`** | Detailed per-wheel telemetry |
| **`get_traffic_light`** | The light governing this vehicle |
| **`get_traffic_light_state`** | That light's current state |
| `get_transform` | Position and rotation together |
| **`get_vehicle_bone_world_transforms`** | Vehicle skeleton bones in world space |
| `get_velocity` | Current linear velocity |
| **`get_wheel_pitch_angle`** | Rolling angle of one wheel |
| **`get_wheel_steer_angle`** | Steering angle of one wheel |
| `get_world` | The world this actor belongs to |
| `id` | Unique actor identifier |
| `is_active` | Whether the actor is simulating |
| `is_alive` | Whether it still exists on the server |
| **`is_at_traffic_light`** | Whether it is stopped at a light |
| `is_dormant` | Whether it has been put to sleep by distance culling |
| `is_enabled_for_ros` | Whether it is published on the ROS bridge |
| **`open_door`** | Open one door or all of them |
| `parent` | The actor it is attached to, if any |
| **`restore_physx_physics`** | Return to the default physics solver |
| `semantic_tags` | Semantic segmentation labels this actor carries |
| **`set_autopilot`** | Hand the vehicle to the traffic manager |
| `set_collisions` | Enable or disable collision response |
| `set_enable_gravity` | Enable or disable gravity for this actor |
| **`set_light_state`** | Set headlights, indicators, brake lights |
| `set_location` | Teleport to a position, keeping rotation |
| `set_simulate_physics` | Full physics, or kinematic only — kinematic is far cheaper |
| `set_target_angular_velocity` | Drive angular velocity directly, bypassing forces |
| `set_target_velocity` | Drive linear velocity directly, bypassing forces |
| `set_transform` | Teleport to a position and rotation |
| **`set_wheel_pitch_angle`** | Force a wheel's rolling angle |
| **`set_wheel_steer_direction`** | Force a wheel's steering angle |
| **`show_debug_telemetry`** | Draw physics telemetry on screen |
| `type_id` | Blueprint identifier, such as `vehicle.tesla.model3` |
| **`use_carsim_road`** | Use CarSim's road surface rather than CARLA's |

### `carla.Walker` — 52 members

Inherits the whole of `carla.Actor`; the members specific to this
class are marked in bold.

| **Member** | **Purpose** |
|---|---|
| `actor_state` | Active, Dormant or Invalid |
| `add_angular_impulse` | Instantaneous change in angular momentum |
| `add_force` | Continuous force at the centre of mass, this frame |
| `add_force_at_location` | Continuous force applied at a point, so it also creates torque |
| `add_impulse` | Instantaneous change in linear momentum |
| `add_impulse_at_location` | Instantaneous impulse at a point |
| `add_torque` | Continuous torque this frame |
| **`apply_control`** | Direction, speed and jump. Replaces the AI controller |
| `attributes` | The blueprint attributes this actor was created with |
| **`blend_pose`** | Blend between a manual pose and the animation |
| `bounding_box` | Local-space bounding box |
| `destroy` | Remove from the world. Always destroy sensors before exiting |
| `disable_constant_velocity` | Stop holding a fixed velocity |
| `disable_for_ros` | Stop publishing this actor on the ROS bridge |
| `enable_constant_velocity` | Hold a fixed velocity regardless of physics |
| `enable_for_ros` | Publish this actor on the ROS bridge |
| `get_acceleration` | Current acceleration vector |
| `get_angular_velocity` | Current angular velocity |
| `get_bone_names` | Skeleton bone names, for skeletal meshes |
| `get_bone_relative_transforms` | Bone transforms relative to the actor |
| `get_bone_world_transforms` | Bone transforms in world space |
| **`get_bones`** | Current skeleton pose |
| `get_component_names` | Names of the actor's Unreal components |
| `get_component_relative_transform` | One component's transform relative to the actor |
| `get_component_world_transform` | One component's transform in world space |
| **`get_control`** | The walker control currently applied |
| `get_location` | World position |
| **`get_pose_from_animation`** | Copy the animation's current pose into the bone buffer |
| `get_socket_names` | Attachment socket names on the mesh |
| `get_socket_relative_transforms` | Socket transforms relative to the actor |
| `get_socket_world_transforms` | Socket transforms in world space |
| `get_transform` | Position and rotation together |
| `get_velocity` | Current linear velocity |
| `get_world` | The world this actor belongs to |
| **`hide_pose`** | Stop showing the manual pose |
| `id` | Unique actor identifier |
| `is_active` | Whether the actor is simulating |
| `is_alive` | Whether it still exists on the server |
| `is_dormant` | Whether it has been put to sleep by distance culling |
| `is_enabled_for_ros` | Whether it is published on the ROS bridge |
| `parent` | The actor it is attached to, if any |
| `semantic_tags` | Semantic segmentation labels this actor carries |
| **`set_bones`** | Drive the skeleton directly — for motion-capture playback |
| `set_collisions` | Enable or disable collision response |
| `set_enable_gravity` | Enable or disable gravity for this actor |
| `set_location` | Teleport to a position, keeping rotation |
| `set_simulate_physics` | Full physics, or kinematic only — kinematic is far cheaper |
| `set_target_angular_velocity` | Drive angular velocity directly, bypassing forces |
| `set_target_velocity` | Drive linear velocity directly, bypassing forces |
| `set_transform` | Teleport to a position and rotation |
| **`show_pose`** | Show the manually set pose |
| `type_id` | Blueprint identifier, such as `vehicle.tesla.model3` |

### `carla.TrafficLight` — 64 members

Inherits the whole of `carla.Actor`; the members specific to this
class are marked in bold.

| **Member** | **Purpose** |
|---|---|
| `actor_state` | Active, Dormant or Invalid |
| `add_angular_impulse` | Instantaneous change in angular momentum |
| `add_force` | Continuous force at the centre of mass, this frame |
| `add_force_at_location` | Continuous force applied at a point, so it also creates torque |
| `add_impulse` | Instantaneous change in linear momentum |
| `add_impulse_at_location` | Instantaneous impulse at a point |
| `add_torque` | Continuous torque this frame |
| `attributes` | The blueprint attributes this actor was created with |
| `bounding_box` | Local-space bounding box |
| `destroy` | Remove from the world. Always destroy sensors before exiting |
| `disable_constant_velocity` | Stop holding a fixed velocity |
| `disable_for_ros` | Stop publishing this actor on the ROS bridge |
| `enable_constant_velocity` | Hold a fixed velocity regardless of physics |
| `enable_for_ros` | Publish this actor on the ROS bridge |
| **`freeze`** | Hold the current state indefinitely |
| `get_acceleration` | Current acceleration vector |
| **`get_affected_lane_waypoints`** | Waypoints in the lanes this light governs |
| `get_angular_velocity` | Current angular velocity |
| `get_bone_names` | Skeleton bone names, for skeletal meshes |
| `get_bone_relative_transforms` | Bone transforms relative to the actor |
| `get_bone_world_transforms` | Bone transforms in world space |
| `get_component_names` | Names of the actor's Unreal components |
| `get_component_relative_transform` | One component's transform relative to the actor |
| `get_component_world_transform` | One component's transform in world space |
| **`get_elapsed_time`** | Seconds spent in the current state |
| **`get_green_time`** | Green phase duration |
| **`get_group_traffic_lights`** | The other lights at this junction |
| **`get_light_boxes`** | Bounding boxes of the individual lamp housings |
| `get_location` | World position |
| **`get_opendrive_id`** | The light's OpenDRIVE identifier |
| **`get_pole_index`** | Which pole in the junction group this is |
| **`get_red_time`** | Red phase duration |
| `get_socket_names` | Attachment socket names on the mesh |
| `get_socket_relative_transforms` | Socket transforms relative to the actor |
| `get_socket_world_transforms` | Socket transforms in world space |
| **`get_state`** | Red, Yellow, Green, Off or Unknown |
| **`get_stop_waypoints`** | Where vehicles stop for this light |
| `get_transform` | Position and rotation together |
| `get_velocity` | Current linear velocity |
| `get_world` | The world this actor belongs to |
| **`get_yellow_time`** | Yellow phase duration |
| `id` | Unique actor identifier |
| `is_active` | Whether the actor is simulating |
| `is_alive` | Whether it still exists on the server |
| `is_dormant` | Whether it has been put to sleep by distance culling |
| `is_enabled_for_ros` | Whether it is published on the ROS bridge |
| **`is_frozen`** | Whether the state is being held |
| `parent` | The actor it is attached to, if any |
| **`reset_group`** | Restart the whole junction's cycle |
| `semantic_tags` | Semantic segmentation labels this actor carries |
| `set_collisions` | Enable or disable collision response |
| `set_enable_gravity` | Enable or disable gravity for this actor |
| **`set_green_time`** | Set green phase duration |
| `set_location` | Teleport to a position, keeping rotation |
| **`set_red_time`** | Set red phase duration |
| `set_simulate_physics` | Full physics, or kinematic only — kinematic is far cheaper |
| **`set_state`** | Force a state |
| `set_target_angular_velocity` | Drive angular velocity directly, bypassing forces |
| `set_target_velocity` | Drive linear velocity directly, bypassing forces |
| `set_transform` | Teleport to a position and rotation |
| **`set_yellow_time`** | Set yellow phase duration |
| **`state`** | Current state as a property |
| **`trigger_volume`** | The box in which vehicles are considered affected |
| `type_id` | Blueprint identifier, such as `vehicle.tesla.model3` |

### `carla.Waypoint` — 24 members

Inherits the whole of `carla.Actor`; the members specific to this
class are marked in bold.

| **Member** | **Purpose** |
|---|---|
| `get_junction` | The junction object, if this waypoint is in one |
| `get_landmarks` | Signals and signs within a distance ahead |
| `get_landmarks_of_type` | As above, filtered by OpenDRIVE type |
| `get_left_lane` | Waypoint in the lane to the left, or None |
| `get_right_lane` | Waypoint in the lane to the right, or None |
| `id` | Unique waypoint identifier |
| `is_intersection` | Deprecated — use `is_junction` |
| `is_junction` | Whether this waypoint lies inside a junction |
| `is_rht` | Whether traffic here drives on the right |
| `junction_id` | Identifier of the containing junction |
| `lane_change` | Which lane changes are legal here |
| `lane_id` | OpenDRIVE lane identifier. Sign indicates direction |
| `lane_type` | Driving, Sidewalk, Shoulder, Parking and so on |
| `lane_width` | Lane width in metres |
| `left_lane_marking` | The marking on the left edge |
| `next` | Waypoints N metres ahead. **A list** — junctions branch |
| `next_until_lane_end` | Every waypoint from here to the end of the lane |
| `previous` | Waypoints N metres behind |
| `previous_until_lane_start` | Every waypoint back to the start of the lane |
| `right_lane_marking` | The marking on the right edge |
| `road_id` | OpenDRIVE road identifier |
| `s` | Distance along the road from its start |
| `section_id` | OpenDRIVE section identifier |
| `transform` | Position and orientation of the waypoint |

### `carla.Sensor` — 47 members

Inherits the whole of `carla.Actor`; the members specific to this
class are marked in bold.

| **Member** | **Purpose** |
|---|---|
| `actor_state` | Active, Dormant or Invalid |
| `add_angular_impulse` | Instantaneous change in angular momentum |
| `add_force` | Continuous force at the centre of mass, this frame |
| `add_force_at_location` | Continuous force applied at a point, so it also creates torque |
| `add_impulse` | Instantaneous change in linear momentum |
| `add_impulse_at_location` | Instantaneous impulse at a point |
| `add_torque` | Continuous torque this frame |
| `attributes` | The blueprint attributes this actor was created with |
| `bounding_box` | Local-space bounding box |
| `destroy` | Remove from the world. Always destroy sensors before exiting |
| `disable_constant_velocity` | Stop holding a fixed velocity |
| `disable_for_ros` | Stop publishing this actor on the ROS bridge |
| `enable_constant_velocity` | Hold a fixed velocity regardless of physics |
| `enable_for_ros` | Publish this actor on the ROS bridge |
| `get_acceleration` | Current acceleration vector |
| `get_angular_velocity` | Current angular velocity |
| `get_bone_names` | Skeleton bone names, for skeletal meshes |
| `get_bone_relative_transforms` | Bone transforms relative to the actor |
| `get_bone_world_transforms` | Bone transforms in world space |
| `get_component_names` | Names of the actor's Unreal components |
| `get_component_relative_transform` | One component's transform relative to the actor |
| `get_component_world_transform` | One component's transform in world space |
| `get_location` | World position |
| `get_socket_names` | Attachment socket names on the mesh |
| `get_socket_relative_transforms` | Socket transforms relative to the actor |
| `get_socket_world_transforms` | Socket transforms in world space |
| `get_transform` | Position and rotation together |
| `get_velocity` | Current linear velocity |
| `get_world` | The world this actor belongs to |
| `id` | Unique actor identifier |
| `is_active` | Whether the actor is simulating |
| `is_alive` | Whether it still exists on the server |
| `is_dormant` | Whether it has been put to sleep by distance culling |
| `is_enabled_for_ros` | Whether it is published on the ROS bridge |
| **`is_listening`** | Whether a callback is currently attached |
| **`listen`** | Attach a callback that receives each measurement |
| `parent` | The actor it is attached to, if any |
| `semantic_tags` | Semantic segmentation labels this actor carries |
| `set_collisions` | Enable or disable collision response |
| `set_enable_gravity` | Enable or disable gravity for this actor |
| `set_location` | Teleport to a position, keeping rotation |
| `set_simulate_physics` | Full physics, or kinematic only — kinematic is far cheaper |
| `set_target_angular_velocity` | Drive angular velocity directly, bypassing forces |
| `set_target_velocity` | Drive linear velocity directly, bypassing forces |
| `set_transform` | Teleport to a position and rotation |
| **`stop`** | Detach the callback. Do this before destroying the sensor |
| `type_id` | Blueprint identifier, such as `vehicle.tesla.model3` |

```python
--- START ------------------------------------------------------------------
cd D:\Research\CarlaAirSetup\CarlaAir-v0.1.7-Windows11-x86_64
.\CarlaAir.ps1 Town10HD                     # start
.\CarlaAir.ps1 Town01 --quality Low --no-traffic   # light
.\CarlaAir.ps1 --kill                       # stop
.\CarlaAir.ps1 --log                        # tail the log
.\env_setup\TestEnv.ps1                     # self-test

--- CONNECT ----------------------------------------------------------------
conda activate carlaAir
python -c "import carla; w=carla.Client('localhost',2000).get_world()"
python -c "import airsim; c=airsim.MultirotorClient(); c.confirmConnection()"

--- PAUSE ------------------------------------------------------------------
c.simPause(True)                            # freeze everything
c.simContinueForTime(0.5)                   # step 0.5 s
c.simContinueForFrames(10)                  # step 10 frames
c.simPause(False)                           # resume

s = world.get_settings(); s.synchronous_mode = True
s.fixed_delta_seconds = 0.05; world.apply_settings(s)
tm.set_synchronous_mode(True); world.tick()       # deterministic stepping

--- MAPS -------------------------------------------------------------------
client.get_available_maps()
client.load_world("Town05")
client.reload_world()

--- WEATHER ----------------------------------------------------------------
world.set_weather(carla.WeatherParameters.HardRainSunset)
c.simEnableWeather(True); c.simSetWeatherParameter(airsim.WeatherParameter.Rain, 0.6)

--- AGENTS -----------------------------------------------------------------
python auto_traffic.py --vehicles 50 --walkers 80
vehicle = world.spawn_actor(bp, spawn); vehicle.set_autopilot(True, 8000)
c.simAddVehicle("Drone2", "SimpleFlight", pose)
c.listVehicles()

--- ROADS AND WAYPOINTS ----------------------------------------------------
m = world.get_map(); spawns = m.get_spawn_points()
wp = m.get_waypoint(vehicle.get_location())
wp.next(5.0)[0]; wp.get_left_lane(); wp.next_until_lane_end(2.0)
m.get_topology(); m.generate_waypoints(5.0); m.to_opendrive()

--- DRIVE A VEHICLE YOURSELF -----------------------------------------------
c = carla.VehicleControl(throttle=0.6, steer=-0.2, brake=0.0)
vehicle.apply_control(c)                    # must be reapplied every tick
vehicle.apply_ackermann_control(carla.VehicleAckermannControl(speed=12.0))
vehicle.set_light_state(carla.VehicleLightState.LowBeam)
vehicle.open_door(carla.VehicleDoor.FL)

--- TRAFFIC LIGHTS ---------------------------------------------------------
tl.set_state(carla.TrafficLightState.Green); tl.freeze(True)
world.freeze_all_traffic_lights(True); world.reset_all_traffic_lights()

--- STREET LIGHTS ----------------------------------------------------------
lm = world.get_lightmanager(); lights = lm.get_all_lights(carla.LightGroup.Street)
lm.turn_on(lights); lm.set_intensity(lights, 2000.0); lm.set_day_night_cycle(False)

--- FLY --------------------------------------------------------------------
c.enableApiControl(True); c.armDisarm(True)
c.takeoffAsync().join()
c.moveToZAsync(-30, 3).join()               # 30 m UP -- z is negative
c.moveByVelocityBodyFrameAsync(5,0,0,4).join(); c.hoverAsync().join()
c.landAsync().join(); c.armDisarm(False); c.enableApiControl(False)

--- CAPTURE ----------------------------------------------------------------
c.simGetImages([airsim.ImageRequest("0", airsim.ImageType.Scene, False, False)])

--- DETECT AND SEE ---------------------------------------------------------
c.simSetDetectionFilterRadius("0", airsim.ImageType.Scene, 8000)
c.simAddDetectionFilterMeshName("0", airsim.ImageType.Scene, "Car*")
c.simGetDetections("0", airsim.ImageType.Scene)
c.simTestLineOfSightBetweenPoints(a, b); c.simGetWorldExtents()
c.simCreateVoxelGrid(pos, 200, 200, 100, 1.0, "occupancy.binvox")

--- SCENE OBJECTS ----------------------------------------------------------
c.simListSceneObjects(".*"); c.simListAssets()
c.simSpawnObject("Target_A", "Cube", pose, scale)
c.simSetObjectPose("Target_A", pose); c.simDestroyObject("Target_A")
world.cast_ray(a, b); world.ground_projection(loc, 100.0)
world.get_level_bbs(carla.CityObjectLabel.Buildings)

--- LOGS AND LIVE MONITORING -----------------------------------------------
.\CarlaAir.ps1 --log                        # tail CarlaAir.log (may not exist)
Get-Content .	raffic.err.log -Wait -Tail 40  # traffic output lives HERE, not traffic.log
Get-Process CarlaUE4-Win64-Shipping
nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader
(Get-Counter '\Memory\Available MBytes').CounterSamples[0].CookedValue
ollama ps
c.simRunConsoleCommand("stat unit")         # game / draw / GPU time in viewport
c.simPrintLogMessage("phase: ", "search")   # your own on-screen messages

--- WATCH A RUN FROM A SECOND PROCESS --------------------------------------
s = c.getMultirotorState(vehicle_name="Drone1")   # read-only calls are safe
# never call enableApiControl or a movement command from a monitor

--- RECORD -----------------------------------------------------------------
client.start_recorder("run01.log", True); client.stop_recorder()
client.replay_file("run01.log", 0, 0, 0)

--- LLM AGENTS -------------------------------------------------------------
ollama list / ollama ps / ollama pull llama3.2:3b / ollama stop <model>
cd D:\Research\AirSimRepo
python test_flight.py                       # no LLM -- prove the stack
python baseline/open_loop_agent.py                # natural language

--- CLEAN UP ---------------------------------------------------------------
client.apply_batch([carla.command.DestroyActor(a)
                    for a in world.get_actors().filter("vehicle.*")])
c.reset()
```
