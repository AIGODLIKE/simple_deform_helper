"""Pure helpers for preserving authored FFD data across grid resize."""
from __future__ import annotations

import math

import bpy


_AXIS_WEIGHT_CACHE = {}


def _point_index(u, v, w, resolution):
    points_u, points_v, _points_w = resolution
    return int(w) * points_u * points_v + int(v) * points_u + int(u)


def _point_coordinates(index, resolution):
    points_u, points_v, points_w = resolution
    count = points_u * points_v * points_w
    index = min(max(int(index), 0), max(count - 1, 0))
    plane = points_u * points_v
    w, remainder = divmod(index, plane)
    v, u = divmod(remainder, points_u)
    return u, v, w


def _axis_sample(coordinate, old_size, new_size):
    scaled = (
        float(coordinate) * max(int(old_size) - 1, 0) /
        max(int(new_size) - 1, 1)
    )
    lower = min(max(int(math.floor(scaled)), 0), max(int(old_size) - 1, 0))
    upper = min(lower + 1, max(int(old_size) - 1, 0))
    return lower, upper, scaled - lower


def native_axis_weights(resolution, interpolation, samples):
    """Sample Blender's native one-dimensional Lattice basis."""
    resolution = max(int(resolution), 2)
    interpolation = str(interpolation or "KEY_BSPLINE")
    samples = tuple(float(value) for value in samples)
    key = (
        resolution,
        interpolation,
        tuple(round(value, 9) for value in samples),
    )
    cached = _AXIS_WEIGHT_CACHE.get(key)
    if cached is not None:
        return cached

    mesh = None
    target = None
    lattice_data = None
    lattice = None
    try:
        mesh = bpy.data.meshes.new("SDH FFD Basis Probe Mesh")
        mesh.from_pydata(
            [(
                0.0,
                (2.0 * value - 1.0) * max(resolution - 1, 1),
                0.0,
            ) for value in samples],
            (),
            (),
        )
        target = bpy.data.objects.new("SDH FFD Basis Probe", mesh)
        bpy.context.collection.objects.link(target)
        lattice_data = bpy.data.lattices.new("SDH FFD Basis Probe Data")
        lattice_data.points_u = 2
        lattice_data.points_v = resolution
        lattice_data.points_w = 2
        lattice_data.interpolation_type_u = "KEY_LINEAR"
        lattice_data.interpolation_type_v = interpolation
        lattice_data.interpolation_type_w = "KEY_LINEAR"
        lattice = bpy.data.objects.new("SDH FFD Basis Probe", lattice_data)
        bpy.context.collection.objects.link(lattice)
        lattice.scale = (2.0, 2.0, 2.0)
        modifier = target.modifiers.new("SDH FFD Basis Probe", "LATTICE")
        modifier.object = lattice
        weights = []
        for basis_index in range(resolution):
            for point in lattice_data.points:
                point.co_deform = point.co
            for w in (0, 1):
                for u in (0, 1):
                    point_index = _point_index(
                        u, basis_index, w, (2, resolution, 2))
                    lattice_data.points[point_index].co_deform.x += 0.5
            bpy.context.view_layer.update()
            evaluated = target.evaluated_get(
                bpy.context.evaluated_depsgraph_get())
            result = evaluated.to_mesh()
            try:
                weights.append(tuple(
                    float(vertex.co.x) for vertex in result.vertices))
            finally:
                evaluated.to_mesh_clear()
        result = tuple(
            tuple(weights[column][row] for column in range(resolution))
            for row in range(len(samples))
        )
        _AXIS_WEIGHT_CACHE[key] = result
        return result
    finally:
        if target is not None:
            try:
                bpy.data.objects.remove(target, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        if lattice is not None:
            try:
                bpy.data.objects.remove(lattice, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        if mesh is not None:
            try:
                bpy.data.meshes.remove(mesh)
            except (ReferenceError, RuntimeError):
                pass
        if lattice_data is not None:
            try:
                bpy.data.lattices.remove(lattice_data)
            except (ReferenceError, RuntimeError):
                pass


def invert_dense_matrix(matrix):
    """Invert one small dense matrix without a NumPy dependency."""
    size = len(matrix)
    if size == 0 or any(len(row) != size for row in matrix):
        return None
    augmented = [
        [float(value) for value in row] + [
            1.0 if column == row_index else 0.0
            for column in range(size)
        ]
        for row_index, row in enumerate(matrix)
    ]
    for column in range(size):
        pivot = max(
            range(column, size),
            key=lambda row_index: abs(augmented[row_index][column]),
        )
        pivot_value = augmented[pivot][column]
        if abs(pivot_value) <= 1.0e-8:
            return None
        if pivot != column:
            augmented[column], augmented[pivot] = (
                augmented[pivot], augmented[column])
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row_index in range(size):
            if row_index == column:
                continue
            factor = augmented[row_index][column]
            if abs(factor) <= 1.0e-12:
                continue
            augmented[row_index] = [
                left - factor * right
                for left, right in zip(
                    augmented[row_index], augmented[column])
            ]
    return tuple(tuple(row[size:]) for row in augmented)


def _axis_transform(old_size, new_size, interpolation):
    old_size = max(int(old_size), 1)
    new_size = max(int(new_size), 1)
    if old_size == new_size:
        return tuple(
            tuple(1.0 if old == new else 0.0 for old in range(old_size))
            for new in range(new_size)
        )
    sample_count = max(old_size, new_size) * 8 + 1
    samples = tuple(
        value / max(sample_count - 1, 1) for value in range(sample_count))
    source_weights = native_axis_weights(
        old_size, interpolation, samples)
    destination_weights = native_axis_weights(
        new_size, interpolation, samples)
    normal = tuple(
        tuple(
            sum(row[left] * row[right] for row in destination_weights)
            for right in range(new_size)
        )
        for left in range(new_size)
    )
    inverse = invert_dense_matrix(normal)
    if inverse is None:
        return None
    right_hand = tuple(
        tuple(sum(
            destination_weights[sample][destination_index] *
            source_weights[sample][source_index]
            for sample in range(sample_count)
        ) for source_index in range(old_size))
        for destination_index in range(new_size)
    )
    return tuple(
        tuple(
            sum(
                inverse[destination][row] * right_hand[row][source]
                for row in range(new_size)
            )
            for source in range(old_size)
        )
        for destination in range(new_size)
    )


def _resample_linear(offsets, old_resolution, new_resolution):
    """Fallback that preserves the visible control grid linearly."""
    offsets = tuple(tuple(float(value) for value in offset) for offset in offsets)
    if not offsets:
        return ((0.0, 0.0, 0.0),) * math.prod(new_resolution)

    def source(index):
        return offsets[min(max(int(index), 0), len(offsets) - 1)]

    result = []
    for w in range(new_resolution[2]):
        w0, w1, fw = _axis_sample(
            w, old_resolution[2], new_resolution[2])
        for v in range(new_resolution[1]):
            v0, v1, fv = _axis_sample(
                v, old_resolution[1], new_resolution[1])
            for u in range(new_resolution[0]):
                u0, u1, fu = _axis_sample(
                    u, old_resolution[0], new_resolution[0])
                value = [0.0, 0.0, 0.0]
                for uu, weight_u in ((u0, 1.0 - fu), (u1, fu)):
                    for vv, weight_v in ((v0, 1.0 - fv), (v1, fv)):
                        for ww, weight_w in ((w0, 1.0 - fw), (w1, fw)):
                            weight = weight_u * weight_v * weight_w
                            if weight == 0.0:
                                continue
                            offset = source(_point_index(
                                uu, vv, ww, old_resolution))
                            for axis in range(3):
                                value[axis] += offset[axis] * weight
                result.append(tuple(value))
    return tuple(result)


def resample_offsets(
        offsets, old_resolution, new_resolution, interpolations=None):
    """Preserve the native FFD field while changing its control resolution."""
    offsets = tuple(tuple(float(value) for value in offset) for offset in offsets)
    old_resolution = tuple(max(int(value), 1) for value in old_resolution)
    new_resolution = tuple(max(int(value), 1) for value in new_resolution)
    if not offsets:
        return ((0.0, 0.0, 0.0),) * math.prod(new_resolution)
    interpolations = tuple(interpolations or ("KEY_LINEAR",) * 3)
    if len(interpolations) != 3:
        return _resample_linear(offsets, old_resolution, new_resolution)
    try:
        transforms = tuple(
            _axis_transform(old_size, new_size, interpolation)
            for old_size, new_size, interpolation in zip(
                old_resolution, new_resolution, interpolations)
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        transforms = ()
    if len(transforms) != 3 or any(value is None for value in transforms):
        return _resample_linear(offsets, old_resolution, new_resolution)

    def source(index):
        return offsets[min(max(int(index), 0), len(offsets) - 1)]

    result = []
    for new_w in range(new_resolution[2]):
        for new_v in range(new_resolution[1]):
            for new_u in range(new_resolution[0]):
                value = [0.0, 0.0, 0.0]
                for old_w in range(old_resolution[2]):
                    weight_w = transforms[2][new_w][old_w]
                    for old_v in range(old_resolution[1]):
                        weight_v = transforms[1][new_v][old_v]
                        for old_u in range(old_resolution[0]):
                            weight = (
                                transforms[0][new_u][old_u] *
                                weight_v * weight_w)
                            if abs(weight) <= 1.0e-15:
                                continue
                            offset = source(_point_index(
                                old_u, old_v, old_w, old_resolution))
                            for axis in range(3):
                                value[axis] += offset[axis] * weight
                result.append(tuple(value))
    return tuple(result)


def resample_values(
        values, old_resolution, new_resolution, interpolations=None):
    """Resample one scalar field with the same native FFD basis as offsets.

    FFD point influence is an authored scalar field, so it must follow the
    same U/V/W interpolation and resolution changes as the displacement
    field.  Reusing the vector implementation keeps the two fields aligned
    without introducing a second interpolation algorithm.
    """
    values = tuple(float(value) for value in values)
    if not values:
        return (1.0,) * math.prod(tuple(max(int(v), 1) for v in new_resolution))
    vectors = tuple((value, 0.0, 0.0) for value in values)
    return tuple(
        min(max(float(vector[0]), 0.0), 1.0)
        for vector in resample_offsets(
            vectors, old_resolution, new_resolution, interpolations)
    )


def remap_index(index, old_resolution, new_resolution):
    """Map one grid index through normalized UVW coordinates."""
    old_resolution = tuple(max(int(value), 1) for value in old_resolution)
    new_resolution = tuple(max(int(value), 1) for value in new_resolution)
    coordinates = _point_coordinates(index, old_resolution)
    mapped = tuple(
        min(max(int(math.floor(
            coordinate * max(new_size - 1, 0) /
            max(old_size - 1, 1) + 0.5)), 0), new_size - 1)
        for coordinate, old_size, new_size in zip(
            coordinates, old_resolution, new_resolution)
    )
    return _point_index(*mapped, new_resolution)


def remap_indices(indices, old_resolution, new_resolution):
    """Map a selection without expanding one old point into several new ones."""
    return frozenset(
        remap_index(index, old_resolution, new_resolution)
        for index in indices
    )
