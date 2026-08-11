"""Fast line and face drawing for the aggregate FFD Gizmo."""
from __future__ import annotations

import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .viewport import gizmo_depth_test


def _rgba(gizmo, highlighted):
    color = tuple(
        gizmo.color_highlight if highlighted else gizmo.color)
    alpha = float(
        gizmo.alpha_highlight if highlighted else gizmo.alpha)
    return (*color[:3], alpha)


def _line_vertices(points, ratio):
    points = tuple(Vector(point) for point in points)
    if len(points) < 2:
        return ()
    lengths = tuple(
        (second - first).length
        for first, second in zip(points, points[1:]))
    total = sum(lengths)
    if total <= 1.0e-8:
        return ()
    cursor = total * 0.5
    walked = 0.0
    center = points[0]
    tangent = Vector((0.0, 1.0, 0.0))
    for first, second, length in zip(points, points[1:], lengths):
        if walked + length >= cursor and length > 1.0e-8:
            factor = (cursor - walked) / length
            center = first.lerp(second, factor)
            tangent = (second - first).normalized()
            break
        walked += length
    half = tangent * total * min(max(float(ratio), 0.10), 1.0) * 0.5
    return center - half, center + half


def _face_vertices(points, ratio):
    points = tuple(Vector(point) for point in points)
    if len(points) != 4:
        return ()
    center = sum(points, Vector((0.0, 0.0, 0.0))) / 4.0
    first_axis = ((points[1] + points[2]) - (points[0] + points[3])) * 0.5
    second_axis = ((points[2] + points[3]) - (points[0] + points[1])) * 0.5
    first_span = first_axis.length
    if first_span <= 1.0e-8:
        return ()
    first_axis.normalize()
    second_axis -= first_axis * second_axis.dot(first_axis)
    second_span = second_axis.length
    if second_span <= 1.0e-8:
        return ()
    second_axis.normalize()
    scale = min(max(float(ratio), 0.10), 1.0) * 0.5
    first_axis *= first_span * scale
    second_axis *= second_span * scale
    corners = (
        center - first_axis - second_axis,
        center + first_axis - second_axis,
        center + first_axis + second_axis,
        center - first_axis + second_axis,
    )
    return (
        corners[0], corners[1], corners[2],
        corners[0], corners[2], corners[3],
    )


def draw_ffd_line_face_batches(
        gizmo, entities, picked, world_points, groups, face_indices,
        color_for=None):
    """Draw all FFD line and face controls using stable color buckets.

    The aggregate Gizmo owns every entity, so one ``color`` field cannot
    represent selected top/bottom groups at the same time.  ``color_for``
    lets the caller supply an entity palette while retaining batched GPU
    draws; the legacy palette remains the fallback for external callers.
    """
    buckets = {}
    counts = {"LINE": 0, "FACE": 0}
    for entity in entities:
        anchor, mode, orientation = entity
        mode = str(mode)
        if mode not in counts:
            continue
        group = tuple(groups.get(tuple(entity), ()))
        if not group:
            continue
        if mode == "LINE":
            vertices = _line_vertices(
                (world_points[index] for index in group),
                getattr(gizmo, "ffd_line_length_ratio", 0.60),
            )
        else:
            ordered = tuple(face_indices(
                int(anchor), str(orientation), group))
            vertices = _face_vertices(
                (world_points[index] for index in ordered),
                getattr(gizmo, "ffd_face_size_ratio", 0.35),
            )
        if not vertices:
            continue
        highlighted = bool(gizmo.is_highlight and entity == picked)
        color = (
            tuple(color_for(entity, group, highlighted))
            if color_for is not None else _rgba(gizmo, highlighted)
        )
        buckets.setdefault((mode, color), []).extend(vertices)
        counts[mode] += 1

    shader = gpu.shader.from_builtin("UNIFORM_COLOR")
    gpu.state.blend_set("ALPHA")
    gpu.state.depth_test_set(gizmo_depth_test())
    try:
        for mode in ("FACE", "LINE"):
            primitive = "TRIS" if mode == "FACE" else "LINES"
            if mode == "LINE":
                gpu.state.line_width_set(max(
                    float(getattr(gizmo, "ffd_line_width", 1.0)), 1.0))
            for (bucket_mode, color), vertices in tuple(buckets.items()):
                if bucket_mode != mode:
                    continue
                if not vertices:
                    continue
                batch = batch_for_shader(shader, primitive, {"pos": vertices})
                shader.bind()
                shader.uniform_float("color", color)
                batch.draw(shader)
    finally:
        gpu.state.line_width_set(1.0)
        gpu.state.depth_test_set("NONE")
        gpu.state.blend_set("NONE")
    return counts
