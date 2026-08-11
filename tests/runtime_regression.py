"""Blender runtime regressions for Simple Deform Helper.

Run with:
    blender --background --factory-startup --python tests/runtime_regression.py
"""

import importlib
import math
import sys
import traceback
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))
failures = []


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def case(name, function):
    try:
        value = function()
    except Exception as exc:
        failures.append((name, type(exc).__name__, str(exc)))
        print(f"SDH::{name}::FAIL::{type(exc).__name__}::{exc}")
        traceback.print_exc()
    else:
        print(f"SDH::{name}::PASS::{value!r}")


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_strip():
    vertices = []
    faces = []
    for index in range(13):
        z = -3.0 + index * 0.5
        vertices.extend(((-0.6, 0.0, z), (0.6, 0.0, z)))
        if index:
            base = index * 2
            faces.append((base - 2, base, base + 1, base - 1))
    mesh = bpy.data.meshes.new("SDH Regression Strip")
    mesh.from_pydata(vertices, (), faces)
    obj = bpy.data.objects.new("SDH Regression Strip", mesh)
    bpy.context.collection.objects.link(obj)
    activate(obj)
    return obj


def rounded_bounds(bounds):
    return tuple(tuple(round(value, 5) for value in point) for point in bounds)


addon_entry = bpy.context.preferences.addons.new()
addon_entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()

stages_module = importlib.import_module(f"{PACKAGE}.stages")
utils_module = importlib.import_module(f"{PACKAGE}.utils")
msgbus_module = importlib.import_module(f"{PACKAGE}.msgbus")
update_module = importlib.import_module(f"{PACKAGE}.update")
angle_module = importlib.import_module(f"{PACKAGE}.gizmo.angle_and_factor")
header_module = importlib.import_module(f"{PACKAGE}.ui.header")
preferences_module = importlib.import_module(f"{PACKAGE}.preferences")
viewport_module = importlib.import_module(f"{PACKAGE}.cage_deform.viewport")
StageCache = stages_module.StageCache
PublicData = utils_module.PublicData
helper = utils_module.GizmoUpdate()

obj = make_strip()
first = obj.modifiers.new("Bend First", "SIMPLE_DEFORM")
first.deform_method = "BEND"
first.angle = math.radians(65.0)
middle = obj.modifiers.new("Solidify Between", "SOLIDIFY")
middle.thickness = 0.25
second = obj.modifiers.new("Twist Second", "SIMPLE_DEFORM")
second.deform_method = "TWIST"
second.angle = math.radians(90.0)
obj.modifiers.active = first


def multi_stage_bounds():
    check(StageCache.rebuild(bpy.context, obj), "stage rebuild failed")
    stages = StageCache.stages_for(obj)
    check(len(stages) == 2, f"expected two stages, got {len(stages)}")
    check([stage.stack_index for stage in stages] == [0, 2], "stack positions are wrong")
    check(stages[0].modifier_pointer == int(first.as_pointer()), "first identity is wrong")
    check(stages[1].modifier_pointer == int(second.as_pointer()), "second identity is wrong")
    first_bounds = rounded_bounds(stages[0].input_bounds)
    second_bounds = rounded_bounds(stages[1].input_bounds)
    check(first_bounds != second_bounds, "preceding modifier stack was not evaluated")
    check(not any(item.get(stages_module.RUNTIME_STAGE_OBJECT, False)
                  for item in bpy.data.objects), "stage clone leaked")
    obj.modifiers.active = second
    check(rounded_bounds(helper.modifier_bound_co) == second_bounds,
          "active stage did not use its cached bounds")
    return first_bounds, second_bounds


case("multi_stage_bounds", multi_stage_bounds)


def runtime_evaluators_are_hidden():
    stage_visibility = []
    preview_visibility = []
    original_stage_hide = stages_module.hide_runtime_object
    original_preview_hide = utils_module.hide_runtime_object

    def audit_stage(item, scene=None):
        result = original_stage_hide(item, scene)
        stage_visibility.append(bool(item.hide_get()))
        return result

    def audit_preview(item, scene=None):
        result = original_preview_hide(item, scene)
        preview_visibility.append(bool(item.hide_get()))
        return result

    stages_module.hide_runtime_object = audit_stage
    utils_module.hide_runtime_object = audit_preview
    try:
        check(StageCache.rebuild(bpy.context, obj), "stage evaluator did not run")
        helper.pref.update_deform_wireframe = True
        check(helper.update_deform_wireframe(force=True), "preview evaluator did not run")
    finally:
        stages_module.hide_runtime_object = original_stage_hide
        utils_module.hide_runtime_object = original_preview_hide
    check(stage_visibility and all(stage_visibility),
          "a stage evaluator was visible in the viewport")
    check(preview_visibility and all(preview_visibility),
          "a preview evaluator was visible in the viewport")
    return len(stage_visibility), len(preview_visibility)


case("runtime_evaluators_are_hidden", runtime_evaluators_are_hidden)


def cage_overlay_depth_contract():
    preference = helper.pref
    original_in_front = bool(preference.show_wireframe_in_front)
    original_gpu = viewport_module.gpu
    original_utils_gpu = utils_module.gpu
    depth_modes = []
    draw_calls = []

    class FakeGizmo:
        def draw_custom_shape(self, *args, **kwargs):
            draw_calls.append((args, kwargs))

    viewport_module.gpu = SimpleNamespace(
        state=SimpleNamespace(depth_test_set=depth_modes.append))
    try:
        property_definition = (
            preferences_module.SimpleDeformGizmoAddonPreferences.bl_rna
            .properties["show_wireframe_in_front"])
        check(bool(property_definition.default),
              "In Front is not enabled by default")

        preference.show_wireframe_in_front = False
        check(viewport_module.cage_overlay_depth_test() == "LESS_EQUAL",
              "cage preview ignored object occlusion")
        viewport_module.draw_cage_custom_shape(
            FakeGizmo(), "shape", matrix="matrix", select_id=7)
        check(depth_modes == ["LESS_EQUAL", "NONE"],
              "occluded cage preview did not restore GPU depth state")
        check(draw_calls == [(("shape",), {
            "matrix": "matrix", "select_id": 7})],
              "cage preview draw arguments changed")

        depth_modes.clear()
        draw_calls.clear()
        check(viewport_module.gizmo_depth_test() == "ALWAYS",
              "interactive controls are not configured in front")
        viewport_module.draw_gizmo_custom_shape(
            FakeGizmo(), "shape", matrix="matrix", select_id=11)
        check(depth_modes == ["ALWAYS", "NONE"],
              "interactive control was occluded with In Front disabled")
        check(draw_calls == [(("shape",), {
            "matrix": "matrix", "select_id": 11})],
              "interactive Gizmo draw arguments changed")

        depth_modes.clear()
        draw_calls.clear()
        utils_module.gpu = SimpleNamespace(
            state=SimpleNamespace(depth_test_set=depth_modes.append))
        legacy_gizmo = SimpleNamespace(
            draw_custom_shape=lambda *args, **kwargs:
            draw_calls.append((args, kwargs)))
        utils_module.GizmoUtils.draw_interactive_custom_shape(
            legacy_gizmo, "legacy", select_id=13)
        check(depth_modes == ["ALWAYS", "NONE"],
              "traditional interactive control was occluded")
        check(draw_calls == [(("legacy",), {"select_id": 13})],
              "traditional Gizmo draw arguments changed")

        depth_modes.clear()
        preference.show_wireframe_in_front = True
        check(viewport_module.cage_overlay_depth_test() == "ALWAYS",
              "In Front did not restore the always-visible cage overlay")
        viewport_module.draw_cage_custom_shape(FakeGizmo(), "shape")
        check(depth_modes == ["ALWAYS", "NONE"],
              "front cage preview did not restore GPU depth state")
    finally:
        viewport_module.gpu = original_gpu
        utils_module.gpu = original_utils_gpu
        preference.show_wireframe_in_front = original_in_front
    return "preview follows In Front; interactive controls always stay in front"


case("cage_overlay_depth_contract", cage_overlay_depth_contract)


def stage_selection_and_reorder():
    obj.modifiers.active = first
    check(bpy.ops.simple_deform_gizmo.stage_cycle(index=1) == {"FINISHED"},
          "direct stage selection failed")
    check(obj.modifiers.active == second, "direct stage selected the wrong modifier")
    check(bpy.ops.simple_deform_gizmo.stage_cycle(direction="PREVIOUS") == {"FINISHED"},
          "previous stage failed")
    check(obj.modifiers.active == first, "previous stage selected the wrong modifier")
    bpy.ops.object.modifier_move_to_index(modifier=second.name, index=1)
    StageCache.rebuild(bpy.context, obj)
    check([stage.modifier_pointer for stage in StageCache.stages_for(obj)] ==
          [int(first.as_pointer()), int(second.as_pointer())],
          "RNA stage identity did not survive reorder")
    bpy.ops.object.modifier_move_to_index(modifier=second.name, index=2)
    return "direct, cycle, and reorder"


case("stage_selection_and_reorder", stage_selection_and_reorder)


def multi_stage_ui_with_external_origin():
    class Layout:
        enabled = True

        def row(self, **_kwargs):
            return self

        def operator(self, *_args, **_kwargs):
            return SimpleNamespace()

        def label(self, **_kwargs):
            return None

        def prop(self, *_args, **_kwargs):
            return None

    origin = bpy.data.objects.new("SDH External UI Origin", None)
    bpy.context.collection.objects.link(origin)
    obj.modifiers.active = first
    first.origin = origin
    context = SimpleNamespace(
        object=obj,
        space_data=SimpleNamespace(type="VIEW_3D", show_gizmo=True),
    )
    try:
        header_module.SimpleDeformHelperToolHeader.draw_property(Layout(), context)
    finally:
        first.origin = None
        bpy.data.objects.remove(origin, do_unlink=True)
    return "multi-stage controls and external Origin"


case("multi_stage_ui_with_external_origin", multi_stage_ui_with_external_origin)


def traditional_header_controls():
    class Layout:
        def __init__(self):
            self.properties = []

        def row(self, **_kwargs):
            return self

        def separator(self, **_kwargs):
            return None

        def prop(self, _data, property_name, **_kwargs):
            self.properties.append(property_name)

    obj.modifiers.active = first
    context = SimpleNamespace(
        object=obj,
        space_data=SimpleNamespace(type="VIEW_3D", show_gizmo=True),
    )
    menu = SimpleNamespace(layout=Layout())
    preferences_module.SimpleDeformGizmoAddonPreferences.draw_header_tool_settings(
        menu, context)
    check(menu.layout.properties[:3] == [
        "deform_method", "deform_axis", "angle"],
          f"traditional header controls changed: {menu.layout.properties!r}")
    return menu.layout.properties


case("traditional_header_controls", traditional_header_controls)


def rotated_managed_origin_bounds():
    bpy.ops.mesh.primitive_cube_add()
    rotated_target = bpy.context.object
    rotated_target.name = "Rotated Origin Bounds Target"
    rotated_target.scale = (1.0, 2.0, 3.0)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    rotated_modifier = rotated_target.modifiers.new(
        "Rotated Origin Bend", "SIMPLE_DEFORM")
    rotated_modifier.deform_method = "BEND"
    rotated_modifier.deform_axis = "Z"
    rotated_target.modifiers.active = rotated_modifier
    rotated_target.SimpleDeformGizmo_PropertyGroup.origin_mode = "DOWN_LIMITS"
    helper.clear_point_cache()
    origin = helper.new_origin_empty_object(force_managed=True)
    check(origin is not None, "managed Origin was not created")
    origin.SimpleDeformGizmo_PropertyGroup.origin_mode = "DOWN_LIMITS"
    try:
        for degrees in (0.0, 1.0, 45.0, 90.0, 135.0):
            origin.simple_deform_helper_rotate_angle = math.radians(degrees)
            bpy.context.view_layer.update()
            helper.clear_point_cache()
            check(
                helper.modifier_origin_is_available,
                f"managed Origin bounds failed at {degrees} degrees",
            )
            up, down, upper_limit, lower_limit = helper.modifier_limits_point
            check((up - down).length > 1.0e-6,
                  f"managed Origin axis collapsed at {degrees} degrees")
            check((upper_limit - lower_limit).length > 1.0e-6,
                  f"managed Origin limits collapsed at {degrees} degrees")
            check(len(helper.modifier_limits_bound_box) == 8,
                  f"managed Origin box is incomplete at {degrees} degrees")
    finally:
        rotated_modifier.origin = None
        rotated_target.SimpleDeformGizmo_PropertyGroup.origin_mode = "NOT"
        bpy.data.objects.remove(origin, do_unlink=True)
        bpy.data.objects.remove(rotated_target, do_unlink=True)
        activate(obj)
        obj.modifiers.active = first
        helper.clear_point_cache()
    return "arbitrary-angle managed Origin bounds"


case("rotated_managed_origin_bounds", rotated_managed_origin_bounds)


def strength_binding():
    class Target:
        value = None

        def target_set_prop(self, identifier, modifier, property_name):
            self.value = identifier, modifier, property_name

    class Group:
        angle = Target()

    group = Group()
    obj.modifiers.active = first
    first.deform_method = "TAPER"
    angle_module.AngleGizmoGroup.refresh(group, bpy.context)
    check(group.angle.value == ("value", first, "factor"),
          "Taper was not bound to factor")
    first.deform_method = "BEND"
    angle_module.AngleGizmoGroup.refresh(group, bpy.context)
    check(group.angle.value == ("value", first, "angle"),
          "Bend was not bound to angle")
    return "Taper=factor, Bend=angle"


case("strength_binding", strength_binding)


def user_origin_is_read_only():
    origin = bpy.data.objects.new("User Origin", None)
    bpy.context.collection.objects.link(origin)
    origin.location = (2.0, 3.0, 4.0)
    origin.rotation_euler = (0.2, 0.3, 0.4)
    origin.scale = (2.0, 2.5, 3.0)
    # A copied or user-authored custom property is not sufficient ownership.
    origin[PublicData.G_OWNER_PROP] = True
    origin[PublicData.G_OWNER_UUID_PROP] = "not-the-active-object-owner"
    for constraint_type in ("COPY_LOCATION", "COPY_SCALE", "LIMIT_LOCATION"):
        origin.constraints.new(constraint_type)
    first.origin = origin
    before = (
        tuple(origin.location), tuple(origin.rotation_euler), tuple(origin.scale),
        tuple(constraint.type for constraint in origin.constraints), origin.parent,
    )
    check(helper.new_origin_empty_object(force_managed=True) is None,
          "a user Origin was treated as managed")
    helper.fix_origin_parent_and_angle()
    helper.update_object_origin_matrix()
    after = (
        tuple(origin.location), tuple(origin.rotation_euler), tuple(origin.scale),
        tuple(constraint.type for constraint in origin.constraints), origin.parent,
    )
    check(before == after, "a user Origin was changed")
    first.origin = None
    return "preserved"


case("user_origin_is_read_only", user_origin_is_read_only)


def managed_origin_lifecycle():
    obj.SimpleDeformGizmo_PropertyGroup.origin_mode = "LIMITS_MIDDLE"
    origin = helper.new_origin_empty_object(force_managed=True)
    check(origin and origin.get(PublicData.G_OWNER_PROP, False), "owner marker missing")
    check(origin.get(PublicData.G_OWNER_UUID_PROP) ==
          obj.get(PublicData.G_OBJECT_UUID_PROP), "owner UUID does not match")
    check(origin.parent == obj, "managed Origin was not parented")
    check(origin.hide_get() and origin.hide_select,
          "managed Origin was not hidden")
    check(any(
        collection.get(utils_module.CONTROL_COLLECTION_MARKER, False)
        for collection in origin.users_collection
    ), "managed Origin was not consolidated into the helper collection")
    check(PublicData.G_NAME_CON_LIMIT in origin.constraints, "limit constraint missing")
    check(PublicData.G_NAME_CON_COPY_ROTATION in origin.constraints,
          "copy-rotation constraint missing")
    name = origin.name
    origin.SimpleDeformGizmo_PropertyGroup.origin_mode = "NOT"
    check(bpy.data.objects.get(name) is None, "managed Origin was not removed")
    check(first.origin is None, "modifier kept the removed Origin")
    check(not any(
        collection.get(utils_module.CONTROL_COLLECTION_MARKER, False)
        for collection in bpy.data.collections
    ), "empty helper collection survived managed Origin removal")
    return name


case("managed_origin_lifecycle", managed_origin_lifecycle)


def geometry_edge_cases():
    curve = bpy.data.curves.new("SDH NURBS", "CURVE")
    spline = curve.splines.new("NURBS")
    spline.points.add(2)
    spline.points[0].co = (0.0, 0.0, 0.0, 1.0)
    spline.points[1].co = (1.0, 2.0, 3.0, 1.0)
    spline.points[2].co = (-1.0, 4.0, 2.0, 1.0)
    curve_obj = bpy.data.objects.new("SDH NURBS", curve)
    bpy.context.collection.objects.link(curve_obj)
    curve_bounds = rounded_bounds(helper.get_mesh_max_min_co(curve_obj))
    empty_mesh = bpy.data.meshes.new("SDH Empty")
    empty_obj = bpy.data.objects.new("SDH Empty", empty_mesh)
    bpy.context.collection.objects.link(empty_obj)
    empty_bounds = rounded_bounds(helper.get_mesh_max_min_co(empty_obj))
    check(curve_bounds == ((-1.0, 0.0, 0.0), (1.0, 4.0, 3.0)),
          f"NURBS bounds are wrong: {curve_bounds}")
    check(empty_bounds == ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
          f"empty geometry bounds are wrong: {empty_bounds}")
    return curve_bounds, empty_bounds


case("geometry_edge_cases", geometry_edge_cases)


def transient_preview():
    activate(obj)
    obj.modifiers.active = first
    helper.pref.update_deform_wireframe = True
    objects_before = {item.as_pointer() for item in bpy.data.objects}
    meshes_before = {item.as_pointer() for item in bpy.data.meshes}
    check(helper.update_deform_wireframe(force=True), "preview update failed")
    check(objects_before == {item.as_pointer() for item in bpy.data.objects},
          "preview object leaked")
    check(meshes_before == {item.as_pointer() for item in bpy.data.meshes},
          "preview mesh leaked")
    data = PublicData.G_DeformDrawData.get("simple_deform_bound_data")
    check(data and len(data["positions"]), "preview draw data is empty")
    return len(data["positions"]), len(data["indices"])


case("transient_preview", transient_preview)


def throttled_preview_stays_visible():
    activate(obj)
    obj.modifiers.active = first
    helper.pref.update_deform_wireframe = True
    check(helper.update_deform_wireframe(force=True), "initial preview failed")
    data = PublicData.G_DeformDrawData["simple_deform_bound_data"]
    old_signature = data["signature"]
    old_angle = first.angle
    try:
        first.angle = old_angle + math.radians(1.0)
        PublicData.G_PREVIEW_LAST_UPDATE = monotonic()
        check(not helper.update_deform_wireframe(), "preview throttle did not engage")
        check(data["signature"] == old_signature, "last complete frame was replaced")
        check(data["signature"] != helper.preview_signature(),
              "test did not create a newer parameter state")
        check(helper.preview_data_matches_context(data),
              "last complete frame would blink off while throttled")
    finally:
        first.angle = old_angle
        helper.update_deform_wireframe(force=True)
    return "last complete frame retained"


case("throttled_preview_stays_visible", throttled_preview_stays_visible)


def render_with_preview_enabled():
    activate(obj)
    obj.modifiers.active = first
    camera_data = bpy.data.cameras.new("SDH Render Camera")
    camera = bpy.data.objects.new("SDH Render Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (8.0, -8.0, 5.0)
    camera.rotation_euler = (
        obj.location - camera.location
    ).to_track_quat("-Z", "Y").to_euler()
    scene = bpy.context.scene
    scene.camera = camera
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 32
    scene.render.resolution_y = 32
    scene.render.resolution_percentage = 100
    bpy.ops.render.render()
    check(not any(item.name.startswith("SDH_Preview") for item in bpy.data.objects),
          "preview object appeared during render")
    return scene.render.engine


case("render_with_preview_enabled", render_with_preview_enabled)


def scoped_keyframes():
    activate(obj)
    obj.modifiers.active = first
    check(bpy.ops.simple_deform_gizmo.key_frame() == {"FINISHED"},
          "keyframe operator failed")
    action = obj.animation_data.action if obj.animation_data else None
    check(action is not None, "no action was created")
    paths = set()
    if hasattr(action, "fcurves"):
        paths.update(curve.data_path for curve in action.fcurves)
    else:
        for layer in action.layers:
            for strip in layer.strips:
                for channelbag in strip.channelbags:
                    paths.update(curve.data_path for curve in channelbag.fcurves)
    check(any(path.endswith(".angle") for path in paths), "strength key is missing")
    check(any(path.endswith(".limits") for path in paths), "limits keys are missing")
    check(not any(token in path for token in ("deform_method", "deform_axis", "vertex_group")
                  for path in paths), "configuration property was keyed")
    check(bpy.ops.simple_deform_gizmo.key_remove_frame() == {"FINISHED"},
          "key removal failed")
    return sorted(paths)


case("scoped_keyframes", scoped_keyframes)


def no_object_callback():
    activate(obj)
    obj.modifiers.active = first
    bpy.context.view_layer.objects.active = None
    obj.select_set(False)
    msgbus_module.modify_deform_method()
    return "ignored safely"


case("no_object_callback", no_object_callback)


def clean_lifecycle():
    addon.unregister()
    check(not hasattr(bpy.types.Object, "sdh_cage_deform"),
          "cage properties survived unregister")
    check(not any(item.get(stages_module.RUNTIME_STAGE_OBJECT, False)
                  for item in bpy.data.objects), "stage object survived unregister")
    addon.register()
    check(hasattr(bpy.types.Object, "sdh_cage_deform"),
          "cage properties missing after re-register")
    addon.unregister()
    check(not hasattr(bpy.types.Object, "sdh_cage_deform"),
          "cage properties survived second unregister")
    return "register/unregister/register/unregister"


case("clean_lifecycle", clean_lifecycle)
bpy.context.preferences.addons.remove(addon_entry)

if failures:
    print(f"SDH::SUMMARY::FAIL::{failures!r}")
    raise SystemExit(1)
print("SDH::SUMMARY::PASS")
