r"""Check every built-in sensor of the drone, read-only. CARLA-Air must be running.
    python sensor_check.py
    python sensor_check.py --vehicle Drone1
Prints: the vehicles AirSim knows, each camera's picture and distance-picture size, one reading from
the IMU, GPS, barometer, magnetometer and collision sensor, and how far away things are straight ahead.
Nothing is written to disk and nothing in the simulator is changed.
"""
import argparse
import airsim
import numpy as np
CAMERAS = ["front_center", "bottom_center"]
def depth_array(resp):
    return np.array(resp.image_data_float, dtype=np.float32).reshape(resp.height, resp.width)
def distance_ahead(depth):
    """Nearest 5% and median distance (m) in the middle third of a planar depth image."""
    h, w = depth.shape
    roi = depth[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
    roi = roi[np.isfinite(roi) & (roi > 0.2)]
    if roi.size == 0:
        return None, None
    return float(np.percentile(roi, 5)), float(np.median(roi))
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vehicle", default=None, help="default: every vehicle AirSim reports")
    a = ap.parse_args()
    c = airsim.MultirotorClient()
    c.confirmConnection()
    vehicles = [a.vehicle] if a.vehicle else c.listVehicles()
    print("vehicles:", c.listVehicles())
    problems = 0
    for v in vehicles:
        print(f"\n== {v}")
        for cam in CAMERAS:
            try:
                fov = c.simGetCameraInfo(cam, v).fov
                rgb, dep = c.simGetImages([
                    airsim.ImageRequest(cam, airsim.ImageType.Scene, False, True),
                    airsim.ImageRequest(cam, airsim.ImageType.DepthPlanar, True, False)], vehicle_name=v)
                near, med = distance_ahead(depth_array(dep))
                dist = f"ahead: nearest {near:.1f} m, typical {med:.1f} m" if near is not None else "ahead: no depth values"
                print(f"  camera {cam:13s} fov {fov:5.1f}  picture {rgb.width}x{rgb.height}  "
                      f"distance picture {dep.width}x{dep.height}  {dist}")
                if rgb.width == 0 or dep.width == 0:
                    problems += 1
            except Exception as e:  # report and continue with the next sensor
                problems += 1
                print(f"  camera {cam:13s} PROBLEM: {e}")
        readings = [
            ("imu", lambda: "angular velocity z {:.3f} rad/s, acceleration z {:.2f} m/s2".format(
                c.getImuData(vehicle_name=v).angular_velocity.z_val,
                c.getImuData(vehicle_name=v).linear_acceleration.z_val)),
            ("gps", lambda: "valid {}  lat {:.6f}  lon {:.6f}  alt {:.1f} m".format(
                c.getGpsData(vehicle_name=v).is_valid,
                c.getGpsData(vehicle_name=v).gnss.geo_point.latitude,
                c.getGpsData(vehicle_name=v).gnss.geo_point.longitude,
                c.getGpsData(vehicle_name=v).gnss.geo_point.altitude)),
            ("barometer", lambda: "altitude {:.1f} m  pressure {:.0f} Pa".format(
                c.getBarometerData(vehicle_name=v).altitude, c.getBarometerData(vehicle_name=v).pressure)),
            ("magnetometer", lambda: "field x {:.3f}  y {:.3f}  z {:.3f}".format(
                *(lambda m: (m.x_val, m.y_val, m.z_val))(c.getMagnetometerData(vehicle_name=v).magnetic_field_body))),
            ("collision", lambda: "has collided: {}".format(c.simGetCollisionInfo(vehicle_name=v).has_collided)),
            ("position", lambda: "x {:.1f}  y {:.1f}  z {:.1f} m (NED, z negative = up)".format(
                *(lambda p: (p.x_val, p.y_val, p.z_val))(c.getMultirotorState(vehicle_name=v).kinematics_estimated.position))),
        ]
        for label, read in readings:
            try:
                print(f"  {label:13s} {read()}")
            except Exception as e:
                problems += 1
                print(f"  {label:13s} PROBLEM: {e}")
    print("\nRESULT:", "all sensors answered" if problems == 0 else f"{problems} problem(s), see above")
if __name__ == "__main__":
    main()
