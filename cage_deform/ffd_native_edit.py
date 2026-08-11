"""Controlled access to Blender's native Lattice Edit Mode for FFD cages."""
from __future__ import annotations

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator
from mathutils import Matrix, Vector

from . import core


_SESSIONS = {}
_TIMER_REGISTERED = False
_GUARD = set()
_PROXY_CONTROLLER_MARKER = "_sdh_ffd_native_edit_controller"


def _pointer(obj):
    try:
        return int(obj.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return id(obj) if obj is not None else 0


def _runtime_scale(lattice):
    return Vector(tuple(
        max(abs(float(value)), core.EPSILON)
        for value in lattice.matrix_world.to_scale()
    ))


def _native_base_coordinate(lattice, index):
    """Return Blender's regular Lattice basis without reading edit-mode RNA."""
    data = lattice.data
    resolution = (
        int(data.points_u), int(data.points_v), int(data.points_w))
    coordinates = core.ffd_point_coordinates(index, resolution)
    return Vector(tuple(
        float(coordinate) - (float(count) - 1.0) * 0.5
        for coordinate, count in zip(coordinates, resolution)
    ))


def _supported(properties):
    return str(getattr(properties, "mode", "LIMITED")) != "UNLIMITED"


def _runtime_lattice_for(controller):
    target = core.find_target(controller)
    modifier = core.find_modifier(target, controller) if target is not None else None
    lattice = (
        core.ffd_lattice_object(target, modifier)
        if target is not None and modifier is not None else None)
    return target, modifier, lattice


def _session_key(controller):
    try:
        target = core.find_target(controller)
        modifier = core.find_modifier(target, controller)
        return core.cage_modifier_uuid(modifier) if modifier is not None else ""
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return ""


def _session_record(target, modifier, controller, proxy):
    return {
        "target_name": str(target.name),
        "target_uuid": str(target.get(core.TARGET_UUID, "")),
        "modifier_uuid": core.cage_modifier_uuid(modifier),
        "controller_name": str(controller.name),
        "proxy_name": str(proxy.name),
    }


def _resolve_session(session):
    if not session:
        return None, None, None, None
    target = bpy.data.objects.get(str(session.get("target_name", "")))
    target_uuid = str(session.get("target_uuid", ""))
    try:
        target_valid = (
            target is not None and
            str(target.get(core.TARGET_UUID, "")) == target_uuid)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        target_valid = False
    if not target_valid:
        target = next((
            candidate for candidate in core._data_objects_snapshot()
            if (
                not core.is_cage_controller(candidate) and
                str(candidate.get(core.TARGET_UUID, "")) == target_uuid
            )
        ), None)
    modifier_uuid = str(session.get("modifier_uuid", ""))
    modifier = core.find_modifier(target, modifier_uuid=modifier_uuid)
    controller = (
        core.find_controller(target, modifier)
        if target is not None and modifier is not None else None)
    proxy = bpy.data.objects.get(str(session.get("proxy_name", "")))
    if proxy is None:
        proxy = next((
            candidate for candidate in core._data_objects_snapshot()
            if (
                bool(candidate.get(core.FFD_NATIVE_EDIT_PROXY_MARKER, False)) and
                str(candidate.get(core.FFD_LATTICE_MODIFIER_MARKER, "")) ==
                modifier_uuid
            )
        ), None)
    return target, modifier, controller, proxy


def native_edit_lattice(controller):
    """Return the authored edit proxy for one active native session."""
    _target, _modifier, _controller, proxy = _resolve_session(
        _SESSIONS.get(_session_key(controller)))
    return proxy


def _remove_proxy(proxy):
    if proxy is None:
        return False
    try:
        data = getattr(proxy, "data", None)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        return False
    try:
        if getattr(proxy, "mode", "OBJECT") == "EDIT":
            bpy.ops.object.mode_set(mode="OBJECT")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        bpy.data.objects.remove(proxy, do_unlink=True)
    except (ReferenceError, RuntimeError, TypeError):
        return False
    if data is not None and getattr(data, "users", 1) == 0:
        try:
            bpy.data.lattices.remove(data)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    return True


def _create_edit_proxy(context, target, modifier, controller, runtime):
    """Create an authored lattice that never participates in deformation."""
    runtime_data = runtime.data
    data = bpy.data.lattices.new(f"{modifier.name} FFD Edit Data")
    data.points_u = int(runtime_data.points_u)
    data.points_v = int(runtime_data.points_v)
    data.points_w = int(runtime_data.points_w)
    data.use_outside = bool(getattr(runtime_data, "use_outside", False))
    for axis in ("u", "v", "w"):
        setattr(
            data,
            f"interpolation_type_{axis}",
            str(getattr(runtime_data, f"interpolation_type_{axis}")),
        )

    proxy = bpy.data.objects.new(f"{modifier.name} FFD Edit", data)
    collections = tuple(getattr(runtime, "users_collection", ()))
    collection = collections[0] if collections else getattr(context, "collection", None)
    if collection is not None:
        collection.objects.link(proxy)
    else:
        bpy.context.collection.objects.link(proxy)
    proxy.parent = target
    proxy.matrix_parent_inverse = Matrix.Identity(4)
    proxy.matrix_world = runtime.matrix_world.copy()
    proxy[core.FFD_NATIVE_EDIT_PROXY_MARKER] = True
    proxy[core.FFD_LATTICE_MODIFIER_MARKER] = core.cage_modifier_uuid(modifier)
    proxy[_PROXY_CONTROLLER_MARKER] = controller.name
    proxy.hide_render = True
    proxy.hide_select = False
    proxy.display_type = "WIRE"
    proxy.show_in_front = True

    scale = _runtime_scale(proxy)
    properties = controller.sdh_cage_deform
    for index, point in enumerate(data.points):
        raw = core.ffd_point_offset(properties, index)
        normalized = Vector(tuple(
            float(component) / float(axis_scale)
            for component, axis_scale in zip(raw, scale)
        ))
        point.co_deform = _native_base_coordinate(proxy, index) + normalized
    return proxy


def _pull(controller, lattice, *, selection=False):
    """Pull authored proxy coordinates without dividing by point weight."""
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None or lattice is None:
        return False
    points = tuple(getattr(lattice.data, "points", ()))
    authored = getattr(properties, "ffd_points", None)
    if authored is None or not points:
        return False
    scale = _runtime_scale(lattice)
    pointer = _pointer(controller)
    changed = False
    count = min(len(points), len(authored))
    current_offsets = tuple(tuple(point.offset) for point in authored)
    candidate_offsets = list(current_offsets)
    for index in range(count):
        native_delta = (
            Vector(points[index].co_deform) -
            _native_base_coordinate(lattice, index)
        )
        candidate_offsets[index] = tuple(
            float(component) * float(axis_scale)
            for component, axis_scale in zip(native_delta, scale)
        )
    safe_offsets, _fraction, _baseline_ratio, _candidate_ratio = (
        core.ffd_guard_offsets(
            properties,
            tuple(candidate_offsets),
            baseline_offsets=current_offsets,
        )
    )
    if pointer:
        _GUARD.add(pointer)
        core._FFD_POINT_GUARD.add(pointer)
    try:
        for index in range(count):
            requested = Vector(safe_offsets[index])
            if (Vector(authored[index].offset) - requested).length > core.EPSILON:
                authored[index].offset = tuple(requested)
                changed = True
            if selection:
                authored[index].selected = bool(getattr(points[index], "select", False))
        if selection:
            visible = set(core.ffd_visible_indices(properties))
            selected = [
                index for index, point in enumerate(authored)
                if bool(getattr(point, "selected", False)) and
                index in visible
            ]
            if selected:
                properties.ffd_active_point = min(
                    selected,
                    key=lambda index: (
                        index != int(getattr(properties, "ffd_active_point", -1)),
                        index,
                    ),
                )
    finally:
        if pointer:
            _GUARD.discard(pointer)
            core._FFD_POINT_GUARD.discard(pointer)
    if changed:
        try:
            core._controller_update(properties, bpy.context)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
    return True


def _restore_hidden(lattice):
    try:
        lattice.hide_select = True
        lattice.hide_set(True)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass


def _finish_session(
        context, controller=None, *, session_key=None, restore_target=True):
    session_key = str(session_key or _session_key(controller))
    session = _SESSIONS.get(session_key)
    if not session:
        return False
    target, modifier, controller, proxy = _resolve_session(session)
    runtime = (
        core.ffd_lattice_object(target, modifier)
        if target is not None and modifier is not None else None)
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        _remove_proxy(proxy)
        _SESSIONS.pop(session_key, None)
        return False
    try:
        if proxy is not None and getattr(proxy, "mode", "OBJECT") == "EDIT":
            _pull(controller, proxy)
            bpy.ops.object.mode_set(mode="OBJECT")
        if proxy is not None:
            _pull(controller, proxy, selection=True)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    try:
        properties.ffd_native_edit_mode_active = False
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    _remove_proxy(proxy)
    _restore_hidden(runtime)
    _SESSIONS.pop(session_key, None)
    if restore_target and target is not None:
        try:
            core._activate(context or bpy.context, target)
        except (AttributeError, ReferenceError, RuntimeError, TypeError):
            pass
    try:
        core.refresh_controller_display(context or bpy.context, force=True)
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    return True


def finish_native_edit_sessions(context=None, *, restore_target=True):
    """Finalize every active native Lattice session before stack changes."""
    finished = 0
    for session_key in tuple(_SESSIONS):
        if _finish_session(
                context or bpy.context, session_key=session_key,
                restore_target=restore_target):
            finished += 1
    if not _SESSIONS:
        _stop_timer()
    return finished


def _watch_sessions():
    global _TIMER_REGISTERED
    for session_key, session in tuple(_SESSIONS.items()):
        properties = None
        target = modifier = controller = proxy = None
        try:
            target, modifier, controller, proxy = _resolve_session(session)
            properties = getattr(controller, "sdh_cage_deform", None)
            if (
                    target is None or modifier is None or
                    properties is None or proxy is None or
                    not bool(getattr(
                        properties, "ffd_native_edit_mode_active", False))
            ):
                _remove_proxy(proxy)
                _SESSIONS.pop(session_key, None)
                continue
            if getattr(proxy, "mode", "OBJECT") == "EDIT":
                _pull(controller, proxy)
            else:
                _finish_session(
                    bpy.context, session_key=session_key, restore_target=True)
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            try:
                properties.ffd_native_edit_mode_active = False
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
            _remove_proxy(proxy)
            _SESSIONS.pop(session_key, None)
    if _SESSIONS:
        _TIMER_REGISTERED = True
        return 0.05
    _stop_timer()
    return None


def _ensure_timer():
    global _TIMER_REGISTERED
    if _TIMER_REGISTERED:
        return
    try:
        bpy.app.timers.register(_watch_sessions, first_interval=0.05)
        _TIMER_REGISTERED = True
    except (AttributeError, RuntimeError, TypeError, ValueError):
        _TIMER_REGISTERED = False


def _stop_timer():
    """Cancel the native-edit watcher when the last session is finalized."""
    global _TIMER_REGISTERED
    try:
        if bpy.app.timers.is_registered(_watch_sessions):
            bpy.app.timers.unregister(_watch_sessions)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        pass
    _TIMER_REGISTERED = False


def _enter(context, controller):
    target, modifier, runtime = _runtime_lattice_for(controller)
    properties = getattr(controller, "sdh_cage_deform", None)
    if target is None or modifier is None or properties is None:
        return False, "FFD cage is unavailable"
    if not _supported(properties):
        return False, "Native Lattice Edit is unavailable for Unlimited FFD"
    try:
        runtime = core.ensure_ffd_lattice(target, modifier, controller)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        runtime = None
    if runtime is None:
        return False, "Native FFD lattice could not be created"
    session_key = core.cage_modifier_uuid(modifier)
    if session_key in _SESSIONS:
        _finish_session(
            context, session_key=session_key, restore_target=False)
    # Object creation can synchronously run the global orphan pass through a
    # depsgraph update. Mark the session active before linking its proxy so
    # that pass can distinguish the live editor from a stale saved proxy.
    properties.ffd_native_edit_mode_active = True
    try:
        proxy = _create_edit_proxy(
            context, target, modifier, controller, runtime)
    except (AttributeError, ReferenceError, RuntimeError, TypeError,
            ValueError) as error:
        properties.ffd_native_edit_mode_active = False
        return False, str(error)
    core.ensure_ffd_point_collection(properties)
    visible = set(core.ffd_visible_indices(properties))
    for index, point in enumerate(proxy.data.points):
        point.select = index in visible and bool(
            properties.ffd_points[index].selected
            if index < len(properties.ffd_points) else False)
    try:
        proxy.hide_select = False
        proxy.hide_set(False, view_layer=context.view_layer)
        proxy.show_in_front = True
        for selected in tuple(context.selected_objects):
            selected.select_set(False)
        proxy.select_set(True)
        context.view_layer.objects.active = proxy
        bpy.ops.object.mode_set(mode="EDIT")
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError) as error:
        _remove_proxy(proxy)
        properties.ffd_native_edit_mode_active = False
        return False, str(error)
    _SESSIONS[session_key] = _session_record(
        target, modifier, controller, proxy)
    _ensure_timer()
    return True, ""


class SDH_OT_edit_ffd_native(Operator):
    bl_idname = "sdh.edit_ffd_native"
    bl_label = "Native Lattice Edit"
    bl_description = "Edit this FFD through Blender's native Lattice Edit Mode"
    # This operator only enters/leaves a temporary edit proxy. The actual
    # lattice transforms own the undo records; the mode toggle must not sit
    # between those edits and the user's previous history state.
    bl_options = {"REGISTER"}

    toggle: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})

    @classmethod
    def poll(cls, context):
        _target, _modifier, controller = core.resolve_context_deform(context)
        properties = getattr(controller, "sdh_cage_deform", None)
        return bool(
            properties is not None and
            str(getattr(properties, "cage_type", "")) == "FFD")

    def execute(self, context):
        _target, _modifier, controller = core.resolve_context_deform(context)
        if controller is None:
            return {"CANCELLED"}
        properties = controller.sdh_cage_deform
        if bool(getattr(properties, "ffd_native_edit_mode_active", False)):
            finish_native_edit_sessions(context, restore_target=True)
            return {"FINISHED"}
        if not _supported(properties):
            self.report({"WARNING"}, "Native Lattice Edit is unavailable for Unlimited FFD")
            return {"CANCELLED"}
        core.finish_ffd_edit_sessions(
            context, restore_target=True, include_native=False)
        ok, message = _enter(context, controller)
        if not ok:
            self.report({"ERROR"}, message)
            return {"CANCELLED"}
        return {"FINISHED"}


classes = (SDH_OT_edit_ffd_native,)
