"""Dependency-neutral deformation semantics shared by cage modules."""
from __future__ import annotations


DEFORM_ORDER = (
    "BEND", "TWIST", "TAPER", "STRETCH", "SHEAR", "FFD", "CURVE")
DEFORM_BITS = {name: 1 << index for index, name in enumerate(DEFORM_ORDER)}
DEFORM_MASK_ALL = sum(DEFORM_BITS.values())

MODE_VALUES = {
    "LIMITED": 0,
    "WITHIN_BOX": 1,
    "UNLIMITED": 2,
    "CHAINED": 3,
}
ORIGIN_VALUES = {"BOTTOM": 0, "CENTER": 1, "SYMMETRIC": 2, "TOP": 3}
CURVE_LENGTH_VALUES = {"PRESERVE": 0, "STRETCH": 1, "FIT_GUIDE": 2}
CURVE_MODE_VALUES = {"UNLIMITED": 0, "LIMITED": 1, "WITHIN_BOX": 2}

FFD_CORNERS = (
    ("Bottom X- Z-", -1.0, -1.0, -1.0),
    ("Bottom X+ Z-", 1.0, -1.0, -1.0),
    ("Bottom X+ Z+", 1.0, -1.0, 1.0),
    ("Bottom X- Z+", -1.0, -1.0, 1.0),
    ("Top X- Z-", -1.0, 1.0, -1.0),
    ("Top X+ Z-", 1.0, 1.0, -1.0),
    ("Top X+ Z+", 1.0, 1.0, 1.0),
    ("Top X- Z+", -1.0, 1.0, 1.0),
)
FFD_SOCKET_NAMES = tuple(
    f"FFD {label} Offset" for label, *_signs in FFD_CORNERS)
FFD_COMPONENT_COUNT = len(FFD_CORNERS) * 3

EPSILON = 1.0e-5
CHAIN_BOUNDARY_EPSILON = 1.0e-4
CHAIN_GAP_MAX = 0.99


def _deform_name(value):
    """Decode one persisted order value without trusting its RNA source."""
    if isinstance(value, str):
        return value if value in DEFORM_BITS else None
    try:
        index = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return DEFORM_ORDER[index] if 0 <= index < len(DEFORM_ORDER) else None


def normalize_deform_order(values, enabled=None, fallback="BEND"):
    """Return a unique, enabled, non-empty tuple of deformation names."""
    if hasattr(values, "deform_order"):
        properties = values
        values = getattr(properties, "deform_order", ())
        if enabled is None:
            enabled = getattr(properties, "deform_types", None)
        fallback = getattr(properties, "deform_type", fallback)

    if isinstance(values, (str, int)):
        values = (values,)
    try:
        raw_values = tuple(values)
    except (TypeError, ValueError):
        raw_values = ()

    if enabled is None:
        allowed = None
    else:
        if isinstance(enabled, (str, int)):
            enabled = (enabled,)
        try:
            allowed = {
                name for name in (_deform_name(value) for value in enabled)
                if name is not None
            }
        except (TypeError, ValueError):
            allowed = set()
        if not allowed:
            allowed = {
                fallback if fallback in DEFORM_BITS else DEFORM_ORDER[0]
            }

    ordered = []
    for value in raw_values:
        name = _deform_name(value)
        if (
                name is not None and name not in ordered and
                (allowed is None or name in allowed)
        ):
            ordered.append(name)
    if allowed is not None:
        ordered.extend(
            name for name in DEFORM_ORDER
            if name in allowed and name not in ordered
        )
    if not ordered:
        ordered.append(
            fallback if fallback in DEFORM_BITS else DEFORM_ORDER[0])
    return tuple(ordered)


def _full_deform_order(values):
    active = normalize_deform_order(values)
    return active + tuple(name for name in DEFORM_ORDER if name not in active)


def deform_order_signature(values):
    return ",".join(_full_deform_order(values))
