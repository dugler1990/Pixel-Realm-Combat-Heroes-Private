"""The few rotation helpers the bake needs, in numpy, matching mathutils' conventions.

Matrices are 3x3 / 4x4 column-vector (v' = M @ v), right-handed, as in Blender. Quaternions (w, x, y, z).
"""
from __future__ import annotations

import math

import numpy as np

Y = np.array([0.0, 1.0, 0.0])
Z = np.array([0.0, 0.0, 1.0])


def ncols(m3: np.ndarray) -> np.ndarray:
    """mathutils Matrix.normalized(): each column scaled to unit length."""
    n = np.linalg.norm(m3, axis=0)
    n[n < 1e-12] = 1.0
    return m3 / n


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v.copy()


def axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    """Matrix.Rotation(angle, 3, axis)."""
    x, y, z = unit(np.asarray(axis, float))
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    return np.array([
        [t * x * x + c, t * x * y - s * z, t * x * z + s * y],
        [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
        [t * x * z - s * y, t * y * z + s * x, t * z * z + c],
    ])


def rot_between(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Vector.rotation_difference(): the shortest-arc rotation taking u onto v."""
    u, v = unit(u), unit(v)
    axis = np.cross(u, v)
    s = float(np.linalg.norm(axis))
    c = float(np.dot(u, v))
    if s < 1e-12:
        if c > 0:
            return np.eye(3)
        ortho = np.cross(u, [1.0, 0.0, 0.0])
        if np.linalg.norm(ortho) < 1e-6:
            ortho = np.cross(u, [0.0, 1.0, 0.0])
        return axis_angle(ortho, math.pi)
    return axis_angle(axis / s, math.atan2(s, c))


def aim_dir(m3: np.ndarray, direction: np.ndarray) -> np.ndarray:
    """Point a bone's +Y along `direction`, keeping as much of its twist as possible."""
    return rot_between(unit(m3 @ Y), unit(direction)) @ m3


def mat_to_quat(m: np.ndarray) -> np.ndarray:
    m = ncols(np.asarray(m, float)[:3, :3])
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = [0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [(m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s]
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s]
    q = np.array(q)
    return q / np.linalg.norm(q)


def quat_to_mat(q: np.ndarray) -> np.ndarray:
    w, x, y, z = unit(np.asarray(q, float))
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
        [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
        [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ])


def slerp_from_identity(q: np.ndarray, t: float) -> np.ndarray:
    """Quaternion().slerp(q, t), shortest path like Blender's interp_qt_qtqt."""
    q = unit(np.asarray(q, float))
    if q[0] < 0:
        q = -q
    cosom = min(1.0, q[0])
    if 1.0 - cosom > 1e-4:
        omega = math.acos(cosom)
        sinom = math.sin(omega)
        a = math.sin((1.0 - t) * omega) / sinom
        b = math.sin(t * omega) / sinom
    else:
        a, b = 1.0 - t, t
    return unit(a * np.array([1.0, 0, 0, 0]) + b * q)


def quat_axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    """Quaternion(axis, angle)."""
    x, y, z = unit(np.asarray(axis, float))
    s = math.sin(angle / 2)
    return np.array([math.cos(angle / 2), x * s, y * s, z * s])


def translate(m3: np.ndarray, loc: np.ndarray) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = m3
    m[:3, 3] = loc
    return m
