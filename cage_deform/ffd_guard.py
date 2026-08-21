"""Pure FFD cage safety checks used by interactive and native editing.

Interactive checks are limited to the cells touched by the current edit,
so the guard remains responsive up to the supported 8x8x8 resolution.
"""
from __future__ import annotations

import math


MIN_JACOBIAN_RATIO = 0.02
SAFE_INTERPOLATION = "KEY_LINEAR"
JACOBIAN_SAMPLES = (0.0, 0.25, 0.5, 0.75, 1.0)


def _point_index(u, v, w, resolution):
    points_u, points_v, _points_w = resolution
    return int(w) * points_u * points_v + int(v) * points_u + int(u)


def _source_points(size, resolution):
    size = tuple(max(abs(float(value)), 1.0e-8) for value in size)
    resolution = tuple(max(int(value), 2) for value in resolution)
    points = []
    for w in range(resolution[2]):
        z = -size[2] * 0.5 + size[2] * w / (resolution[2] - 1)
        for v in range(resolution[1]):
            y = -size[1] * 0.5 + size[1] * v / (resolution[1] - 1)
            for u in range(resolution[0]):
                x = -size[0] * 0.5 + size[0] * u / (resolution[0] - 1)
                points.append((x, y, z))
    return tuple(points)


def _add(left, right):
    return tuple(a + b for a, b in zip(left, right))


def _sub(left, right):
    return tuple(a - b for a, b in zip(left, right))


def _mul(value, factor):
    return tuple(component * factor for component in value)


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def _cross(left, right):
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _determinant(first, second, third):
    return _dot(first, _cross(second, third))


def _corner_indices(cell_u, cell_v, cell_w, resolution):
    u0, v0, w0 = cell_u, cell_v, cell_w
    u1, v1, w1 = u0 + 1, v0 + 1, w0 + 1
    return (
        _point_index(u0, v0, w0, resolution),
        _point_index(u1, v0, w0, resolution),
        _point_index(u0, v1, w0, resolution),
        _point_index(u1, v1, w0, resolution),
        _point_index(u0, v0, w1, resolution),
        _point_index(u1, v0, w1, resolution),
        _point_index(u0, v1, w1, resolution),
        _point_index(u1, v1, w1, resolution),
    )


def _all_cell_indices(resolution):
    """Yield every valid cell coordinate in deterministic order."""
    for cell_w in range(resolution[2] - 1):
        for cell_v in range(resolution[1] - 1):
            for cell_u in range(resolution[0] - 1):
                yield cell_u, cell_v, cell_w


def _normalize_cell_indices(resolution, cell_indices):
    """Return valid, unique cell coordinates supplied by an edit path."""
    if cell_indices is None:
        return tuple(_all_cell_indices(resolution))
    result = []
    seen = set()
    try:
        values = tuple(cell_indices)
    except (TypeError, ValueError):
        return ()
    for value in values:
        try:
            cell = tuple(int(component) for component in value)
        except (TypeError, ValueError, OverflowError):
            continue
        if (
                len(cell) != 3 or
                not 0 <= cell[0] < resolution[0] - 1 or
                not 0 <= cell[1] < resolution[1] - 1 or
                not 0 <= cell[2] < resolution[2] - 1 or
                cell in seen
        ):
            continue
        seen.add(cell)
        result.append(cell)
    return tuple(result)


def _affected_cell_indices(changed_indices, resolution):
    """Return only cells touching one or more changed control points."""
    cells = set()
    points_u, points_v, points_w = resolution
    for index in changed_indices:
        try:
            index = int(index)
        except (TypeError, ValueError, OverflowError):
            continue
        plane = points_u * points_v
        w, remainder = divmod(index, plane)
        v, u = divmod(remainder, points_u)
        for cell_w in (w - 1, w):
            for cell_v in (v - 1, v):
                for cell_u in (u - 1, u):
                    if (
                            0 <= cell_u < points_u - 1 and
                            0 <= cell_v < points_v - 1 and
                            0 <= cell_w < points_w - 1
                    ):
                        cells.add((cell_u, cell_v, cell_w))
    return tuple(sorted(cells))


def _trilinear_jacobian(corners, sample):
    """Return dP/d(s,t,r) for one trilinear cell sample."""
    s, t, r = (float(value) for value in sample)
    one = (1.0 - s, s)
    two = (1.0 - t, t)
    three = (1.0 - r, r)
    d_s = (-1.0, 1.0)
    d_t = (-1.0, 1.0)
    d_r = (-1.0, 1.0)
    derivatives = [[0.0, 0.0, 0.0] for _ in range(3)]
    # Corner order is (u, v, w) with each coordinate in {0, 1}.
    for index, point in enumerate(corners):
        u = index & 1
        v = (index >> 1) & 1
        w = (index >> 2) & 1
        weights = (
            d_s[u] * two[v] * three[w],
            one[u] * d_t[v] * three[w],
            one[u] * two[v] * d_r[w],
        )
        for axis in range(3):
            derivatives[0][axis] += point[axis] * weights[0]
            derivatives[1][axis] += point[axis] * weights[1]
            derivatives[2][axis] += point[axis] * weights[2]
    return tuple(tuple(value) for value in derivatives)


def minimum_jacobian_ratio(
        points, size, resolution, *, samples=JACOBIAN_SAMPLES,
        cell_indices=None):
    """Return the smallest sampled cell Jacobian relative to the base grid.

    The quarter points catch interior trilinear foldovers that can be missed
    by checking only cell corners and the center.
    """
    resolution = tuple(max(int(value), 2) for value in resolution)
    if len(points) != math.prod(resolution):
        return -math.inf
    base_size = tuple(max(abs(float(value)), 1.0e-8) for value in size)
    base_cell = math.prod(
        value / max(count - 1, 1)
        for value, count in zip(base_size, resolution)
    )
    if base_cell <= 0.0 or not math.isfinite(base_cell):
        return -math.inf
    minimum = math.inf
    cells = _normalize_cell_indices(resolution, cell_indices)
    for cell_u, cell_v, cell_w in cells:
        corners = tuple(
            tuple(float(component) for component in points[index])
            for index in _corner_indices(
                cell_u, cell_v, cell_w, resolution)
        )
        for sample in (
                (s, t, r)
                for s in samples
                for t in samples
                for r in samples):
            d_s, d_t, d_r = _trilinear_jacobian(corners, sample)
            determinant = _determinant(d_s, d_t, d_r)
            if not math.isfinite(determinant):
                return -math.inf
            minimum = min(minimum, determinant / base_cell)
    return float(minimum)


def _effective_points(size, resolution, offsets, influences):
    sources = _source_points(size, resolution)
    count = len(sources)
    if len(offsets) != count:
        return None
    values = []
    for index, source in enumerate(sources):
        try:
            offset = tuple(float(value) for value in offsets[index])
            influence = min(max(float(influences[index]), 0.0), 1.0)
        except (IndexError, TypeError, ValueError, OverflowError):
            return None
        if len(offset) != 3 or not all(math.isfinite(value) for value in offset):
            return None
        if not math.isfinite(influence):
            return None
        values.append(_add(source, _mul(offset, influence)))
    return tuple(values)


def clamp_offsets(
        size, resolution, baseline_offsets, candidate_offsets, influences,
        *, threshold=MIN_JACOBIAN_RATIO, iterations=18, baseline_ratio=None):
    """Clamp a candidate raw-offset field to the last valid cell transform.

    The returned tuple is ``(offsets, fraction, baseline_ratio, candidate_ratio)``.
    A fraction below one means the candidate crossed the safety boundary.
    """
    resolution = tuple(max(int(value), 2) for value in resolution)
    count = math.prod(resolution)
    if (
            len(baseline_offsets) != count or
            len(candidate_offsets) != count or
            len(influences) != count
    ):
        return tuple(candidate_offsets), 1.0, -math.inf, -math.inf
    initial_points = _effective_points(
        size, resolution, baseline_offsets, influences)
    candidate_points = _effective_points(
        size, resolution, candidate_offsets, influences)
    if initial_points is None or candidate_points is None:
        return tuple(baseline_offsets), 0.0, -math.inf, -math.inf
    changed_indices = tuple(
        index for index, (baseline, candidate) in enumerate(
            zip(baseline_offsets, candidate_offsets))
        if baseline != candidate
    )
    if not changed_indices:
        if baseline_ratio is None:
            baseline_ratio = minimum_jacobian_ratio(
                initial_points, size, resolution)
        return tuple(candidate_offsets), 1.0, float(baseline_ratio), float(
            baseline_ratio)
    if baseline_ratio is None or not math.isfinite(float(baseline_ratio)):
        baseline_ratio = minimum_jacobian_ratio(
            initial_points, size, resolution)
    baseline_ratio = float(baseline_ratio)
    affected_cells = _affected_cell_indices(changed_indices, resolution)
    candidate_ratio = minimum_jacobian_ratio(
        candidate_points, size, resolution, cell_indices=affected_cells)
    if baseline_ratio < float(threshold):
        # Existing files can already contain a folded cage. Do not invent a
        # larger edit; keep the last known field and let the caller warn.
        return tuple(baseline_offsets), 0.0, baseline_ratio, candidate_ratio
    if candidate_ratio >= float(threshold):
        return tuple(candidate_offsets), 1.0, baseline_ratio, candidate_ratio

    low = 0.0
    high = 1.0
    for _index in range(max(int(iterations), 1)):
        fraction = (low + high) * 0.5
        probe = tuple(
            _add(
                baseline_offsets[index],
                _mul(
                    _sub(candidate_offsets[index], baseline_offsets[index]),
                    fraction,
                ),
            )
            for index in range(count)
        )
        points = _effective_points(size, resolution, probe, influences)
        ratio = minimum_jacobian_ratio(
            points, size, resolution, cell_indices=affected_cells)
        if ratio >= float(threshold):
            low = fraction
        else:
            high = fraction
    result = tuple(
        _add(
            baseline_offsets[index],
            _mul(
                _sub(candidate_offsets[index], baseline_offsets[index]), low)
        )
        for index in range(count)
    )
    return result, low, baseline_ratio, candidate_ratio
