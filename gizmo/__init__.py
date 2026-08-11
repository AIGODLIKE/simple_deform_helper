import bpy

from .angle_and_factor import AngleGizmo, AngleGizmoGroup
from .bend_axis import BendAxiSwitchGizmoGroup, CustomGizmo
from .set_deform_axis import SetDeformGizmoGroup
from .up_down_limits_point import UpDownLimitsGizmo, UpDownLimitsGizmoGroup
from .z_rotate import ZRotateGizmo, ZRotateGizmoGroup
from ..draw import Draw3D

class_list = (
    UpDownLimitsGizmo,
    UpDownLimitsGizmoGroup,

    AngleGizmo,
    AngleGizmoGroup,

    ZRotateGizmo,
    ZRotateGizmoGroup,

    CustomGizmo,
    BendAxiSwitchGizmoGroup,

    SetDeformGizmoGroup,
)

_HANDLER_SPECS = (
    ("handler", "WINDOW"),
    (Draw3D.text_key, "WINDOW"),
)
_registered_classes = []
_registered_handlers = []


def _register_draw_handlers():
    missing = {
        key for key, _region in _HANDLER_SPECS
        if key not in Draw3D.G_HandleData
    }
    try:
        Draw3D.add_handler()
    finally:
        # add_handler() creates the view handler before the text handler. If
        # the second call fails, retain ownership of the first for rollback.
        owned_keys = {key for key, _handle, _region in _registered_handlers}
        for key, region in _HANDLER_SPECS:
            if key not in missing or key in owned_keys:
                continue
            handle = Draw3D.G_HandleData.get(key)
            if handle is not None:
                _registered_handlers.append((key, handle, region))


def _cleanup_registration():
    for item in reversed(tuple(_registered_classes)):
        try:
            bpy.utils.unregister_class(item)
        except (RuntimeError, ValueError):
            pass
    _registered_classes.clear()

    owned_handlers = tuple(_registered_handlers)
    for key, handle, region in reversed(owned_handlers):
        # Do not remove a handler that another registration replaced.
        if Draw3D.G_HandleData.get(key) is not handle:
            continue
        try:
            bpy.types.SpaceView3D.draw_handler_remove(handle, region)
        except (ReferenceError, RuntimeError, ValueError):
            pass
        finally:
            if Draw3D.G_HandleData.get(key) is handle:
                Draw3D.G_HandleData.pop(key, None)
    _registered_handlers.clear()

    if owned_handlers and not any(
            key in Draw3D.G_HandleData for key, _region in _HANDLER_SPECS):
        Draw3D.G_HandleData.pop("draw_error", None)
        Draw3D.G_ShaderData.clear()


def register():
    if _registered_classes or _registered_handlers:
        return
    try:
        _register_draw_handlers()
        for item in class_list:
            bpy.utils.register_class(item)
            _registered_classes.append(item)
    except Exception:
        _cleanup_registration()
        raise


def unregister():
    _cleanup_registration()
