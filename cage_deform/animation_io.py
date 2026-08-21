"""Cage keyframe channels and animation baking.

Extracted from ``core`` so the oversized module keeps shrinking; ``core``
re-exports every public name for compatibility with older scripts and tests.
"""
from __future__ import annotations

import hashlib
import math
from array import array

import bpy
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty,
)
from bpy.types import Operator

from . import core


_CAGE_ANIMATION_GROUP = "Simple Deform Cage"
_BAKED_ANIMATION_GROUP = "Baked Cage Animation"
_BAKED_ANIMATION_MARKER = "_sdh_baked_cage_animation"
_BAKED_SOURCE_NAME = "_sdh_baked_source_name"
_BAKED_FRAME_START = "_sdh_baked_frame_start"
_BAKED_FRAME_END = "_sdh_baked_frame_end"
_BAKED_FRAME_STEP = "_sdh_baked_frame_step"
_CAGE_ANIMATED_PROPERTIES = (
    "bend_strength",
    "bend_direction",
    "twist_strength",
    "taper_factor",
    "stretch_factor",
    "shear_factors",
    "ffd_offsets",
    "curve_control_mode",
    "curve_length_mode",
    "curve_mode",
    "curve_boundary_mode",
    "curve_range_start",
    "curve_range_end",
    "curve_global_radius",
    "curve_global_twist",
    "curve_relative_binding",
    "curve_closed",
    "curve_preserve_volume",
    "stage_enabled",
    "preserve_volume",
    "influence_weight",
    "top_scale",
    "bottom_scale",
    "top_offset",
    "bottom_offset",
    "size",
)

# Property paths owned by one deformation layer. Used by the layer-scoped
# keyframe operators so animators can key a single operation of a stack.
_LAYER_PROPERTY_PATHS = {
    "BEND": ("bend_strength", "bend_direction"),
    "TWIST": ("twist_strength",),
    "TAPER": ("taper_factor",),
    "STRETCH": ("stretch_factor",),
    "SHEAR": ("shear_factors",),
    "FFD": ("ffd_offsets",),
    "CURVE": (
        "curve_control_mode",
        "curve_length_mode",
        "curve_mode",
        "curve_boundary_mode",
        "curve_range_start",
        "curve_range_end",
        "curve_global_radius",
        "curve_global_twist",
        "curve_relative_binding",
        "curve_closed",
        "curve_preserve_volume",
    ),
}


def _cage_animation_paths(controller):
    """Return the current cage's animatable property and transform paths."""
    paths = [f"sdh_cage_deform.{name}" for name in _CAGE_ANIMATED_PROPERTIES]
    properties = getattr(controller, "sdh_cage_deform", None)
    if (
            properties is not None and
            str(getattr(properties, "cage_type", "STANDARD")) == "FFD"
    ):
        core.ensure_ffd_point_collection(properties)
        for index in core.ffd_keyframe_indices(properties):
            paths.extend((
                f"sdh_cage_deform.ffd_points[{index}].offset",
                f"sdh_cage_deform.ffd_points[{index}].influence",
            ))
    if (
            properties is not None and
            str(getattr(properties, "cage_type", "STANDARD")) == "CURVE"
    ):
        try:
            from .curve import curve_animation_paths
            paths.extend(curve_animation_paths(controller))
        except (ImportError, ReferenceError, RuntimeError):
            pass
    rotation_mode = str(getattr(controller, "rotation_mode", "XYZ"))
    rotation_path = {
        "QUATERNION": "rotation_quaternion",
        "AXIS_ANGLE": "rotation_axis_angle",
    }.get(rotation_mode, "rotation_euler")
    paths.extend(("location", rotation_path))
    return tuple(paths)


def _keyframe_paths(controller, paths, *, delete=False):
    changed = 0
    for data_path in paths:
        try:
            result = (
                controller.keyframe_delete(
                    data_path, group=_CAGE_ANIMATION_GROUP)
                if delete else
                controller.keyframe_insert(
                    data_path, group=_CAGE_ANIMATION_GROUP)
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            result = False
        changed += int(bool(result))
    return changed


def _keyframe_ffd_points(controller, *, delete=False):
    """Key FFD points according to the user-configured point scope."""
    properties = getattr(controller, "sdh_cage_deform", None)
    if (
            properties is None or
            str(getattr(properties, "cage_type", "STANDARD")) != "FFD"
    ):
        return 0
    core.ensure_ffd_point_collection(properties)
    paths = tuple(
        path
        for index in core.ffd_keyframe_indices(properties)
        for path in (
            f"sdh_cage_deform.ffd_points[{index}].offset",
            f"sdh_cage_deform.ffd_points[{index}].influence",
        ))
    return _keyframe_paths(controller, paths, delete=delete)


def _keyframe_cage_paths(controller, *, delete=False):
    changed = _keyframe_paths(
        controller, _cage_animation_paths(controller), delete=delete)
    properties = getattr(controller, "sdh_cage_deform", None)
    if (
            properties is not None and
            str(getattr(properties, "cage_type", "STANDARD")) == "CURVE"
    ):
        try:
            from .curve import keyframe_curve_guide
            changed += keyframe_curve_guide(
                controller, delete=delete, group=_CAGE_ANIMATION_GROUP)
        except (ImportError, ReferenceError, RuntimeError):
            pass
    return changed


def _active_layer_name(properties):
    """Return the deformation layer the user is currently editing."""
    cage_type = str(getattr(properties, "cage_type", "STANDARD"))
    locked = {"FFD": "FFD", "CURVE": "CURVE", "SHEAR": "SHEAR"}.get(cage_type)
    if locked:
        return locked
    ordered = core.ordered_deform_types(properties)
    if not ordered:
        return "BEND"
    index = int(getattr(properties, "active_deform_layer", 0))
    return ordered[min(max(index, 0), len(ordered) - 1)]


def _keyframe_layer_paths(controller, *, delete=False):
    """Key only the active deformation layer's parameters."""
    properties = getattr(controller, "sdh_cage_deform", None)
    if properties is None:
        return 0
    layer = _active_layer_name(properties)
    paths = tuple(
        f"sdh_cage_deform.{name}"
        for name in _LAYER_PROPERTY_PATHS.get(layer, ())
    )
    changed = _keyframe_paths(controller, paths, delete=delete)
    if layer == "FFD":
        changed += _keyframe_ffd_points(controller, delete=delete)
    elif layer == "CURVE":
        try:
            from .curve import keyframe_curve_guide
            changed += keyframe_curve_guide(
                controller, delete=delete, group=_CAGE_ANIMATION_GROUP)
        except (ImportError, ReferenceError, RuntimeError):
            pass
    return changed


def _bake_frame_samples(frame_start, frame_end, step):
    frame_start = float(frame_start)
    frame_end = float(frame_end)
    step = float(step)
    if frame_end < frame_start:
        raise ValueError(iface_(
            "End Frame must not be earlier than Start Frame"))
    if step < 0.01:
        raise ValueError(iface_("Sample Step must be at least 0.01"))
    frames = []
    current = frame_start
    while current < frame_end - 1.0e-9:
        frames.append(round(current, 6))
        current += step
    frames.append(float(frame_end))
    return tuple(frames)


def _mesh_topology_signature(mesh):
    """Return a connectivity signature suitable for shape-key baking."""
    if mesh is None or not getattr(mesh, "vertices", None):
        raise RuntimeError(iface_("The evaluated geometry has no vertices"))
    digest = hashlib.blake2b(digest_size=16)
    collections = (
        (mesh.edges, "vertices", 2),
        (mesh.loops, "vertex_index", 1),
        (mesh.polygons, "loop_start", 1),
        (mesh.polygons, "loop_total", 1),
    )
    for collection, property_name, width in collections:
        values = array("i", [0]) * (len(collection) * width)
        if values:
            collection.foreach_get(property_name, values)
            digest.update(values.tobytes())
    return (
        len(mesh.vertices),
        len(mesh.edges),
        len(mesh.loops),
        len(mesh.polygons),
        digest.digest(),
    )


def _mesh_vertex_coordinates(mesh):
    coordinates = array("f", [0.0]) * (len(mesh.vertices) * 3)
    mesh.vertices.foreach_get("co", coordinates)
    return coordinates


def _evaluated_mesh_snapshot(target, depsgraph):
    evaluated = target.evaluated_get(depsgraph)
    mesh = None
    try:
        mesh = evaluated.to_mesh(
            preserve_all_data_layers=True,
            depsgraph=depsgraph,
        )
        if mesh is None:
            raise RuntimeError(iface_(
                "The evaluated object could not be converted to a mesh"))
        return _mesh_topology_signature(mesh), _mesh_vertex_coordinates(mesh)
    finally:
        if mesh is not None:
            evaluated.to_mesh_clear()


def _iter_baked_action_fcurves(action):
    """Yield legacy and Blender 5 layered F-Curves for the bake Action."""
    if action is None:
        return
    seen = set()

    def emit(curves):
        for curve in tuple(curves or ()):
            pointer = core._pointer(curve) or id(curve)
            if pointer in seen:
                continue
            seen.add(pointer)
            yield curve

    yield from emit(getattr(action, "fcurves", ()))
    slots = tuple(getattr(action, "slots", ()) or ())
    for layer in tuple(getattr(action, "layers", ()) or ()):
        for strip in tuple(getattr(layer, "strips", ()) or ()):
            yield from emit(getattr(strip, "fcurves", ()))
            channelbags = tuple(getattr(strip, "channelbags", ()) or ())
            if channelbags:
                for channelbag in channelbags:
                    yield from emit(getattr(channelbag, "fcurves", ()))
                continue
            accessor = getattr(strip, "channelbag", None)
            if not callable(accessor):
                continue
            for slot in slots:
                try:
                    channelbag = accessor(slot)
                except (AttributeError, ReferenceError, RuntimeError,
                        TypeError, ValueError):
                    continue
                yield from emit(getattr(channelbag, "fcurves", ()))


def _linearize_baked_eval_time(shape_keys):
    animation = getattr(shape_keys, "animation_data", None)
    action = getattr(animation, "action", None) if animation else None
    if action is not None:
        action.name = f"{shape_keys.name} Action"
    for curve in _iter_baked_action_fcurves(action):
        if str(getattr(curve, "data_path", "")) != "eval_time":
            continue
        for keyframe in tuple(getattr(curve, "keyframe_points", ()) or ()):
            keyframe.interpolation = "LINEAR"


def _prepare_bake_frame(context, frame):
    frame = float(frame)
    whole = int(math.floor(frame))
    subframe = min(max(frame - whole, 0.0), 0.999999)
    context.scene.frame_set(whole, subframe=subframe)
    core.sync_all_controllers(pull_transform=True, sync_mode="timer")
    core._drain_chain_reconnect_queue()
    core._drain_stack_auto_fit_queue()
    context.view_layer.update()
    return context.evaluated_depsgraph_get()


def bake_cage_animation_to_shape_keys(
        context, target, frame_start, frame_end, step=1, result_name=""):
    """Bake evaluated cage animation to an independent absolute-key mesh."""
    if target is None or getattr(target, "type", None) not in core.SUPPORTED_TYPES:
        raise RuntimeError(iface_("Select a supported target object first"))
    frames = _bake_frame_samples(frame_start, frame_end, step)
    scene = context.scene
    original_frame = int(scene.frame_current)
    original_subframe = float(getattr(scene, "frame_subframe", 0.0))
    source_matrix = target.matrix_world.copy()
    result_name = str(result_name or "").strip() or f"{target.name} Baked"
    baked = None
    baked_mesh = None
    progress_started = False
    try:
        context.window_manager.progress_begin(0, len(frames))
        progress_started = True
        depsgraph = _prepare_bake_frame(context, frames[0])
        evaluated = target.evaluated_get(depsgraph)
        baked_mesh = bpy.data.meshes.new_from_object(
            evaluated,
            preserve_all_data_layers=True,
            depsgraph=depsgraph,
        )
        if baked_mesh is None:
            raise RuntimeError(iface_(
                "The evaluated object could not be converted to a mesh"))
        topology = _mesh_topology_signature(baked_mesh)
        baked_mesh.name = f"{result_name} Mesh"
        baked = bpy.data.objects.new(result_name, baked_mesh)
        target_collections = tuple(getattr(target, "users_collection", ()))
        collection = (
            target_collections[0] if target_collections
            else getattr(context, "collection", None) or scene.collection
        )
        baked.matrix_world = source_matrix
        for attribute in ("color", "display_type", "show_in_front"):
            try:
                setattr(baked, attribute, getattr(target, attribute))
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                pass

        basis = baked.shape_key_add(name="Basis", from_mix=False)
        basis.interpolation = "KEY_LINEAR"
        shape_keys = baked_mesh.shape_keys
        shape_keys.name = f"{baked.name} Shape Keys"
        shape_keys.use_relative = False
        shape_keys.eval_time = 0.0
        shape_keys.keyframe_insert(
            "eval_time", frame=frames[0], group=_BAKED_ANIMATION_GROUP)
        context.window_manager.progress_update(1)

        for index, frame in enumerate(frames[1:], start=1):
            depsgraph = _prepare_bake_frame(context, frame)
            current_topology, coordinates = _evaluated_mesh_snapshot(
                target, depsgraph)
            if current_topology != topology:
                raise RuntimeError(iface_(
                    "Topology changes at frame {frame}; shape-key baking "
                    "requires stable topology").format(frame=frame))
            shape = baked.shape_key_add(
                name=f"Frame {frame:g}", from_mix=False)
            shape.interpolation = "KEY_LINEAR"
            shape.data.foreach_set("co", coordinates)
            shape_keys.eval_time = float(index * 10)
            shape_keys.keyframe_insert(
                "eval_time", frame=frame, group=_BAKED_ANIMATION_GROUP)
            context.window_manager.progress_update(index + 1)

        _linearize_baked_eval_time(shape_keys)
        baked[_BAKED_ANIMATION_MARKER] = True
        baked[_BAKED_SOURCE_NAME] = target.name_full
        baked[_BAKED_FRAME_START] = float(frames[0])
        baked[_BAKED_FRAME_END] = float(frames[-1])
        baked[_BAKED_FRAME_STEP] = float(step)
        baked_mesh.update()
        # Keep the result outside the dependency graph while sampling. This
        # prevents collection-driven source modifiers from accidentally
        # ingesting the partially built bake and changing their own topology.
        collection.objects.link(baked)
        return baked, len(frames)
    except Exception:
        if baked is not None:
            try:
                bpy.data.objects.remove(baked, do_unlink=True)
            except (ReferenceError, RuntimeError):
                pass
        if baked_mesh is not None and baked_mesh.users == 0:
            try:
                bpy.data.meshes.remove(baked_mesh)
            except (ReferenceError, RuntimeError):
                pass
        raise
    finally:
        try:
            scene.frame_set(original_frame, subframe=original_subframe)
            context.view_layer.update()
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError):
            pass
        if progress_started:
            context.window_manager.progress_end()


def _finish_edit_sessions(context):
    core.finish_ffd_edit_sessions(context, restore_target=False)
    try:
        from .curve import (
            finish_curve_edit_sessions,
            finish_curve_object_edit_sessions,
        )
        finish_curve_object_edit_sessions(context, restore_target=False)
        finish_curve_edit_sessions(context, restore_target=False)
    except (ImportError, ReferenceError, RuntimeError):
        pass


def _replace_source_with_bake(context, target, baked):
    """Keep the source Object identity and replace only its evaluated mesh."""
    if getattr(target, "type", None) != "MESH":
        raise RuntimeError(iface_(
            "Replace Source requires a mesh target; bake to a new object "
            "instead"))
    _finish_edit_sessions(context)
    original_data_name = str(getattr(getattr(target, "data", None), "name", ""))
    source_data = getattr(target, "data", None)
    baked_data = getattr(baked, "data", None)
    if baked_data is None or not isinstance(baked_data, bpy.types.Mesh):
        raise RuntimeError(iface_("The baked result has no mesh data"))
    stages = core.cage_modifiers(target)
    modifier_uuids = {core.cage_modifier_uuid(modifier) for modifier in stages}
    node_groups = tuple(dict.fromkeys(
        getattr(modifier, "node_group", None) for modifier in stages))
    controllers = tuple(
        obj for obj in bpy.data.objects
        if core.is_cage_controller(obj) and
        getattr(obj, "parent", None) == target and
        str(obj.get(core.MODIFIER_UUID, "")) in modifier_uuids
    )
    for modifier in stages:
        core.remove_ffd_lattice(target, modifier)
        try:
            from .curve import remove_curve_companions
            remove_curve_companions(target, modifier)
        except (ImportError, ReferenceError, RuntimeError):
            pass
        target.modifiers.remove(modifier)
    for controller in controllers:
        bpy.data.objects.remove(controller, do_unlink=True)
    for legacy_modifier in tuple(
            modifier for modifier in getattr(target, "modifiers", ())
            if modifier.type == "SIMPLE_DEFORM"):
        core.remove_legacy_simple_deform(target, legacy_modifier)
    # The baked mesh is the fully evaluated object. Leaving any unrelated
    # modifier on the retained Object would apply it a second time.
    for remaining_modifier in tuple(getattr(target, "modifiers", ())):
        target.modifiers.remove(remaining_modifier)
    for node_group in node_groups:
        if (
                node_group and node_group.users == 0 and
                node_group.get(core.MODIFIER_MARKER, False)
        ):
            bpy.data.node_groups.remove(node_group)
    target.data = baked_data
    for key in (
            _BAKED_ANIMATION_MARKER, _BAKED_SOURCE_NAME,
            _BAKED_FRAME_START, _BAKED_FRAME_END, _BAKED_FRAME_STEP):
        if key in baked:
            target[key] = baked[key]
    bpy.data.objects.remove(baked, do_unlink=True)
    if (
            source_data is not None and
            getattr(source_data, "users", 1) == 0 and
            isinstance(source_data, bpy.types.Mesh)
    ):
        try:
            bpy.data.meshes.remove(source_data)
        except (ReferenceError, RuntimeError, TypeError):
            pass
    core.remove_unused_control_collections()
    try:
        if original_data_name:
            baked_data.name = original_data_name
    except (AttributeError, ReferenceError, RuntimeError, TypeError):
        pass
    return target


def _export_alembic(context, target, filepath, frame_start, frame_end):
    filepath = str(filepath or "").strip()
    if not filepath:
        raise RuntimeError(iface_("Choose an Alembic output path first"))
    filepath = bpy.path.abspath(filepath)
    if not filepath.lower().endswith(".abc"):
        filepath += ".abc"
    core._activate(context, target)
    for obj in tuple(context.selected_objects or ()):
        if obj != target:
            try:
                obj.select_set(False)
            except (AttributeError, ReferenceError, RuntimeError):
                pass
    try:
        target.select_set(True)
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    options = {
        "filepath": filepath,
        "start": int(frame_start),
        "end": int(frame_end),
        "selected": True,
        "visible_objects_only": False,
        "flatten": False,
        "apply_subdiv": False,
        "evaluation_mode": "VIEWPORT",
    }
    # Blender 5.x dropped/renamed some exporter keywords (for example
    # ``visible_objects_only``); keep only the ones this build accepts.
    known = bpy.ops.wm.alembic_export.get_rna_type().properties.keys()
    result = bpy.ops.wm.alembic_export(
        **{key: value for key, value in options.items() if key in known})
    if "FINISHED" not in result:
        raise RuntimeError(iface_("Alembic export did not finish"))
    return filepath


class SDH_OT_insert_cage_keyframes(Operator):
    bl_idname = "sdh.insert_cage_keyframes"
    bl_label = "Insert Deformation Keyframes"
    bl_description = (
        "Key the active cage or traditional Simple Deform stage on the "
        "current frame"
    )
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    layer_only: BoolProperty(
        name="Active Layer Only",
        description="Key only the active deformation layer's parameters",
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        target = core.deform_stack_target_from_context(context)
        active = getattr(getattr(target, "modifiers", None), "active", None)
        return bool(target and active in core.deform_stack_modifiers(target))

    def execute(self, context):
        target = core.deform_stack_target_from_context(context)
        modifier = getattr(getattr(target, "modifiers", None), "active", None)
        if target is None or modifier not in core.deform_stack_modifiers(target):
            return {"CANCELLED"}
        if modifier.type == "SIMPLE_DEFORM":
            from ..ops.key_frame import keyframe_simple_deform
            count = keyframe_simple_deform(modifier)
        else:
            controller = core.find_controller(target, modifier)
            if controller is None:
                return {"CANCELLED"}
            count = (
                _keyframe_layer_paths(controller)
                if self.layer_only else _keyframe_cage_paths(controller))
        self.report(
            {"INFO"},
            iface_("Inserted {count} deformation keyframe channels").format(
                count=count),
        )
        return {"FINISHED"}


class SDH_OT_delete_cage_keyframes(Operator):
    bl_idname = "sdh.delete_cage_keyframes"
    bl_label = "Delete Deformation Keyframes"
    bl_description = (
        "Delete current-frame keys for the active cage or traditional "
        "Simple Deform stage"
    )
    bl_options = {"REGISTER", "UNDO", "INTERNAL"}

    layer_only: BoolProperty(
        name="Active Layer Only",
        description=(
            "Delete keys only for the active deformation layer's parameters"),
        default=False,
        options={"SKIP_SAVE"},
    )

    @classmethod
    def poll(cls, context):
        target = core.deform_stack_target_from_context(context)
        active = getattr(getattr(target, "modifiers", None), "active", None)
        return bool(target and active in core.deform_stack_modifiers(target))

    def execute(self, context):
        target = core.deform_stack_target_from_context(context)
        modifier = getattr(getattr(target, "modifiers", None), "active", None)
        if target is None or modifier not in core.deform_stack_modifiers(target):
            return {"CANCELLED"}
        if modifier.type == "SIMPLE_DEFORM":
            from ..ops.key_frame import keyframe_simple_deform
            count = keyframe_simple_deform(modifier, delete=True)
        else:
            controller = core.find_controller(target, modifier)
            if controller is None:
                return {"CANCELLED"}
            count = (
                _keyframe_layer_paths(controller, delete=True)
                if self.layer_only
                else _keyframe_cage_paths(controller, delete=True))
        self.report(
            {"INFO"},
            iface_("Removed {count} deformation keyframe channels").format(
                count=count),
        )
        return {"FINISHED"}


class SDH_OT_bake_cage_animation(Operator):
    bl_idname = "sdh.bake_cage_animation"
    bl_label = "Bake Mesh Animation"
    bl_description = (
        "Bake the evaluated cage animation to shape keys, replace the "
        "source in place, or export an Alembic file"
    )
    bl_options = {"REGISTER", "UNDO"}

    bake_output: EnumProperty(
        name="Output",
        description="Where the baked animation is written",
        items=(
            (
                "OBJECT", "New Object",
                "Bake absolute shape keys onto a new independent mesh object",
            ),
            (
                "REPLACE", "Replace Source",
                "Bake to a new mesh, remove the managed deformation stack "
                "and the source object, and take over the source name",
            ),
            (
                "ALEMBIC", "Alembic File",
                "Export the evaluated animation to an Alembic (.abc) cache "
                "without creating shape keys",
            ),
        ),
        default="OBJECT",
    )
    frame_start: IntProperty(
        name="Start Frame",
        description="First scene frame to sample",
        default=1,
    )
    frame_end: IntProperty(
        name="End Frame",
        description="Last scene frame to sample",
        default=250,
    )
    step: FloatProperty(
        name="Sample Step",
        description=(
            "Scene frames between baked samples; values below 1.0 add "
            "subframe samples"
        ),
        default=1.0,
        min=0.05,
        soft_max=10.0,
    )
    result_name: StringProperty(
        name="Result Name",
        description="Name of the new independent mesh object",
        default="",
    )
    filepath: StringProperty(
        name="Alembic Path",
        description="Output .abc file path",
        subtype="FILE_PATH",
        default="//cage_bake.abc",
    )
    hide_source: BoolProperty(
        name="Hide Source",
        description=(
            "Hide the source object in the viewport and renders after a "
            "successful bake"
        ),
        default=True,
    )

    @classmethod
    def poll(cls, context):
        target = core.deform_stack_target_from_context(context)
        return bool(
            target and target.type in core.SUPPORTED_TYPES and
            core.deform_stack_modifiers(target))

    def invoke(self, context, _event):
        target = core.deform_stack_target_from_context(context)
        self.frame_start = int(context.scene.frame_start)
        self.frame_end = int(context.scene.frame_end)
        if target is not None and not self.result_name:
            self.result_name = f"{target.name} Baked"
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, _context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, "bake_output")
        layout.prop(self, "frame_start")
        layout.prop(self, "frame_end")
        if self.bake_output == "ALEMBIC":
            layout.prop(self, "filepath")
        else:
            layout.prop(self, "step")
        if self.bake_output == "OBJECT":
            layout.prop(self, "result_name")
            layout.prop(self, "hide_source")

    def execute(self, context):
        target = core.deform_stack_target_from_context(context)
        if target is None:
            return {"CANCELLED"}
        _finish_edit_sessions(context)
        if self.bake_output == "ALEMBIC":
            try:
                exported = _export_alembic(
                    context, target, self.filepath,
                    self.frame_start, self.frame_end)
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError) as error:
                self.report({"ERROR"}, str(error))
                return {"CANCELLED"}
            self.report(
                {"INFO"},
                iface_("Exported Alembic cache to {path}").format(
                    path=exported),
            )
            return {"FINISHED"}
        if self.bake_output == "REPLACE":
            try:
                from .merge import is_deform_merge, merge_owner
                if is_deform_merge(target) or merge_owner(target) is not None:
                    self.report({"ERROR"}, iface_(
                        "Replace Source is unavailable for multi-object "
                        "merges; bake to a new object instead"))
                    return {"CANCELLED"}
            except (ImportError, ReferenceError, RuntimeError):
                pass
            if getattr(target, "type", None) != "MESH":
                self.report({"ERROR"}, iface_(
                    "Replace Source requires a mesh target; bake to a new "
                    "object instead"))
                return {"CANCELLED"}
        try:
            baked, count = bake_cage_animation_to_shape_keys(
                context,
                target,
                self.frame_start,
                self.frame_end,
                self.step,
                self.result_name,
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError,
                ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        result_object = baked
        if self.bake_output == "REPLACE":
            try:
                result_object = _replace_source_with_bake(
                    context, target, baked)
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError) as error:
                self.report(
                    {"ERROR"},
                    iface_("Source replacement failed: {error}").format(
                        error=error),
                )
                return {"CANCELLED"}
        elif self.hide_source:
            try:
                target.hide_set(True)
                target.hide_render = True
            except (AttributeError, ReferenceError, RuntimeError, TypeError):
                pass
        core._activate(context, result_object)
        self.report(
            {"INFO"},
            iface_("Baked {count} frames to {name}").format(
                count=count, name=result_object.name),
        )
        return {"FINISHED"}
