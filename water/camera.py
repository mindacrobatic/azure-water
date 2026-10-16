"""Matrix math and the orbit camera.

Convention: column-vector math (clip = P @ pos). Matrices are stored as
row-major numpy arrays; when uploading to GL we flatten with order="F"
(i.e. column-major bytes), which is what GLSL expects.
"""
from __future__ import annotations

import math

import numpy as np


def perspective(fovy_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fovy_deg) * 0.5)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye, target, up=(0.0, 1.0, 0.0)) -> np.ndarray:
    eye = np.asarray(eye, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)

    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)

    m = np.eye(4, dtype=np.float64)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -np.dot(s, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] = np.dot(f, eye)
    return m.astype(np.float32)


def reflect_y(level: float) -> np.ndarray:
    """Matrix mirroring space across the horizontal plane y == level."""
    m = np.eye(4, dtype=np.float32)
    m[1, 1] = -1.0
    m[1, 3] = 2.0 * level
    return m


def dir_from_angles(az_deg: float, el_deg: float) -> np.ndarray:
    """Unit direction from azimuth/elevation in degrees (az measured from +Z)."""
    az = math.radians(az_deg)
    el = math.radians(el_deg)
    return np.array(
        [math.sin(az) * math.cos(el), math.sin(el), math.cos(az) * math.cos(el)],
        dtype=np.float64,
    )


class OrbitCamera:
    """Drag-to-orbit camera aimed at a target point above the water."""

    def __init__(self, target=(0.0, 0.6, 0.0), az=194.0, el=-3.0, radius=60.0):
        self.target = np.array(target, dtype=np.float64)
        self.az = az          # view azimuth (direction the camera faces)
        self.el = el          # view pitch in degrees (negative = looking down)
        self.radius = radius
        self.min_radius = 3.0
        self.max_radius = 320.0
        self.min_el = -80.0
        self.max_el = 12.0
        self.eye_min_y = 0.35  # keep the eye above the water

    # -- interaction -------------------------------------------------
    def orbit(self, dx: float, dy: float) -> None:
        self.az -= dx * 0.14
        self.el = max(self.min_el, min(self.max_el, self.el - dy * 0.10))

    def zoom(self, steps: float) -> None:
        self.radius = max(self.min_radius, min(self.max_radius, self.radius * math.exp(-steps * 0.10)))

    def pan(self, forward: float, strafe: float, up: float) -> None:
        # Move the target in the camera's horizontal frame.
        v = dir_from_angles(self.az, 0.0)
        right = np.array([-v[2], 0.0, v[0]])
        speed = self.radius * 0.5
        self.target = self.target + (v * forward + right * strafe) * speed + np.array([0.0, 1.0, 0.0]) * up * speed
        self.target[1] = min(40.0, max(0.15, self.target[1]))

    # -- matrices ----------------------------------------------------
    def eye(self) -> np.ndarray:
        d = dir_from_angles(self.az, self.el)
        eye = self.target - d * self.radius
        eye[1] = max(self.eye_min_y, eye[1])
        return eye

    def view(self) -> np.ndarray:
        return look_at(self.eye(), self.target)
