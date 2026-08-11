"""Geometry Nodes and controller regressions for Cage Deform."""

import importlib
import math
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Euler, Matrix, Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))
failures = []


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def close_vector(actual, expected, tolerance=2.0e-4):
    return (Vector(actual) - Vector(expected)).length <= tolerance


def case(name, function):
    try:
        result = function()
    except Exception as exc:
        failures.append((name, type(exc).__name__, str(exc)))
        print(f"SDH_CAGE::{name}::FAIL::{type(exc).__name__}::{exc}")
        traceback.print_exc()
    else:
        print(f"SDH_CAGE::{name}::PASS::{result!r}")


def evaluated_points(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
core = importlib.import_module(f"{PACKAGE}.cage_deform.core")


def packaged_node_group_contract():
    loaded = ()
    with bpy.data.libraries.load(
            str(core.GROUP_LIBRARY_PATH), link=False) as (source, destination):
        check(core.GROUP_NAME in source.node_groups,
              "packaged node template is missing")
        destination.node_groups = [core.GROUP_NAME]
        loaded = destination.node_groups
    group = next((item for item in loaded if item is not None), None)
    check(group is not None, "packaged node template did not load")
    try:
        check(
            int(group.get(core.GROUP_MARKER, 0)) == core.GROUP_VERSION,
            "packaged node template schema is stale",
        )
        check(len(group.nodes) >= 110, "packaged deformation graph is incomplete")
        return (int(group.get(core.GROUP_MARKER, 0)), len(group.nodes))
    finally:
        if group.users == 0:
            bpy.data.node_groups.remove(group)


case("packaged_node_group_contract", packaged_node_group_contract)

vertices = (
    (-0.25, -2.0, 0.0),
    (0.0, -1.0, 0.0),
    (0.25, 0.0, 0.0),
    (0.0, 1.0, 0.0),
    (-0.25, 2.0, 0.0),
    (1.5, 0.0, 0.0),
)
mesh = bpy.data.meshes.new("Cage Deform Regression")
mesh.from_pydata(vertices, (), ())
obj = bpy.data.objects.new("Cage Deform Regression", mesh)
bpy.context.collection.objects.link(obj)
obj.select_set(True)
bpy.context.view_layer.objects.active = obj

modifier, controller, _previous = deform.create_deform_stage(bpy.context, obj)
properties = controller.sdh_cage_deform
properties.size = (2.0, 2.0, 2.0)
properties.strength = math.radians(90.0)
properties.direction = 0.0
properties.mode = "LIMITED"
properties.origin = "BOTTOM"
controller.location = (0.0, 0.0, 0.0)
controller.rotation_euler = (0.0, 0.0, 0.0)
deform.sync_controller(controller, pull_transform=False)
stage_state = {}


def node_group_contract():
    group = modifier.node_group
    check(group.get(deform.GROUP_MARKER) == deform.GROUP_VERSION, "group version marker missing")
    check(len(group.nodes) >= 110, "deformation graph is incomplete")
    check(deform.is_cage_modifier(modifier), "modifier marker missing")
    check(deform.find_controller(obj, modifier) == controller, "controller ownership failed")
    check(not any(item.get(deform.RUNTIME_EVALUATOR, False) for item in bpy.data.objects),
          "fit evaluator leaked")
    return len(group.nodes)


case("node_group_contract", node_group_contract)


def hidden_helper_collection_and_controller_styles():
    utils = importlib.import_module(f"{PACKAGE}.utils")

    collections = tuple(
        collection for collection in bpy.data.collections
        if collection.get(utils.CONTROL_COLLECTION_MARKER, False)
    )
    check(len(collections) == 1, "managed helper collection was not created")
    helper_collection = collections[0]
    check(tuple(controller.users_collection) == (helper_collection,),
          "controller was not consolidated into the helper collection")
    # Empty objects stay hidden until a target is selected; selected cage
    # controllers are revealed so Blender's Timeline can show their keys.
    check(controller.hide_get() and controller.hide_select,
          "managed controller Empty is visible or directly selectable")
    check(not properties.show_axis_gizmo and not properties.show_direction_handle,
          "optional direction controls are visible before the user requests them")

    expected_styles = {
        deform_type: style[0]
        for deform_type, style in deform.CONTROLLER_STYLES.items()
    }
    for deform_type, display_type in expected_styles.items():
        if deform_type in {"SHEAR", "FFD", "CURVE"}:
            properties.cage_type = deform_type
        else:
            properties.cage_type = "STANDARD"
            deform.core.set_deform_layers(
                properties, (deform_type,), bpy.context)
        deform.sync_controller(controller, pull_transform=False)
        check(controller.empty_display_type == display_type,
              f"{deform_type} controller style was not applied")

    properties.cage_type = "STANDARD"
    deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
    check(bpy.ops.sdh.select_cage_controller() == {"FINISHED"},
          "controller edit selection failed")
    check(bpy.context.object == controller and not controller.hide_get(),
          "controller was not revealed for editing")
    check(bpy.ops.sdh.select_cage_target() == {"FINISHED"},
          "return-to-object failed")
    check(bpy.context.object == obj and controller.select_get() and
          not controller.hide_get(),
          "return-to-object did not sync the managed controller selection")
    check(not controller.show_name,
          "managed controller name is visible in the viewport")
    check(bpy.ops.sdh.select_cage_stage(index=0) == {"FINISHED"},
          "cage-stage selection failed")
    check(bpy.context.object == obj and controller.select_get() and
          not controller.hide_get(),
          "cage-stage selection lost the managed controller selection")
    return expected_styles


case("hidden_helper_collection_and_controller_styles",
     hidden_helper_collection_and_controller_styles)


def legacy_controller_selection_fallback():
    """An old generated Empty still follows target selection and timeline."""
    core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
    original_name = controller.name
    original_values = {
        key: controller.get(key)
        for key in (
            deform.CONTROLLER_MARKER,
            deform.CONTROLLER_UUID,
            deform.TARGET_UUID,
            deform.MODIFIER_UUID,
        )
        if key in controller
    }
    try:
        controller.name = "Cage Deform Controller"
        for key in (
                deform.CONTROLLER_MARKER,
                deform.CONTROLLER_UUID,
                deform.TARGET_UUID,
                deform.MODIFIER_UUID):
            if key in controller:
                del controller[key]
        activate(obj)
        check(deform.find_controller(obj, modifier) == controller,
              "legacy named Empty was not matched to its stage")
        core._SELECTION_SYNC_SIGNATURE = None
        core._selection_sync_notify()
        check(core._selection_watch_timer() == core._SELECTION_WATCH_INTERVAL,
              "selection fallback watcher did not remain active")
        # A previous stage click can leave one deferred selection-repair pass.
        # Drain it before checking the ordinary target-to-controller watcher.
        core._selection_sync_timer()
        core._selection_sync_timer()
        check(deform.is_cage_controller(controller),
              "legacy controller markers were not repaired")
        check(controller.select_get(),
              "target selection did not include the legacy controller")
        check(bpy.context.view_layer.objects.active == obj,
              "target selection lost the active object")
        return controller.name
    finally:
        controller.name = original_name
        for key in (
                deform.CONTROLLER_MARKER,
                deform.CONTROLLER_UUID,
                deform.TARGET_UUID,
                deform.MODIFIER_UUID):
            if key in controller:
                del controller[key]
        for key, value in original_values.items():
            controller[key] = value
        activate(obj)
        core.refresh_controller_display(bpy.context, force=True)


case("legacy_controller_selection_fallback",
     legacy_controller_selection_fallback)


def type_specific_gizmo_contract():
    gizmos = deform.gizmos
    gizmo_ids = {
        gizmos.SDHCageBendStrengthGizmo.bl_idname,
        gizmos.SDHCageTwistStrengthGizmo.bl_idname,
        gizmos.SDHCageTaperFactorGizmo.bl_idname,
        gizmos.SDHCageStretchFactorGizmo.bl_idname,
        gizmos.SDHCageShearGizmo.bl_idname,
        gizmos.SDHCageFFDCornerGizmo.bl_idname,
    }
    check(len(gizmo_ids) == 6,
          "deformation layers do not have distinct gizmo types")
    check(set(deform.AXIS_VECTORS) == {
        "POS_X", "NEG_X", "POS_Y", "NEG_Y", "POS_Z", "NEG_Z"},
        "axis-switch gizmo does not expose all signed axes")
    check(set(deform.BEND_TREND_BASES) == set(deform.AXIS_VECTORS),
          "bend-trend palette does not cover all six cage faces")
    for alignment in deform.BEND_TREND_BASES:
        for variant in (0, 1):
            matrix, scale, _bounds = deform.bend_trend_handle_matrix(
                obj, alignment, variant)
            check(all(math.isfinite(value) for row in matrix for value in row),
                  f"{alignment}/{variant} bend-trend matrix is invalid")
            check(scale >= 0.12,
                  f"{alignment}/{variant} bend-trend handle is too small")
    return sorted(gizmo_ids)


case("type_specific_gizmo_contract", type_specific_gizmo_contract)


def compact_stage_picker_contract():
    gizmos = deform.gizmos
    properties.cage_type = "STANDARD"
    deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
    properties.size = (3.0, 6.0, 2.0)
    properties.origin = "BOTTOM"
    properties.bend_strength = math.radians(70.0)
    properties.bend_direction = math.radians(25.0)
    preview_state = gizmos.cage_preview_geometry_state(properties)
    full = gizmos.cage_preview_wire_vertices(
        properties, steps=12, ring_positions=(0.0, 0.5, 1.0),
        preview_state=preview_state)
    compact = gizmos.cage_picker_wire_vertices(
        properties, steps=12, preview_state=preview_state)
    center = Vector(deform.deform_point_from_properties(
        (0.0, 0.0, 0.0), properties, chain_preview=True,
        preview_output_frame=preview_state[1]))
    check(len(compact) == len(full),
          "compact stage picker no longer matches its visible wire topology")
    full_radius = max((Vector(vertex) - center).length for vertex in full)
    compact_radius = max((Vector(vertex) - center).length for vertex in compact)
    expected_radius = full_radius * gizmos.CAGE_STAGE_PICKER_SCALE
    check(abs(compact_radius - expected_radius) <= 1.0e-5,
          "stage picker drawing and hit geometry are not compact")
    check(compact_radius < full_radius * 0.35,
          "stage picker covers too much of the inactive cage")
    return round(compact_radius / full_radius, 3)


case("compact_stage_picker_contract", compact_stage_picker_contract)


def shear_and_ffd_contract():
    properties.mode = "LIMITED"
    properties.origin = "BOTTOM"
    properties.size = (2.0, 2.0, 2.0)
    properties.top_scale = (1.0, 1.0)
    properties.bottom_scale = (1.0, 1.0)
    properties.top_offset = (0.0, 0.0)
    properties.bottom_offset = (0.0, 0.0)

    properties.cage_type = "SHEAR"
    properties.shear_factors = (0.35, -0.2)
    deform.sync_controller(controller, pull_transform=False)
    actual_shear = evaluated_points(obj)
    expected_shear = tuple(
        deform.deform_point_from_properties(point, properties)
        for point in vertices)
    check(all(close_vector(a, e) for a, e in zip(actual_shear, expected_shear)),
          "Geometry Nodes Shear differs from the reference evaluator")

    properties.cage_type = "FFD"
    deform.sync_controller(controller, pull_transform=False)
    before_ffd = evaluated_points(obj)
    properties.ffd_points[5].offset = (0.4, 0.25, -0.3)
    deform.sync_controller(controller, pull_transform=False)
    actual_ffd = evaluated_points(obj)
    check(any(not close_vector(a, b) for a, b in zip(actual_ffd, before_ffd)),
          "Dedicated FFD point did not deform evaluated geometry")
    check(bpy.ops.sdh.reset_cage_ffd() == {"FINISHED"},
          "FFD reset operator failed")
    check(all(
        all(abs(value) <= 1.0e-8 for value in point.offset)
        for point in properties.ffd_points),
        "FFD reset left non-zero control-point offsets")

    properties.cage_type = "STANDARD"
    deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
    properties.bend_strength = math.radians(90.0)
    properties.strength = properties.bend_strength
    deform.sync_controller(controller, pull_transform=False)
    return {
        "shear": tuple(round(value, 4) for value in actual_shear[2]),
        "ffd": tuple(round(value, 4) for value in actual_ffd[2]),
    }


case("shear_and_ffd_contract", shear_and_ffd_contract)


def parameter_gizmo_orientation_contract():
    gizmos = deform.gizmos
    cage_matrix = Matrix.Identity(4)
    ring = gizmos._twist_ring_matrix(cage_matrix, Vector((0.0, 0.0, 0.0)), 0.0)
    # The ring normal is cage +Y, so its plane is parallel to the cage end face.
    ring_normal = Vector(ring.to_3x3().col[2]).normalized()
    check(close_vector(ring_normal, (0.0, 1.0, 0.0)),
          f"twist ring is not parallel to cage end face: {ring_normal}")
    rotated_cage = Matrix.Rotation(math.radians(37.0), 4, "Z")
    rotated_ring = gizmos._twist_ring_matrix(
        rotated_cage, Vector((1.0, 2.0, 3.0)), 0.0)
    expected_normal = (rotated_cage.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
    actual_normal = Vector(rotated_ring.to_3x3().col[2]).normalized()
    check(close_vector(actual_normal, expected_normal),
          "twist ring lost the rotated cage end-face normal")
    check(abs(gizmos.STRENGTH_ARROW_SCALE - 0.30) <= 1.0e-8,
          "shared fixed-size parameter handle scale regressed")

    properties.cage_type = "SHEAR"
    properties.origin = "CENTER"
    properties.size = (2.0, 4.0, 2.0)
    properties.shear_factors = (0.35, -0.2)
    deform.sync_controller(controller, pull_transform=False)
    shear_frame, shear_radius = gizmos.shear_handle_frame(obj, controller)
    local_anchor = (
        deform.cage_local_matrix(obj, controller).inverted_safe() @
        shear_frame.translation)
    expected_anchor = deform.deform_point_from_properties(
        (0.0, 2.0, 0.0), properties, chain_preview=True)
    check(close_vector(local_anchor, expected_anchor),
          "center-origin Shear handle is not on the displaced free end")
    check(gizmos.shear_handle_local_y(properties) == 2.0,
          "center-origin Shear handle remained at the zero-influence center")
    shear_normal = Vector(shear_frame.to_3x3().col[2]).normalized()
    expected_shear_normal = (
        deform.cage_local_matrix(obj, controller).to_3x3() @
        Vector((0.0, 1.0, 0.0))).normalized()
    check(abs(shear_normal.dot(expected_shear_normal)) >= 1.0 - 2.0e-4,
          "Shear handle is not parallel to the evaluated end face")
    check(shear_radius >= 0.99,
          "Shear handle scale no longer follows the cage cross-section")
    shear_shape = gizmos._shape_vertices("SHEAR")
    check(max(abs(vertex[0]) for vertex in shear_shape) >= 1.0 and
          max(abs(vertex[1]) for vertex in shear_shape) >= 1.0,
          "Shear handle no longer exposes both planar drag axes")
    check(gizmos.shear_drag_axis_from_screen(
        (50.0, 50.0), (50.0, 50.0), (100.0, 50.0), (50.0, 100.0)) == "FREE",
        "Shear center grip no longer selects free planar drag")
    check(gizmos.shear_drag_axis_from_screen(
        (90.0, 51.0), (50.0, 50.0), (100.0, 50.0), (50.0, 100.0)) == "X",
        "Shear X arm does not select cage X")
    check(gizmos.shear_drag_axis_from_screen(
        (49.0, 90.0), (50.0, 50.0), (100.0, 50.0), (50.0, 100.0)) == "Z",
        "Shear Z arm does not select cage Z")
    x_delta = gizmos.constrain_shear_delta((0.4, 0.0, -0.7), axis="X")
    z_delta = gizmos.constrain_shear_delta((0.4, 0.0, -0.7), axis="Z")
    check(abs(x_delta.z) <= 1.0e-8 and abs(z_delta.x) <= 1.0e-8,
          "Shear axis-arm drag is not constrained to its selected axis")

    properties.cage_type = "STANDARD"
    deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
    properties.origin = "BOTTOM"
    properties.size = (2.0, 2.0, 2.0)
    deform.sync_controller(controller, pull_transform=False)
    return {
        "twist_normal": tuple(round(value, 4) for value in actual_normal),
        "shear_radius": round(shear_radius, 4),
    }


case("parameter_gizmo_orientation_contract", parameter_gizmo_orientation_contract)


def bend_drag_sign_contract():
    # The straight-line BEND mapping is authored as ``delta = -progress``.
    # Keep this contract close to the implementation so a future refactor does
    # not make normal and Alt direction drags disagree again.
    source = Path(deform.gizmos.__file__).read_text(encoding="utf-8")
    marker = "# Both normal bend-angle dragging and Alt direction dragging"
    check(marker in source, "bend drag sign contract marker is missing")
    check(source.count("delta = -delta") >= 1,
          "bend drag does not invert screen progress")
    return "normal and Alt bend drags share the negative screen-progress sign"


case("bend_drag_sign_contract", bend_drag_sign_contract)


def bend_trend_choice_contract():
    original = {
        "alignment": properties.alignment,
        "direction": properties.direction,
        "size": tuple(properties.size),
        "location": tuple(controller.location),
        "rotation": tuple(controller.rotation_euler),
        "scale": tuple(controller.scale),
    }
    try:
        properties.deform_type = "BEND"
        properties.show_axis_gizmo = True
        expected_alignment, expected_direction = deform.gizmos.bend_trend_target(
            "NEG_Z", 1, controller=controller)
        result = bpy.ops.sdh.set_bend_trend(
            alignment="NEG_Z", variant=1)
        check(result == {"FINISHED"}, "bend-trend choice operator failed")
        check(properties.alignment == expected_alignment,
              "bend-trend choice did not change the signed axis")
        check(abs(properties.bend_direction - expected_direction) < 1.0e-5,
              "bend-trend choice did not change the perpendicular trend")
        check(not properties.show_axis_gizmo,
              "bend-trend choices did not auto-hide after selection")

        properties.show_axis_gizmo = True
        expected_alignment, expected_direction = deform.gizmos.bend_trend_target(
            "POS_Y", 0, controller=controller)
        result = bpy.ops.sdh.set_bend_trend(
            alignment="POS_Y", variant=0, keep_open=True)
        check(result == {"FINISHED"}, "persistent bend-trend choice failed")
        check(properties.alignment == expected_alignment and
              abs(properties.bend_direction - expected_direction) < 1.0e-5,
              "persistent bend-trend choice selected the wrong frame")
        check(properties.show_axis_gizmo,
              "Ctrl-style persistent bend-trend choice did not stay visible")
        return (properties.alignment, properties.direction)
    finally:
        properties.alignment = original["alignment"]
        properties.direction = original["direction"]
        properties.size = original["size"]
        properties.show_axis_gizmo = False
        controller.location = original["location"]
        controller.rotation_euler = original["rotation"]
        controller.scale = original["scale"]
        deform.sync_controller(controller, pull_transform=False)


case("bend_trend_choice_contract", bend_trend_choice_contract)


def simplified_chinese_translations():
    preferences = bpy.context.preferences.view
    previous_language = preferences.language
    previous_interface = preferences.use_translate_interface
    try:
        preferences.language = "zh_HANS"
        preferences.use_translate_interface = True
        expected = {
            "Simple Deformer": "简易变形器",
            "Cage Deform": "笼式形变",
            "Deformation Type": "形变类型",
            "Twist": "扭曲",
            "Cage Controls": "笼控制",
            "Align & Fit": "对齐并适配",
            "Preserve Volume": "维持体积",
            "Independent Ends": "独立端部",
            "Top Scale": "顶部缩放",
            "Show Shape Handles": "显示端面塑形手柄",
            "Show Length Handles": "显示长度手柄",
            "Limit to Object Bounds": "限制在物体边界内",
            "Length handles stop at the object bounds":
                "长度手柄不会越过物体边界",
            "Show Axis Switch": "显示轴向切换",
            "Show Twist": "显示扭转",
            "Bend Trend": "弯曲趋势",
            "Fine Direction": "精细方向",
            "Remove Stage": "删除阶段",
            "Remove Cage Stack": "删除笼式堆栈",
            "Purple twist ring: drag around its center":
                "紫色扭转环：围绕中心拖动",
            "Large purple twist ring: drag around its center":
                "大型紫色扭转环：围绕中心拖动",
            "Red / green arrows: horizontal / vertical bend trend":
                "红色 / 绿色箭头：横向 / 竖向弯曲趋势",
            "Click to choose and close • Ctrl keeps choices open":
                "点击选择并收起 • 按住 Ctrl 保持选项显示",
            "Axis switch: RGB is X/Y/Z; diamond is +, ring is -":
                "轴向切换：RGB 对应 X/Y/Z；菱形为正向，圆环为负向",
            "Cyan top / green bottom: drag one end only":
                "青色顶部 / 绿色底部：仅拖动一个端部",
            "Yellow top / amber bottom: move one boundary":
                "黄色顶部 / 琥珀色底部：仅移动一个边界",
        }
        actual = {
            source: bpy.app.translations.pgettext_iface(source)
            for source in expected
        }
        visible_sources = (
            "Simple Deformer", "Cage Deform", "Deformation Type", "Twist",
            "Cage Controls", "Align & Fit", "Preserve Volume",
            "Independent Ends", "Top Scale", "Show Shape Handles",
            "Show Length Handles", "Limit to Object Bounds",
            "Show Axis Switch", "Show Twist", "Bend Trend",
            "Remove Stage", "Remove Cage Stack",
        )
        untranslated = tuple(
            source for source in visible_sources if actual[source] == source)
        check(not untranslated,
              f"visible Chinese labels are untranslated: {untranslated!r}")
        return actual
    finally:
        preferences.language = previous_language
        preferences.use_translate_interface = previous_interface


case("simplified_chinese_translations", simplified_chinese_translations)


def compare_mode(mode, deform_type="BEND"):
    properties.deform_type = deform_type
    properties.mode = mode
    deform.sync_controller(controller, pull_transform=False)
    actual = evaluated_points(obj)
    expected = tuple(
        deform.deform_point_local(
            point, properties.size, properties.deform_type,
            properties.strength, properties.factor, properties.direction,
            properties.mode, properties.origin, properties.preserve_volume)
        for point in vertices
    )
    for index, (actual_point, expected_point) in enumerate(zip(actual, expected)):
        check(close_vector(actual_point, expected_point),
              f"{mode} point {index}: {tuple(actual_point)} != {tuple(expected_point)}")
    return tuple(tuple(round(value, 4) for value in point) for point in actual)


for deform_name in ("BEND", "TWIST", "TAPER", "STRETCH"):
    for mode_name in ("LIMITED", "WITHIN_BOX", "UNLIMITED"):
        case(
            f"{deform_name.lower()}_{mode_name.lower()}",
            lambda mode_name=mode_name, deform_name=deform_name:
                compare_mode(mode_name, deform_name),
        )


def stretch_without_volume_compensation():
    properties.preserve_volume = False
    result = compare_mode("LIMITED", "STRETCH")
    properties.preserve_volume = True
    return result


case("stretch_without_volume_compensation", stretch_without_volume_compensation)


def independent_end_shape():
    properties.deform_type = "BEND"
    properties.strength = 0.0
    properties.direction = 0.0
    properties.mode = "LIMITED"
    properties.origin = "BOTTOM"
    properties.top_scale = (1.8, 0.6)
    properties.bottom_scale = (0.7, 1.2)
    properties.top_offset = (0.35, -0.15)
    properties.bottom_offset = (-0.2, 0.1)
    controller.rotation_euler = (0.0, 0.0, 0.0)
    deform.sync_controller(controller, pull_transform=False)

    actual = evaluated_points(obj)
    expected = tuple(
        deform.deform_point_local(
            point, properties.size, properties.deform_type,
            properties.strength, properties.factor, properties.direction,
            properties.mode, properties.origin, properties.preserve_volume,
            properties.top_scale, properties.bottom_scale,
            properties.top_offset, properties.bottom_offset)
        for point in vertices
    )
    check(all(close_vector(a, e) for a, e in zip(actual, expected)),
          "independent end profile does not match the reference formula")
    bottom_before = actual[0].copy()
    top_before = actual[4].copy()

    properties.top_scale = (2.2, 0.9)
    deform.sync_controller(controller, pull_transform=False)
    changed = evaluated_points(obj)
    check(close_vector(changed[0], bottom_before),
          "changing the top end also changed the bottom end")
    check(not close_vector(changed[4], top_before),
          "changing the top end did not change the top geometry")
    check(close_vector(deform.modifier_input(modifier, "Top Scale"), (2.2, 1.0, 0.9)),
          "top scale did not sync to Geometry Nodes")
    check(close_vector(deform.modifier_input(modifier, "Bottom Offset"), (-0.2, 0.0, 0.1)),
          "bottom offset did not sync to Geometry Nodes")

    obj.modifiers.active = modifier
    bpy.context.view_layer.objects.active = obj
    result = bpy.ops.sdh.reset_cage_ends()
    check(result == {"FINISHED"}, "reset independent ends operator failed")
    check(tuple(properties.top_scale) == (1.0, 1.0), "top scale was not reset")
    check(tuple(properties.bottom_scale) == (1.0, 1.0), "bottom scale was not reset")
    check(tuple(properties.top_offset) == (0.0, 0.0), "top offset was not reset")
    check(tuple(properties.bottom_offset) == (0.0, 0.0), "bottom offset was not reset")

    scale_drag = SimpleNamespace(
        side="TOP",
        invoke_target=obj,
        invoke_modifier=modifier,
        invoke_controller=controller,
        initial_scale=(1.0, 1.0),
        initial_offset=(0.0, 0.0),
        initial_mouse_x=100,
        initial_mouse_y=100,
        _mod_flags=(False, False, False),
    )
    drag_event = SimpleNamespace(
        mouse_region_x=160, mouse_region_y=100,
        shift=False, alt=False, ctrl=False)
    result = deform.SDHCageEndShapeGizmo.modal(
        scale_drag, bpy.context, drag_event, None)
    check(result == {"RUNNING_MODAL"}, "top handle scale drag was cancelled")
    check(close_vector(properties.top_scale, (1.6, 1.6)),
          "top handle did not update the selected end scale")
    check(close_vector(properties.bottom_scale, (1.0, 1.0)),
          "top handle drag changed the bottom scale")

    slide_drag = SimpleNamespace(
        side="TOP",
        invoke_target=obj,
        invoke_modifier=modifier,
        invoke_controller=controller,
        initial_scale=tuple(properties.top_scale),
        initial_offset=(0.0, 0.0),
        initial_mouse_x=100,
        initial_mouse_y=100,
        _mod_flags=(False, False, True),
    )
    slide_event = SimpleNamespace(
        mouse_region_x=140, mouse_region_y=100,
        shift=False, alt=True, ctrl=False)
    result = deform.SDHCageEndShapeGizmo.modal(
        slide_drag, bpy.context, slide_event, None)
    check(result == {"RUNNING_MODAL"}, "top handle Alt slide was cancelled")
    check(close_vector(properties.top_offset, (0.2, 0.0)),
          "top handle Alt drag did not slide the selected end")
    check(close_vector(properties.bottom_offset, (0.0, 0.0)),
          "top handle Alt drag changed the bottom offset")
    bpy.ops.sdh.reset_cage_ends()
    properties.strength = math.radians(90.0)
    return tuple(round(value, 4) for value in changed[4])


case("independent_end_shape", independent_end_shape)


def independent_cage_boundaries():
    properties.deform_type = "BEND"
    properties.strength = 0.0
    properties.size = (2.0, 4.0, 2.0)
    controller.location = (0.0, 0.0, 0.0)
    controller.rotation_euler = (0.0, 0.0, 0.0)
    properties.limit_boundaries_to_object = True
    deform.sync_controller(controller, pull_transform=False)

    axis_limits = deform.cage_input_axis_limits(
        bpy.context, obj, modifier, controller)
    check(close_vector(axis_limits, (-2.0, 2.0)),
          f"wrong input bounds along cage axis: {axis_limits!r}")
    controller.rotation_euler = (0.0, 0.0, -math.pi * 0.5)
    x_axis_limits = deform.cage_input_axis_limits(
        bpy.context, obj, modifier, controller)
    check(close_vector(x_axis_limits, (-0.25, 1.5)),
          f"axis-switched bounds were not projected correctly: {x_axis_limits!r}")
    controller.rotation_euler = (0.0, 0.0, 0.0)

    # View projection is unavailable in a background process. The movement
    # and clamping contract below exercises the same boundary implementation.

    def boundary(side):
        half_y = properties.size[1] * 0.5
        local = Vector((0.0, half_y if side == "TOP" else -half_y, 0.0))
        return Vector(controller.location) + controller.rotation_euler.to_matrix() @ local

    initial_top = boundary("TOP")
    initial_bottom = boundary("BOTTOM")
    initial_size = tuple(properties.size)
    initial_location = tuple(controller.location)
    applied, length = deform.move_cage_boundary(
        controller, "TOP", 1.25, initial_size, initial_location, axis_limits)
    check(abs(applied) < 1.0e-5 and abs(length - 4.0) < 1.0e-5,
          "top boundary escaped the object bounds")
    check(close_vector(boundary("BOTTOM"), initial_bottom),
          "moving the top boundary moved the bottom boundary")
    check(close_vector(boundary("TOP"), initial_top),
          "clamped top boundary changed unexpectedly")

    initial_size = tuple(properties.size)
    initial_location = tuple(controller.location)
    applied, length = deform.move_cage_boundary(
        controller, "TOP", -0.75, initial_size, initial_location, axis_limits)
    check(abs(applied + 0.75) < 1.0e-5 and abs(length - 3.25) < 1.0e-5,
          "top boundary could not move inward")
    check(close_vector(boundary("BOTTOM"), initial_bottom),
          "inward top movement changed the bottom boundary")

    top_before_bottom_drag = boundary("TOP")
    bottom_before_bottom_drag = boundary("BOTTOM")
    second_size = tuple(properties.size)
    second_location = tuple(controller.location)
    applied, length = deform.move_cage_boundary(
        controller, "BOTTOM", -0.75, second_size, second_location, axis_limits)
    check(abs(applied) < 1.0e-5 and abs(length - 3.25) < 1.0e-5,
          "bottom boundary escaped the object bounds")
    check(close_vector(boundary("TOP"), top_before_bottom_drag),
          "moving the bottom boundary moved the top boundary")
    check(close_vector(boundary("BOTTOM"), bottom_before_bottom_drag),
          "clamped bottom boundary changed unexpectedly")

    second_size = tuple(properties.size)
    second_location = tuple(controller.location)
    applied, length = deform.move_cage_boundary(
        controller, "BOTTOM", 0.5, second_size, second_location, axis_limits)
    check(abs(applied - 0.5) < 1.0e-5 and abs(length - 2.75) < 1.0e-5,
          "bottom boundary could not move inward")
    check(close_vector(boundary("TOP"), top_before_bottom_drag),
          "inward bottom movement changed the top boundary")

    properties.size = (2.0, 4.0, 2.0)
    controller.location = (0.0, 0.0, 0.0)
    deform.sync_controller(controller, pull_transform=False)
    modal_bottom_before = boundary("BOTTOM")
    drag = SimpleNamespace(
        side="TOP",
        invoke_target=obj,
        invoke_modifier=modifier,
        invoke_controller=controller,
        initial_size=(2.0, 4.0, 2.0),
        initial_location=(0.0, 0.0, 0.0),
        initial_curve_range=(0.0, 1.0),
        initial_mouse=(100, 100),
        axis_screen=(0.0, 1.0),
        units_per_pixel=0.01,
        boundary_limits=axis_limits,
        shared_edit_state=None,
        chain_edit_state=None,
        _mod_flags=(False, False, False),
    )
    event = SimpleNamespace(
        mouse_region_x=100, mouse_region_y=180,
        shift=False, ctrl=False)
    result = deform.SDHCageBoundaryGizmo.modal(
        drag, bpy.context, event, None)
    check(result == {"RUNNING_MODAL"}, "top length handle drag was cancelled")
    check(close_vector(boundary("BOTTOM"), modal_bottom_before),
          "top length handle changed the bottom boundary")
    check(abs(properties.size[1] - 4.0) < 1.0e-5,
          "modal top handle escaped the object bounds")
    check(close_vector(deform.modifier_input(modifier, "Size"), (2.0, 4.0, 2.0)),
          "clamped length did not sync to Geometry Nodes")

    event.mouse_region_y = 20
    result = deform.SDHCageBoundaryGizmo.modal(
        drag, bpy.context, event, None)
    check(result == {"RUNNING_MODAL"}, "inward top length drag was cancelled")
    check(abs(properties.size[1] - 3.2) < 1.0e-5,
          "modal top handle could not move inward")
    check(close_vector(boundary("BOTTOM"), modal_bottom_before),
          "inward modal drag changed the bottom boundary")

    properties.size = (2.0, 4.0, 2.0)
    controller.location = (0.0, 0.0, 0.0)
    properties.limit_boundaries_to_object = False
    deform.sync_controller(controller, pull_transform=False)
    drag.boundary_limits = None
    event.mouse_region_y = 180
    deform.SDHCageBoundaryGizmo.modal(drag, bpy.context, event, None)
    check(abs(properties.size[1] - 4.8) < 1.0e-5,
          "disabling the object-bound limit did not restore free dragging")

    properties.size = (2.0, 2.0, 2.0)
    controller.location = (0.0, 0.0, 0.0)
    properties.limit_boundaries_to_object = True
    properties.strength = math.radians(90.0)
    deform.sync_controller(controller, pull_transform=False)
    return "top and bottom boundaries stay independent and within object bounds"


case("independent_cage_boundaries", independent_cage_boundaries)


def origin_modes():
    properties.deform_type = "BEND"
    properties.mode = "UNLIMITED"
    properties.size = (2.0, 4.0, 2.0)
    properties.top_scale = (1.0, 1.0)
    properties.bottom_scale = (1.0, 1.0)
    properties.top_offset = (0.0, 0.0)
    properties.bottom_offset = (0.0, 0.0)
    controller.location = (0.0, 0.0, 0.0)
    controller.rotation_euler = (0.0, 0.0, 0.0)
    results = {}
    for origin in ("BOTTOM", "CENTER", "SYMMETRIC", "TOP"):
        properties.origin = origin
        deform.sync_controller(controller, pull_transform=False)
        actual = evaluated_points(obj)
        expected = tuple(
            deform.deform_point_local(
                point, properties.size, properties.deform_type,
                properties.strength, properties.factor, properties.direction,
                properties.mode, properties.origin, properties.preserve_volume)
            for point in vertices
        )
        check(all(close_vector(a, e) for a, e in zip(actual, expected)),
              f"{origin} does not match the reference formula")
        results[origin] = tuple(
            tuple(round(value, 4) for value in point) for point in actual)
    return results


case("origin_modes", origin_modes)


def direction_and_controller_rotation():
    properties.deform_type = "BEND"
    properties.origin = "CENTER"
    properties.direction = math.radians(90.0)
    controller.rotation_euler = Euler((0.0, math.radians(35.0), 0.0))
    deform.sync_controller(controller, pull_transform=False)
    rotation = controller.rotation_euler.to_matrix()
    actual = evaluated_points(obj)
    expected = tuple(
        rotation @ deform.deform_point_local(
            rotation.inverted() @ Vector(point),
            properties.size, properties.deform_type, properties.strength,
            properties.factor, properties.direction, properties.mode,
            properties.origin, properties.preserve_volume)
        for point in vertices
    )
    check(all(close_vector(a, e) for a, e in zip(actual, expected)),
          "direction or cage rotation mapping is wrong")
    return tuple(round(value, 4) for value in actual[-1])


case("direction_and_controller_rotation", direction_and_controller_rotation)


def axis_alignment_and_fit():
    obj.modifiers.active = modifier
    bpy.context.view_layer.objects.active = obj
    result = bpy.ops.sdh.set_cage_axis(alignment="NEG_Z")
    check(result == {"FINISHED"}, "axis operator failed")
    check(properties.alignment == "NEG_Z", "axis choice was not stored")
    check(abs(controller.rotation_euler.x + math.pi * 0.5) < 1.0e-4,
          "cage was not aligned to -Z")
    check(all(value > 0.0 for value in properties.size), "fit produced an invalid size")
    bpy.ops.sdh.set_cage_axis(alignment="AUTO")
    return tuple(round(value, 4) for value in controller.rotation_euler)


case("axis_alignment_and_fit", axis_alignment_and_fit)


def axis_selection_visibility_contract():
    """Axis selection is one-shot unless the Ctrl-style flag is retained."""
    original_alignment = properties.alignment
    original_show = properties.show_axis_gizmo
    try:
        properties.cage_type = "SHEAR"
        deform.core.set_deform_layers(properties, ("SHEAR",), bpy.context)
        properties.show_axis_gizmo = True
        result = bpy.ops.sdh.set_cage_axis(
            alignment="POS_X", keep_open=False)
        check(result == {"FINISHED"}, "one-shot axis selection failed")
        check(properties.alignment == "POS_X",
              "one-shot axis selection did not store the axis")
        check(not properties.show_axis_gizmo,
              "normal axis selection did not hide the chooser")

        properties.show_axis_gizmo = True
        result = bpy.ops.sdh.set_cage_axis(
            alignment="NEG_Y", keep_open=True)
        check(result == {"FINISHED"}, "persistent axis selection failed")
        check(properties.alignment == "NEG_Y",
              "persistent axis selection did not store the axis")
        check(properties.show_axis_gizmo,
              "Ctrl-style axis selection did not keep the chooser visible")
        return properties.alignment
    finally:
        properties.cage_type = "STANDARD"
        deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
        properties.alignment = original_alignment
        properties.show_axis_gizmo = original_show
        deform.sync_controller(controller, pull_transform=False)


case("axis_selection_visibility_contract", axis_selection_visibility_contract)


def duplicate_retained_stage_ownership():
    duplicate = obj.copy()
    duplicate_data = obj.data.copy()
    duplicate.data = duplicate_data
    duplicate.name = "Cage Duplicate Retained"
    bpy.context.collection.objects.link(duplicate)
    source_uuid = str(obj[deform.TARGET_UUID])
    source_group = modifier.node_group
    source_strength = float(deform.modifier_input(modifier, "Strength"))
    try:
        activate(obj)
        deform.resolve_context_deform(bpy.context)
        check(str(obj[deform.TARGET_UUID]) == source_uuid,
              "selecting the source reassigned ownership because a copy exists")
        activate(duplicate)
        copied_target, copied_modifier, copied_controller = (
            deform.resolve_context_deform(bpy.context))
        check(copied_target == duplicate and copied_modifier is not None,
              "copied retained stage could not be resolved")
        check(str(duplicate[deform.TARGET_UUID]) != source_uuid,
              "copied retained stack did not receive unique target ownership")
        check(copied_modifier.node_group != source_group,
              "copied retained stage still shares the source node group")
        check(copied_controller is not None and copied_controller.parent == duplicate,
              "copied retained stage did not receive its own controller")
        copied_controller.sdh_cage_deform.strength = math.radians(22.0)
        deform.sync_controller(copied_controller, pull_transform=False)
        check(abs(float(deform.modifier_input(modifier, "Strength")) - source_strength) < 1.0e-5,
              "editing the copied stack changed the source stage")
        check(bpy.ops.sdh.remove_cage_stack() == {"FINISHED"},
              "copied retained stack could not be removed")
        return "retained copied stages detach from source ownership"
    finally:
        for item in tuple(bpy.data.objects):
            if deform.is_cage_controller(item) and item.parent == duplicate:
                bpy.data.objects.remove(item, do_unlink=True)
        bpy.data.objects.remove(duplicate, do_unlink=True)
        if duplicate_data.users == 0:
            bpy.data.meshes.remove(duplicate_data)
        activate(obj)
        obj.modifiers.active = modifier


case("duplicate_retained_stage_ownership", duplicate_retained_stage_ownership)


def duplicate_rebuild_and_stack_removal():
    duplicate = obj.copy()
    duplicate_data = obj.data.copy()
    duplicate.data = duplicate_data
    duplicate.name = "Cage Duplicate Rebuild"
    bpy.context.collection.objects.link(duplicate)
    source_uuid = str(obj[deform.TARGET_UUID])
    try:
        check(str(duplicate[deform.TARGET_UUID]) == source_uuid,
              "test duplicate did not inherit the source ownership UUID")
        for copied_modifier in tuple(duplicate.modifiers):
            if deform.is_cage_modifier(copied_modifier):
                duplicate.modifiers.remove(copied_modifier)

        activate(duplicate)
        check(bpy.ops.sdh.add_cage_deform() == {"FINISHED"},
              "re-adding Cage Deform to a copied target failed")
        rebuilt_stages = deform.cage_modifiers(duplicate)
        check(len(rebuilt_stages) == 1,
              "copied target did not receive exactly one rebuilt stage")
        check(str(duplicate[deform.TARGET_UUID]) != source_uuid,
              "copied target kept the source ownership UUID")
        rebuilt_controller = deform.find_controller(duplicate, rebuilt_stages[0])
        check(rebuilt_controller is not None and rebuilt_controller.parent == duplicate,
              "rebuilt controller was linked back to the source target")
        check(deform.find_target(rebuilt_controller) == duplicate,
              "rebuilt controller resolves to the wrong copied target")
        rebuilt_properties = rebuilt_controller.sdh_cage_deform
        rebuilt_properties.strength = math.radians(70.0)
        deform.sync_controller(rebuilt_controller, pull_transform=False)
        original_points = tuple(vertex.co.copy() for vertex in duplicate.data.vertices)
        changed_points = evaluated_points(duplicate)
        check(any(not close_vector(a, b) for a, b in zip(original_points, changed_points)),
              "rebuilt stage on the copied target has no deformation effect")

        rebuilt_controller_name = rebuilt_controller.name
        rebuilt_controller_uuid = str(
            rebuilt_controller[deform.CONTROLLER_UUID])
        duplicate.modifiers.remove(rebuilt_stages[0])
        check(rebuilt_controller_name in bpy.data.objects,
              "direct modifier removal unexpectedly removed its controller")
        check(bpy.ops.sdh.add_cage_deform() == {"FINISHED"},
              "adding after direct Geometry Nodes removal failed")
        check(not any(
            deform.is_cage_controller(item) and
            str(item.get(deform.CONTROLLER_UUID, "")) == rebuilt_controller_uuid
            for item in bpy.data.objects
        ),
              "adding after direct modifier removal kept an orphan controller")
        check(len(deform.cage_modifiers(duplicate)) == 1,
              "direct removal and re-add produced an invalid stack")

        check(bpy.ops.sdh.add_cage_deform() == {"FINISHED"},
              "second copied-target stage could not be added")
        check(len(deform.cage_modifiers(duplicate)) == 2,
              "copied target did not receive a two-stage stack")
        check(bpy.ops.sdh.remove_cage_deform(index=0) == {"FINISHED"},
              "indexed N-panel stage removal failed")
        check(len(deform.cage_modifiers(duplicate)) == 1,
              "indexed stage removal changed the wrong number of stages")
        check(bpy.ops.sdh.add_cage_deform() == {"FINISHED"},
              "stage could not be re-added before whole-stack removal")
        check(bpy.ops.sdh.remove_cage_stack() == {"FINISHED"},
              "whole cage-stack removal failed")
        check(not deform.cage_modifiers(duplicate),
              "whole-stack removal left a managed modifier")
        check(not any(
            deform.is_cage_controller(item) and item.parent == duplicate
            for item in bpy.data.objects
        ), "whole-stack removal left an owned controller")
        return "duplicate rebuild and N-panel removals remain independent"
    finally:
        for item in tuple(bpy.data.objects):
            if deform.is_cage_controller(item) and item.parent == duplicate:
                bpy.data.objects.remove(item, do_unlink=True)
        bpy.data.objects.remove(duplicate, do_unlink=True)
        if duplicate_data.users == 0:
            bpy.data.meshes.remove(duplicate_data)
        activate(obj)
        obj.modifiers.active = modifier


case("duplicate_rebuild_and_stack_removal", duplicate_rebuild_and_stack_removal)


def legacy_stage_migration():
    legacy_family = "prototype_cage"
    legacy_mesh = bpy.data.meshes.new("Legacy Cage Migration")
    legacy_mesh.from_pydata(((-0.5, -1.0, 0.0), (0.5, 1.0, 0.0)), (), ())
    legacy_object = bpy.data.objects.new("Legacy Cage Migration", legacy_mesh)
    bpy.context.collection.objects.link(legacy_object)
    legacy_modifier, legacy_controller, _previous = deform.create_deform_stage(
        bpy.context, legacy_object, name="Legacy Cage Stage")
    legacy_properties = legacy_controller.sdh_cage_deform
    legacy_properties.strength = math.radians(33.0)
    legacy_properties.direction = math.radians(12.0)
    legacy_properties.mode = "WITHIN_BOX"
    legacy_properties.origin = "SYMMETRIC"
    deform.sync_controller(legacy_controller, pull_transform=False)

    old_modifier_uuid = deform.cage_modifier_uuid(legacy_modifier)
    old_target_uuid = str(legacy_object[deform.TARGET_UUID])
    group = legacy_modifier.node_group
    del group[deform.MODIFIER_MARKER]
    del group[deform.MODIFIER_UUID]
    group[f"_sdh_{legacy_family}_stage"] = True
    group[f"_sdh_{legacy_family}_modifier_uuid"] = old_modifier_uuid
    del legacy_object[deform.TARGET_UUID]
    legacy_object[f"_sdh_{legacy_family}_target_uuid"] = old_target_uuid
    for key in (deform.CONTROLLER_MARKER, deform.CONTROLLER_UUID,
                deform.TARGET_UUID, deform.MODIFIER_UUID):
        if key in legacy_controller:
            del legacy_controller[key]
    legacy_controller[f"_sdh_{legacy_family}_controller"] = True
    legacy_controller[f"_sdh_{legacy_family}_controller_uuid"] = "legacy-controller"
    legacy_controller[f"_sdh_{legacy_family}_target_uuid"] = old_target_uuid
    legacy_controller[f"_sdh_{legacy_family}_modifier_uuid"] = old_modifier_uuid

    check(deform.migrate_legacy_stages() == 1, "legacy stage was not migrated")
    check(deform.is_cage_modifier(legacy_modifier), "migrated modifier is unmanaged")
    check(deform.find_controller(legacy_object, legacy_modifier) == legacy_controller,
          "migrated controller ownership is broken")
    migrated = legacy_controller.sdh_cage_deform
    check(migrated.mode == "WITHIN_BOX" and migrated.origin == "SYMMETRIC",
          "legacy spatial settings were not preserved")
    check(not any(legacy_family in key for key in legacy_controller.keys()),
          "legacy controller identifiers remain visible")
    return legacy_modifier.node_group.name


case("legacy_stage_migration", legacy_stage_migration)


def managed_stage_version_upgrade():
    properties.top_scale = (1.35, 0.8)
    properties.bottom_offset = (-0.15, 0.2)
    properties.show_axis_gizmo = True
    properties.show_direction_handle = True
    modifier.node_group[deform.GROUP_MARKER] = deform.GROUP_VERSION - 1
    check(deform.upgrade_managed_stages() == 1,
          "older managed stage was not upgraded")
    check(modifier.node_group.get(deform.GROUP_MARKER) == deform.GROUP_VERSION,
          "managed stage version marker was not refreshed")
    check(close_vector(deform.modifier_input(modifier, "Top Scale"), (1.35, 1.0, 0.8)),
          "controller values were not restored after group upgrade")
    check(not properties.show_axis_gizmo and not properties.show_direction_handle,
          "upgraded stages kept legacy always-visible direction controls")
    check(controller.empty_display_type == deform.CONTROLLER_STYLES["BEND"][0],
          "upgraded controller did not receive the Bend visual style")
    properties.top_scale = (1.0, 1.0)
    properties.bottom_offset = (0.0, 0.0)
    deform.sync_controller(controller, pull_transform=False)
    return len(modifier.node_group.nodes)


case("managed_stage_version_upgrade", managed_stage_version_upgrade)


def multiple_deform_stages():
    second, second_controller, _previous = deform.create_deform_stage(
        bpy.context, obj, name="Cage Deform Second", after_modifier=modifier)
    second_properties = second_controller.sdh_cage_deform
    second_properties.deform_type = "TWIST"
    second_properties.size = (3.0, 4.0, 3.0)
    second_properties.strength = math.radians(-35.0)
    second_properties.direction = math.radians(25.0)
    second_properties.mode = "UNLIMITED"
    second_properties.origin = "CENTER"
    second_controller.location = (0.0, 0.0, 0.0)
    second_controller.rotation_euler = (0.0, 0.0, 0.0)
    deform.sync_controller(second_controller, pull_transform=False)
    check(tuple(obj.modifiers).index(second) == tuple(obj.modifiers).index(modifier) + 1,
          "second deformation was not inserted after the active stage")
    check(len(deform.cage_modifiers(obj)) == 2, "multi-stage cage stack was not created")
    points = evaluated_points(obj)
    check(any(not close_vector(point, source) for point, source in zip(points, vertices)),
          "two-stage result did not deform")
    stage_state["second"] = second
    stage_state["controller"] = second_controller
    return tuple(item.name for item in deform.cage_modifiers(obj))


case("multiple_deform_stages", multiple_deform_stages)


def stage_order_controls():
    second = stage_state["second"]
    before_order = deform.cage_modifiers(obj)
    second_strength = float(deform.modifier_input(second, "Twist Angle"))
    result = bpy.ops.sdh.move_cage_deform(index=1, direction="EARLIER")
    check(result == {"FINISHED"}, "move-earlier operator failed")
    after_order = deform.cage_modifiers(obj)
    check(after_order == (second, modifier), "cage stage order was not swapped")
    check(abs(float(deform.modifier_input(second, "Twist Angle")) -
              second_strength) < 1.0e-6,
          "moving a cage stage changed its authored parameters")
    result = bpy.ops.sdh.move_cage_deform(index=0, direction="LATER")
    check(result == {"FINISHED"}, "move-later operator failed")
    check(deform.cage_modifiers(obj) == before_order, "original stage order was not restored")
    return tuple(item.name for item in deform.cage_modifiers(obj))


case("stage_order_controls", stage_order_controls)


def animation_and_render_sync():
    second = stage_state["second"]
    second_controller = stage_state["controller"]
    second_properties = second_controller.sdh_cage_deform
    second_properties.deform_type = "BEND"
    scene = bpy.context.scene

    second_properties.bend_strength = math.radians(10.0)
    second_controller.location.x = -0.35
    second_controller.keyframe_insert(
        data_path="sdh_cage_deform.bend_strength", frame=1)
    second_controller.keyframe_insert(data_path="location", frame=1)
    second_properties.bend_strength = math.radians(80.0)
    second_controller.location.x = 0.45
    second_controller.keyframe_insert(
        data_path="sdh_cage_deform.bend_strength", frame=12)
    second_controller.keyframe_insert(data_path="location", frame=12)

    scene.frame_set(1)
    check(abs(float(deform.modifier_input(second, "Bend Angle")) -
              math.radians(10.0)) < 1.0e-4,
          "frame-change handler did not sync animated Bend angle")
    check(abs(Vector(deform.modifier_input(second, "Center")).x + 0.35) < 1.0e-4,
          "frame-change handler did not sync animated controller transform")
    scene.frame_set(12)
    check(abs(float(deform.modifier_input(second, "Bend Angle")) -
              math.radians(80.0)) < 1.0e-4,
          "later animated Bend angle was not synced")
    deform.core._render_sync(scene)
    check(abs(Vector(deform.modifier_input(second, "Center")).x - 0.45) < 1.0e-4,
          "render handler did not preserve the current controller transform")
    return math.degrees(float(deform.modifier_input(second, "Bend Angle")))


case("animation_and_render_sync", animation_and_render_sync)


def cage_keyframe_operators():
    second = stage_state["second"]
    second_controller = stage_state["controller"]
    properties = second_controller.sdh_cage_deform
    scene = bpy.context.scene
    activate(obj)
    obj.modifiers.active = second

    deform.core.set_deform_layers(
        properties, ("BEND", "TWIST"), bpy.context)
    for frame, size, bend, twist in (
            (20, (2.0, 4.0, 3.0), math.radians(20.0), math.radians(-15.0)),
            (30, (4.0, 8.0, 6.0), math.radians(50.0), math.radians(35.0))):
        scene.frame_set(frame)
        properties.size = size
        properties.bend_strength = bend
        properties.twist_strength = twist
        check(bpy.ops.sdh.insert_cage_keyframes() == {"FINISHED"},
              "cage keyframe insertion failed")

    animated_paths = deform.core._animation_paths(second_controller)
    required = {
        "sdh_cage_deform.size",
        "sdh_cage_deform.bend_strength",
        "sdh_cage_deform.twist_strength",
        "location",
        "rotation_euler",
    }
    check(required.issubset(animated_paths),
          f"cage keyframe channels are missing: {required - set(animated_paths)!r}")

    scene.frame_set(25)
    expected_size = Vector((3.0, 6.0, 4.5))
    check(close_vector(properties.size, expected_size, tolerance=1.0e-3),
          "animated cage size was overwritten by the controller scale")
    check(close_vector(
        deform.modifier_input(second, "Size"), expected_size,
        tolerance=1.0e-3),
        "animated cage size was not synced to Geometry Nodes")
    check(close_vector(
        Vector(second_controller.scale) * 2.0, expected_size,
        tolerance=1.0e-3),
        "controller display scale did not follow animated cage size")

    for frame in (20, 30):
        scene.frame_set(frame)
        check(bpy.ops.sdh.delete_cage_keyframes() == {"FINISHED"},
              "cage keyframe deletion failed")
    return sorted(required)


case("cage_keyframe_operators", cage_keyframe_operators)


def survives_extension_disable():
    before = evaluated_points(obj)
    addon.unregister()
    after = evaluated_points(obj)
    check(all(close_vector(a, b) for a, b in zip(before, after)),
          "generated Geometry Nodes changed after extension disable")
    return "geometry remains procedural"


case("survives_extension_disable", survives_extension_disable)

if hasattr(bpy.types.Object, "sdh_cage_deform"):
    try:
        addon.unregister()
    except Exception:
        traceback.print_exc()
try:
    bpy.context.preferences.addons.remove(entry)
except Exception:
    traceback.print_exc()

if failures:
    print(f"SDH_CAGE::SUMMARY::FAIL::{failures!r}")
    raise SystemExit(1)
print("SDH_CAGE::SUMMARY::PASS")
