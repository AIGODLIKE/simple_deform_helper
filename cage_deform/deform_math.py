"""Pure local deformation math shared by runtime and tests."""
from __future__ import annotations

import math

from mathutils import Vector

from .deform_contract import (
    CHAIN_BOUNDARY_EPSILON,
    DEFORM_BITS,
    DEFORM_ORDER,
    EPSILON,
    FFD_COMPONENT_COUNT,
    FFD_CORNERS,
    _deform_name,
    normalize_deform_order,
)


def normalized_ffd_offsets(values=()):
    """Return eight finite cage-local FFD offset vectors."""
    try:
        flat = tuple(float(value) for value in values)
    except (TypeError, ValueError, OverflowError):
        flat = ()
    flat = flat[:FFD_COMPONENT_COUNT] + (0.0,) * max(
        FFD_COMPONENT_COUNT - len(flat), 0)
    return tuple(
        Vector(flat[index:index + 3])
        for index in range(0, FFD_COMPONENT_COUNT, 3)
    )


def deform_point_local(point, size, deform_type="BEND", strength=0.0,
                       factor=0.0, direction=0.0, mode="LIMITED",
                       origin="BOTTOM", preserve_volume=True,
                       top_scale=(1.0, 1.0), bottom_scale=(1.0, 1.0),
                       top_offset=(0.0, 0.0), bottom_offset=(0.0, 0.0), *,
                       stage_enabled=True,
                       chain_eligible=True,
                       chain_root_stage=False,
                       chain_input_offset=(0.0, 0.0, 0.0),
                       chain_input_frame=None,
                       chain_output_frame=None,
                       chain_source_coordinate=None,
                       chain_source_start=None,
                       chain_profile_after_end=False,
                       chain_profile_gap_distance=0.0,
                       deform_types=None, bend_strength=None,
                       bend_direction=None, twist_strength=None,
                       taper_factor=None, stretch_factor=None,
                       shear_factors=(0.0, 0.0), ffd_offsets=(),
                       deform_order=None, curve_deformer=None,
                       _prepared=False):
    """Reference implementation shared by viewport drawing and regressions.

    Omitting ``deform_types`` preserves the original single-operation API.
    Supplying ``deform_order`` composes enabled operations in that normalized
    order, matching the permanent operation blocks in Geometry Nodes.
    """
    raw_point = Vector(point)
    point = raw_point.copy()
    if not stage_enabled:
        return raw_point.copy()
    size = Vector((max(abs(value), EPSILON) for value in size))
    if _prepared:
        enabled = set(deform_types or ())
        operation_order = tuple(deform_order or ())
    elif deform_types is None and deform_order is None:
        enabled = {deform_type} if deform_type in DEFORM_BITS else {"BEND"}
    elif deform_types is None:
        try:
            enabled = {
                name for name in (_deform_name(value) for value in deform_order)
                if name is not None
            }
        except TypeError:
            enabled = set()
    else:
        try:
            enabled = {
                name for name in (_deform_name(value) for value in deform_types)
                if name is not None
            }
        except TypeError:
            enabled = set()
    if not _prepared:
        operation_order = (
            normalize_deform_order(
                DEFORM_ORDER if deform_order is None else deform_order,
                enabled,
                deform_type,
            )
            if enabled else ()
        )

    bend_strength = (
        float(strength) if bend_strength is None and deform_type == "BEND"
        else float(bend_strength or 0.0))
    bend_direction = (
        float(direction) if bend_direction is None
        else float(bend_direction))
    twist_strength = (
        float(strength) if twist_strength is None and deform_type == "TWIST"
        else float(twist_strength or 0.0))
    taper_factor = (
        float(factor) if taper_factor is None and deform_type == "TAPER"
        else float(taper_factor or 0.0))
    stretch_factor = (
        float(factor) if stretch_factor is None and deform_type == "STRETCH"
        else float(stretch_factor or 0.0))
    try:
        shear_factors = tuple(float(value) for value in shear_factors)
    except (TypeError, ValueError, OverflowError):
        shear_factors = (0.0, 0.0)
    shear_factors = (
        shear_factors[0] if len(shear_factors) > 0 else 0.0,
        shear_factors[1] if len(shear_factors) > 1 else 0.0,
    )
    ffd_offset_vectors = (
        normalized_ffd_offsets(ffd_offsets) if "FFD" in enabled else ())

    half = size * 0.5
    configured_origin_y = {
        "BOTTOM": -half.y,
        "CENTER": 0.0,
        "SYMMETRIC": 0.0,
        "TOP": half.y,
    }[origin]
    # CHAINED uses the authored Origin for the local deformation reference.
    # The root continues from both outer ends, while downstream eligibility
    # remains one-sided so later stages cannot modify the incoming prefix.
    origin_y = configured_origin_y
    lower = -half.y - origin_y
    upper = half.y - origin_y

    # A non-root chain stage is framed from its evaluated lower boundary.
    # That boundary is not necessarily a fixed point for TOP/CENTER/
    # SYMMETRIC origins.  The inverse chain input frame maps an incoming seam
    # back to the authored lower boundary before evaluating this stage,
    # preventing the boundary deformation from being applied twice.
    chain_output = None
    if mode == "CHAINED" and chain_eligible:
        if chain_input_frame is not None:
            try:
                pivot, inverse_x, inverse_y, inverse_z = (
                    Vector(value) for value in chain_input_frame)
                delta = point - pivot
                point = Vector((
                    delta.dot(inverse_x),
                    delta.dot(inverse_y) - half.y,
                    delta.dot(inverse_z),
                ))
            except (TypeError, ValueError, RuntimeError):
                point = raw_point.copy()
        else:
            try:
                offset = Vector(chain_input_offset)
            except (TypeError, ValueError):
                offset = Vector((0.0, 0.0, 0.0))
            if len(offset) != 3 or not all(math.isfinite(value) for value in offset):
                offset = Vector((0.0, 0.0, 0.0))
            point -= offset
        if chain_output_frame is not None:
            try:
                output_offset, output_x, output_y, output_z = (
                    Vector(value) for value in chain_output_frame)
                if not all(
                        math.isfinite(component)
                        for vector in (
                            output_offset, output_x, output_y, output_z)
                        for component in vector
                ):
                    raise ValueError("non-finite chain output frame")
                chain_output = (
                    output_offset, output_x, output_y, output_z)
            except (TypeError, ValueError, RuntimeError):
                chain_output = None

    # A chained stage receives an already-deformed spatial Y from upstream,
    # but a mixed Bend stage must evaluate its profile in the original source
    # coordinate.  Geometry Nodes carries that coordinate through the point
    # domain; the optional arguments keep the Python reference evaluator and
    # frame sampling on the same authored axis.  Pure Bend remains on the
    # post-frame local Y path because its axial composition is intentionally
    # spatial.
    authored_y_input = point.y
    mixed_chain_source = (
        mode == "CHAINED" and
        chain_source_coordinate is not None and
        "BEND" in enabled and
        any(operation != "BEND" for operation in operation_order)
    )
    if mixed_chain_source:
        try:
            source_start = float(
                0.0 if chain_source_start is None else chain_source_start)
            authored_y_input = (
                float(chain_source_coordinate) - source_start - half.y)
            if not math.isfinite(authored_y_input):
                authored_y_input = point.y
        except (TypeError, ValueError, OverflowError):
            authored_y_input = point.y

    distance = authored_y_input - origin_y

    inside = (
        abs(point.x) <= half.x and
        abs(authored_y_input) <= half.y and
        abs(point.z) <= half.z
    )
    if mode == "WITHIN_BOX" and not inside:
        return raw_point.copy()
    if mode == "CHAINED" and not chain_eligible:
        return raw_point.copy()

    frame_t = (authored_y_input + half.y) / size.y
    if mode != "UNLIMITED":
        frame_t = min(max(frame_t, 0.0), 1.0)
    scale_x = bottom_scale[0] + (top_scale[0] - bottom_scale[0]) * frame_t
    scale_z = bottom_scale[1] + (top_scale[1] - bottom_scale[1]) * frame_t
    offset_x = bottom_offset[0] + (top_offset[0] - bottom_offset[0]) * frame_t
    offset_z = bottom_offset[1] + (top_offset[1] - bottom_offset[1]) * frame_t
    result = Vector((
        point.x * scale_x + offset_x,
        point.y,
        point.z * scale_z + offset_z,
    ))

    evaluated_distance = distance
    outside_distance = 0.0
    if mode == "LIMITED":
        evaluated_distance = min(max(distance, lower), upper)
        outside_distance = distance - evaluated_distance
    elif mode == "CHAINED":
        # Downstream stages preserve their incoming prefix. The root instead
        # extends its lower boundary frame over geometry exposed by an inward
        # boundary edit, matching the normal LIMITED end continuation.
        if (
                not chain_root_stage and
                distance < lower - CHAIN_BOUNDARY_EPSILON
        ):
            return raw_point.copy()
        evaluated_distance = min(max(distance, lower), upper)
        outside_distance = (
            distance - evaluated_distance
            if chain_root_stage else
            max(distance - upper, 0.0)
        )

    # A connected stage carries its terminal frame beyond the cage without
    # adding deformation in an authored gap.  Keep the compatibility
    # arguments in the public reference API, but clamp every profile at the
    # cage boundary.
    profile_outside_distance = 0.0
    profile_distance_input = evaluated_distance
    profile_distance = (
        abs(profile_distance_input)
        if origin == "SYMMETRIC" else profile_distance_input
    )
    profile = profile_distance / size.y

    def apply_chain_output(value):
        nonlocal chain_output
        if chain_output is None:
            return value
        output_offset, output_x, output_y, output_z = chain_output
        chain_output = None
        return Vector((
            value.dot(output_x) + output_offset.x,
            value.dot(output_y) + output_offset.y,
            value.dot(output_z) + output_offset.z,
        ))

    for operation in operation_order:
        if operation == "BEND" and abs(bend_strength) >= EPSILON:
            cos_direction = math.cos(bend_direction)
            sin_direction = math.sin(bend_direction)
            u = cos_direction * result.x + sin_direction * result.z
            v = -sin_direction * result.x + cos_direction * result.z
            curvature = bend_strength / size.y
            if origin == "SYMMETRIC" and authored_y_input < 0.0:
                curvature = -curvature
            radius = 1.0 / curvature
            bend_evaluated_distance = (
                evaluated_distance + profile_outside_distance)
            bend_outside_distance = (
                outside_distance - profile_outside_distance)
            theta = curvature * bend_evaluated_distance
            cosine = math.cos(theta)
            sine = math.sin(theta)
            radial = radius + u
            deformed_u = (
                radial * cosine - radius - sine * bend_outside_distance)
            authored_y = (
                origin_y + radial * sine +
                cosine * bend_outside_distance)
            result = Vector((
                cos_direction * deformed_u - sin_direction * v,
                result.y + authored_y - authored_y_input,
                sin_direction * deformed_u + cos_direction * v,
            ))
        elif operation == "TWIST":
            theta = twist_strength * profile
            cosine = math.cos(theta)
            sine = math.sin(theta)
            result = Vector((
                cosine * result.x - sine * result.z,
                result.y,
                sine * result.x + cosine * result.z,
            ))
        elif operation == "TAPER":
            scale = 1.0 + taper_factor * profile
            result = Vector((
                result.x * scale, result.y, result.z * scale))
        elif operation == "STRETCH":
            scale = 1.0 + stretch_factor
            # Preserve the endpoint displacement outside the cage without
            # stretching an unowned chain gap.
            stretch_outside = outside_distance
            authored_y = (
                origin_y + evaluated_distance * scale + stretch_outside)
            # Axial stretch is uniform over the stage.  Use that same
            # constant for volume preservation in chained stages so a
            # subdivided chain does not introduce artificial transverse
            # scaling at each seam.
            volume_scale_factor = scale
            volume_scale = (
                max(abs(volume_scale_factor), EPSILON) ** -0.5
                if preserve_volume else 1.0)
            result = Vector((
                result.x * volume_scale,
                result.y + authored_y - authored_y_input,
                result.z * volume_scale,
            ))
        elif operation == "SHEAR":
            result = Vector((
                result.x + shear_factors[0] * profile_distance,
                result.y,
                result.z + shear_factors[1] * profile_distance,
            ))
        elif operation == "FFD":
            u = point.x / max(size.x, EPSILON) + 0.5
            v = frame_t
            w = point.z / max(size.z, EPSILON) + 0.5
            if mode != "UNLIMITED":
                u = min(max(u, 0.0), 1.0)
                w = min(max(w, 0.0), 1.0)
            displacement = Vector((0.0, 0.0, 0.0))
            for offset, (_label, x_sign, y_sign, z_sign) in zip(
                    ffd_offset_vectors, FFD_CORNERS):
                weight = (
                    (u if x_sign > 0.0 else 1.0 - u) *
                    (v if y_sign > 0.0 else 1.0 - v) *
                    (w if z_sign > 0.0 else 1.0 - w)
                )
                displacement += offset * weight
            result += displacement
        elif operation == "CURVE" and curve_deformer is not None:
            try:
                result = Vector(curve_deformer(
                    result, authored_y_input, size))
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError, OverflowError):
                pass

        if operation == "BEND":
            result = apply_chain_output(result)

    return apply_chain_output(result)
