"""Runtime regressions for multi-layer and chained Cage Deform workflows.

Run with:
    blender --background --factory-startup --python-exit-code 1 \
        --python tests/cage_chain_regression.py
"""

import importlib
import math
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy
from mathutils import Vector


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))
failures = []


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def close_vector(actual, expected, tolerance=3.0e-4):
    return (Vector(actual) - Vector(expected)).length <= tolerance


def case(name, function):
    try:
        result = function()
    except Exception as exc:
        failures.append((name, type(exc).__name__, str(exc)))
        print(f"SDH_CHAIN::{name}::FAIL::{type(exc).__name__}::{exc}")
        traceback.print_exc()
    else:
        print(f"SDH_CHAIN::{name}::PASS::{result!r}")


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def make_object(name, vertices):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, (), ())
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    activate(obj)
    return obj


def evaluated_points(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def endpoint(controller, side):
    properties = controller.sdh_cage_deform
    sign = 1.0 if side == "TOP" else -1.0
    rotation = deform.core._controller_rotation_xyz(controller).to_matrix()
    return Vector(controller.location) + rotation @ Vector((
        0.0, sign * properties.size[1] * 0.5, 0.0))


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain


def multi_layer_stack():
    vertices = (
        (-0.8, -2.0, -0.3),
        (0.7, -0.8, 0.4),
        (0.35, 0.3, 0.9),
        (-0.6, 1.1, 0.5),
        (0.9, 2.0, -0.7),
    )
    target = make_object("SDH Multi Layer", vertices)
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target, show_other_default=False)
    properties = controller.sdh_cage_deform
    properties.size = (2.4, 4.0, 2.4)
    properties.mode = "LIMITED"
    properties.origin = "BOTTOM"
    controller.location = (0.0, 0.0, 0.0)
    controller.rotation_euler = (0.0, 0.0, 0.0)

    check(deform.core.set_deform_layers(
        properties, ("BEND", "TWIST", "TAPER"), bpy.context),
        "multi-layer stack was not created")
    properties.bend_strength = math.radians(62.0)
    properties.bend_direction = math.radians(18.0)
    properties.twist_strength = math.radians(47.0)
    properties.taper_factor = 0.35
    deform.sync_controller(controller, pull_transform=False)

    ordered = deform.core.ordered_deform_types(properties)
    check(ordered == ("BEND", "TWIST", "TAPER"),
          f"wrong initial layer order: {ordered!r}")
    check("BEND" in properties.expanded_deform_layers,
          "deformation layers were not expanded by default")
    check(bpy.ops.sdh.select_deform_layer(index=0) == {"FINISHED"},
          "layer disclosure control failed")
    check("BEND" not in properties.expanded_deform_layers,
          "layer disclosure control did not collapse its row")
    check(bpy.ops.sdh.expand_all_deform_layers() == {"FINISHED"},
          "expand-all operator failed")
    check(set(ordered).issubset(set(properties.expanded_deform_layers)),
          "expand-all operator did not expand every row")
    actual = evaluated_points(target)
    expected = tuple(
        deform.deform_point_from_properties(point, properties, evaluator=True)
        for point in vertices
    )
    check(all(close_vector(a, b) for a, b in zip(actual, expected)),
          "multi-layer Geometry Nodes result differs from the reference")

    check(deform.core.move_deform_layer(properties, 1, "UP", bpy.context),
          "layer reorder failed")
    reordered = deform.core.ordered_deform_types(properties)
    check(reordered == ("TWIST", "BEND", "TAPER"),
          f"wrong reordered layer stack: {reordered!r}")
    after_reorder = evaluated_points(target)
    check(any(not close_vector(a, b)
              for a, b in zip(actual, after_reorder)),
          "changing layer order had no evaluated effect")

    twist_value = properties.twist_strength
    check(deform.core.set_deform_layer_muted(
        properties, "TWIST", True, bpy.context),
        "temporary layer bypass failed")
    muted = evaluated_points(target)
    check(any(not close_vector(a, b)
              for a, b in zip(after_reorder, muted)),
          "temporarily bypassing Twist had no evaluated effect")
    check(abs(properties.twist_strength - twist_value) < 1.0e-7,
          "temporary bypass discarded the Twist value")

    properties.stage_enabled = False
    deform.sync_controller(controller, pull_transform=False)
    bypassed = evaluated_points(target)
    check(all(close_vector(point, source)
              for point, source in zip(bypassed, vertices)),
          "disabled cage stage still deforms geometry")
    properties.stage_enabled = True
    deform.core.set_deform_layer_muted(
        properties, "TWIST", False, bpy.context)
    target.modifiers.active = modifier
    return reordered


case("multi_layer_stack", multi_layer_stack)


def chained_creation_and_batch_edit():
    vertices = (
        (-0.7, -3.0, -0.5), (0.7, -3.0, 0.5),
        (-0.8, 0.0, 0.6), (0.8, 0.0, -0.6),
        (-0.6, 3.0, -0.4), (0.6, 3.0, 0.4),
    )
    target = make_object("SDH Chained Creation", vertices)
    result = bpy.ops.sdh.add_cage_chain(
        count=3,
        connection_mode="CHAINED",
        gap=0.15,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        alignment="POS_Y",
    )
    check(result == {"FINISHED"}, "chain creation operator failed")
    stages = chain.chain_stages(target)
    check(len(stages) == 3, f"expected 3 chain stages, got {len(stages)}")
    report = chain.validate_chain(target, chain.stage_chain_uuid(stages[0]))
    check(not report["broken"], f"new chain is broken: {report['messages']!r}")
    check(tuple(chain.stage_chain_index(stage) for stage in stages) == (0, 1, 2),
          "chain stages are not ordered")

    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    check(all(controllers), "a chain stage has no controller")
    check(all(item.sdh_cage_deform.show_other_cages for item in controllers),
          "chain did not enable multi-cage display")
    check(all(item.sdh_cage_deform.auto_reconnect for item in controllers),
          "chain did not enable automatic reconnect")
    check(all(not item.sdh_cage_deform.auto_sync_upstream
              for item in controllers),
          "chain incorrectly inherited ordinary-stack auto sync")
    check(all(not deform.core._stack_auto_fit_enabled(item, stage)
              for item, stage in zip(controllers, stages)),
          "chain stage entered the ordinary-stack auto-fit queue")
    check(all(item.sdh_cage_deform.sync_shared_end_scale for item in controllers),
          "chain did not enable shared-end scale sync")

    for index in range(1, len(stages)):
        gap = chain.stage_chain_gap(stages[index])
        previous_top, _x_axis, previous_y, _z_axis = chain._stage_top_frame(
            target, controllers[index - 1])
        current_bottom = endpoint(controllers[index], "BOTTOM")
        expected_bottom = previous_top + previous_y * gap
        check(close_vector(current_bottom, expected_bottom),
              f"stage {index} does not preserve its authored gap")

    initial_domain = (
        sum(item.sdh_cage_deform.size[1] for item in controllers) +
        sum(chain.stage_chain_gap(stage) for stage in stages[1:])
    )
    check(chain.set_stage_chain_gap(
        target, stages[1], 0.3, preserve_span=True),
        "editing an interior gap failed")
    updated_domain = (
        sum(item.sdh_cage_deform.size[1] for item in controllers) +
        sum(chain.stage_chain_gap(stage) for stage in stages[1:])
    )
    check(abs(updated_domain - initial_domain) < 3.0e-4,
          "preserve-span gap editing changed the chain range")

    changed = chain.apply_chain_batch_edit(
        target,
        stages[0],
        scope="ALL",
        operation="END_SCALE",
        end_side="BOTH",
        assignment="SET",
        scale=(1.3, 0.75),
    )
    check(changed == 3, f"batch scale updated {changed} stages")
    check(all(close_vector(item.sdh_cage_deform.top_scale, (1.3, 0.75)) and
              close_vector(item.sdh_cage_deform.bottom_scale, (1.3, 0.75))
              for item in controllers),
          "batch end scale did not update the full chain")

    chain.apply_chain_batch_edit(
        target,
        stages[0],
        scope="ALL",
        operation="DEFORMATION",
        deform_type="BEND",
        assignment="SET",
        angle_value=0.0,
    )
    before = tuple(Vector(item.location) for item in controllers[1:])
    controllers[0].sdh_cage_deform.bend_strength = math.radians(55.0)
    deform.sync_controller(controllers[0], pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    after = tuple(Vector(item.location) for item in controllers[1:])
    check(any(not close_vector(a, b) for a, b in zip(before, after)),
          "downstream cage frames did not refresh after an upstream bend")
    for stage_controller in controllers:
        stage_properties = stage_controller.sdh_cage_deform
        half_y = float(stage_properties.size[1]) * 0.5
        sample = max(abs(float(stage_properties.size[1])) * 0.01, 1.0e-5)
        for side, sign in (("TOP", 1.0), ("BOTTOM", -1.0)):
            boundary, handle = deform.cage_boundary_points_local(
                stage_properties, side)
            expected = deform.core.deform_point_for_display(
                (0.0, sign * half_y, 0.0), stage_properties)
            inside = deform.core.deform_point_for_display(
                (0.0, sign * half_y - sign * sample, 0.0),
                stage_properties)
            tangent = Vector(expected) - Vector(inside)
            check(close_vector(boundary, expected, tolerance=2.0e-5),
                  f"{side} boundary handle did not follow the deformed end")
            check(tangent.length > 1.0e-6 and
                  (Vector(handle) - Vector(boundary)).normalized().dot(
                      tangent.normalized()) > 0.999,
                  f"{side} boundary handle did not follow the end tangent")

    activate(target)
    target.modifiers.active = stages[0]
    deform.core.refresh_controller_display(bpy.context, force=True)
    check(all(item.select_get() for item in controllers),
          "target selection did not sync the complete chain controllers")
    check(all(not item.hide_get() and not item.hide_select for item in controllers),
          "selected chain controllers were not made available to the Timeline")
    check(all(item.sdh_cage_deform.show_other_cages for item in controllers),
          "show-other-cages was not enabled across the chain")
    check(bpy.ops.sdh.select_cage_stage(index=2) == {"FINISHED"},
          "chain stage picker failed")
    check(bpy.context.object == target and
           target.modifiers.active == stages[2],
          "chain stage picker selected the wrong cage")
    check(all(item.select_get() for item in controllers),
          "chain stage picker lost synchronized controller selection")

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = None
    deform.core.refresh_controller_display(bpy.context, force=True)
    check(all(item.hide_get() for item in controllers),
          "controllers remain visible with no selected object")
    activate(target)
    return tuple(stage.name for stage in stages)


case("chained_creation_and_batch_edit", chained_creation_and_batch_edit)


def native_modifier_reorder_recovery():
    """A native stack reorder must rebuild chain ownership before evaluation."""
    vertices = []
    side_count = 8
    for ring in range(37):
        y = -3.0 + 6.0 * ring / 36.0
        for side in range(side_count):
            angle = math.tau * side / side_count
            vertices.append((0.65 * math.cos(angle), y,
                             0.65 * math.sin(angle)))
    target = make_object("SDH Native Modifier Reorder", vertices)
    check(
        bpy.ops.sdh.add_cage_chain(
            count=3, connection_mode="CHAINED", gap=0.2,
            auto_reconnect=True, sync_shared_end_scale=False,
            alignment="POS_Y", origin="BOTTOM",
        ) == {"FINISHED"},
        "native reorder chain creation failed",
    )
    stages = chain.chain_stages(target)
    original_order = tuple(stage.name for stage in stages)
    controllers = tuple(deform.find_controller(target, stage)
                        for stage in stages)
    check(len(stages) == 3 and all(controllers),
          "native reorder chain is incomplete")
    for index, controller in enumerate(controllers):
        properties = controller.sdh_cage_deform
        properties.bend_strength = math.radians(24.0 + index * 13.0)
        properties.twist_strength = 0.0
        properties.taper_factor = 0.0
        properties.stretch_factor = 0.0
        deform.sync_controller(controller, pull_transform=False)
    chain.reconnect_chain(target)

    # Move the original root with Blender's native operator, bypassing the
    # add-on's explicit stage-move operator. The runtime must restore the
    # persisted physical segment order rather than promoting the old root's
    # neighbor to the chain root.
    activate(target)
    target.modifiers.active = stages[0]
    check(
        bpy.ops.object.modifier_move_to_index(
            modifier=stages[0].name,
            index=len(tuple(target.modifiers)) - 1,
        ) == {"FINISHED"},
        "native modifier reorder failed",
    )
    reordered = chain.chain_stages(target)
    before = chain.validate_chain(target, chain.stage_chain_uuid(reordered[0]))
    check(before["index_mismatch"] and before["broken"],
          "native modifier reorder was not detected")

    # Reproduce the depsgraph event emitted by the native Modifier-panel
    # reorder.  The runtime handler must queue only this target's recoverable
    # order mismatch; the actual metadata writes stay in the safe timer path.
    deform.core._CHAIN_RECONNECT_QUEUE.clear()

    class _GeometryUpdate:
        id = target
        is_updated_transform = False
        is_updated_geometry = True
        is_updated_shading = False

    class _Depsgraph:
        updates = (_GeometryUpdate(),)

    deform.core._depsgraph_sync(None, _Depsgraph())
    chain_uuid = chain.stage_chain_uuid(reordered[0])
    queue_key = deform.core._chain_request_key(target, chain_uuid)
    check(queue_key in deform.core._CHAIN_RECONNECT_QUEUE,
          "depsgraph reorder did not queue chain recovery")
    check(deform.core._drain_chain_reconnect_queue() == 2,
          "queued reconnect did not recover a natively reordered chain")
    reordered = chain.chain_stages(target)
    check(tuple(stage.name for stage in reordered) == original_order,
          "native reorder accepted an unsafe chain segment swap")
    check(tuple(chain.stage_chain_index(stage) for stage in reordered) ==
          (0, 1, 2), "reconnect kept stale stage indices")
    check(tuple(bool(deform.modifier_input(stage, "Chain Root Stage"))
                for stage in reordered) == (True, False, False),
          "reconnect kept the stale root flag")
    check(tuple(bool(deform.modifier_input(stage, "Chain Tip Stage"))
                for stage in reordered) == (False, False, True),
          "reconnect kept the stale tip flag")
    check(abs(chain.stage_chain_gap(reordered[0])) < 1.0e-7,
          "reconnect retained an incoming gap on the new root")

    ordered_controllers = tuple(deform.find_controller(target, stage)
                                for stage in reordered)
    expected = []
    for source in vertices:
        point = Vector(source)
        eligible = True
        for controller in ordered_controllers:
            matrix = chain._stage_local_matrix(target, controller)
            local = matrix.inverted_safe() @ point
            domain_local = deform.core.chain_input_point_from_properties(
                local, controller.sdh_cage_deform)
            half_y = float(controller.sdh_cage_deform.size[1]) * 0.5
            next_eligible = (
                eligible and domain_local.y >= half_y - 1.0e-4)
            deformed = deform.deform_point_from_properties(
                local, controller.sdh_cage_deform, evaluator=True,
                chain_eligible=eligible,
            )
            point = matrix @ deformed
            eligible = next_eligible
        expected.append(point)
    actual = evaluated_points(target)
    maximum = max(
        ((actual_point - expected_point).length
         for actual_point, expected_point in zip(actual, expected)),
        default=0.0,
    )
    check(maximum < 5.0e-4,
          f"reordered chain differs from the recovered reference: {maximum}")
    return round(maximum, 7)


case("native_modifier_reorder_recovery", native_modifier_reorder_recovery)


def mirrored_chain_metadata_fallback():
    """Controller metadata must keep the GN domain alive after group repair."""
    target = make_object(
        "SDH Controller Metadata Fallback",
        ((-0.5, -2.0, -0.5), (0.5, -2.0, 0.5),
         (-0.5, 2.0, 0.5), (0.5, 2.0, -0.5)),
    )
    check(
        bpy.ops.sdh.add_cage_chain(
            count=2, connection_mode="CHAINED", gap=0.0,
            auto_reconnect=True, sync_shared_end_scale=False,
            alignment="POS_Y", origin="BOTTOM",
        ) == {"FINISHED"},
        "metadata fallback chain creation failed",
    )
    stages = chain.chain_stages(target)
    controllers = tuple(deform.find_controller(target, stage)
                        for stage in stages)
    check(len(stages) == 2 and all(controllers),
          "metadata fallback chain is incomplete")

    # Simulate a node-group copy/rebuild that retained the controller mirror
    # but briefly dropped the custom properties from each GeometryNodeTree.
    for stage in stages:
        group = stage.node_group
        for key in (
                chain.CHAIN_UUID, chain.CHAIN_INDEX, chain.CHAIN_COUNT,
                chain.CHAIN_MODE,
        ):
            if key in group:
                del group[key]

    for index, (stage, controller) in enumerate(zip(stages, controllers)):
        values = deform.core._chain_domain_input_values(controller, stage)
        expected_name = (
            f"{deform.core.CHAIN_DOMAIN_ATTRIBUTE_PREFIX}"
            f"{chain.stage_chain_uuid(stage).replace('-', '')}")
        check(values["Chain Domain Attribute"] == expected_name,
              "controller metadata did not restore the chain domain token")
        check(values["Chain Root Stage"] is (index == 0),
              "controller metadata restored the wrong root flag")
        check(values["Chain Tip Stage"] is (index == len(stages) - 1),
              "controller metadata restored the wrong tip flag")
        check(deform.core._managed_chain_mode(controller, stage) == "CHAINED",
              "controller metadata did not preserve the chained mode lock")
        deform.sync_controller(controller, pull_transform=False)
        check(deform.modifier_input(stage, "Chain Domain Attribute") ==
              expected_name,
              "sync_controller cleared the fallback chain domain input")
    return tuple(
        deform.modifier_input(stage, "Chain Domain Attribute")
        for stage in stages
    )


case("mirrored_chain_metadata_fallback", mirrored_chain_metadata_fallback)


def chain_origin_modes():
    vertices = (
        (-0.7, -3.0, -0.5), (0.7, -3.0, 0.5),
        (-0.8, 0.0, 0.6), (0.8, 0.0, -0.6),
        (-0.6, 3.0, -0.4), (0.6, 3.0, 0.4),
    )
    target = make_object("SDH Chained Origins", vertices)
    result = bpy.ops.sdh.add_cage_chain(
        count=3,
        connection_mode="CHAINED",
        gap=0.1,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        alignment="POS_Y",
        origin="BOTTOM",
    )
    check(result == {"FINISHED"}, "origin chain creation failed")
    stages = chain.chain_stages(target)
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    check(len(stages) == 3 and all(controllers),
          "origin chain did not create all controllers")
    values = {}
    for origin in ("BOTTOM", "TOP", "CENTER", "SYMMETRIC"):
        for controller in controllers:
            controller.sdh_cage_deform.origin = origin
            controller.sdh_cage_deform.bend_strength = math.radians(34.0)
            controller.sdh_cage_deform.twist_strength = math.radians(18.0)
            deform.sync_controller(controller, pull_transform=False)
        deform.core.flush_pending_chain_updates(target)
        check(all(controller.sdh_cage_deform.origin == origin
                  for controller in controllers),
              f"{origin} was normalized away from the chain")
        check(not chain.validate_chain(target, chain.stage_chain_uuid(stages[0]))["broken"],
              f"{origin} broke chain metadata")
        actual = evaluated_points(target)
        # The complete chain is checked for finite output and stable metadata;
        # each stage's local GN/reference parity is covered by the base cage
        # regression and the chained construction contract.
        check(all(all(math.isfinite(component) for component in point)
                  for point in actual), f"{origin} produced non-finite output")
        check(all(controller.sdh_cage_deform.origin == origin
                  for controller in controllers),
              f"{origin} changed while evaluating")
        values[origin] = tuple(tuple(round(component, 4) for component in point)
                               for point in actual)
    check(any(values["BOTTOM"] != values[origin]
              for origin in ("TOP", "CENTER", "SYMMETRIC")),
          "all chain Origin modes produced identical output")
    return tuple(values)


case("chain_origin_modes", chain_origin_modes)


def chain_origin_seam_continuity():
    target = make_object(
        "SDH Chain Origin Seams",
        ((-0.5, -3.0, -0.4), (0.5, -3.0, 0.4),
         (-0.5, 3.0, 0.4), (0.5, 3.0, -0.4)),
    )
    check(
        bpy.ops.sdh.add_cage_chain(
            count=3, connection_mode="CHAINED", gap=0.0,
            auto_reconnect=True, sync_shared_end_scale=True,
            alignment="POS_Y", origin="BOTTOM",
        ) == {"FINISHED"},
        "seam test chain creation failed",
    )
    stages = chain.chain_stages(target)
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    seams = {}
    for origin in ("BOTTOM", "TOP", "CENTER", "SYMMETRIC"):
        for controller in controllers:
            properties = controller.sdh_cage_deform
            properties.origin = origin
            properties.bend_strength = math.radians(48.0)
            properties.twist_strength = 0.0
            deform.sync_controller(controller, pull_transform=False)
        deform.core.flush_pending_chain_updates(target)
        errors = []
        for index in range(1, len(controllers)):
            previous_top, previous_x, _previous_y, previous_z = (
                chain._stage_top_frame(target, controllers[index - 1]))
            current = controllers[index]
            matrix = chain._stage_local_matrix(target, current)
            half = Vector(current.sdh_cage_deform.size) * 0.5
            samples = (
                (0.0, 0.0),
                (-half.x * 0.5, -half.z * 0.5),
                (-half.x * 0.5, half.z * 0.5),
                (half.x * 0.5, -half.z * 0.5),
                (half.x * 0.5, half.z * 0.5),
            )
            for sample_x, sample_z in samples:
                incoming = (
                    previous_top + previous_x * sample_x +
                    previous_z * sample_z)
                local = matrix.inverted_safe() @ incoming
                output = matrix @ deform.deform_point_from_properties(
                    local, current.sdh_cage_deform, evaluator=True,
                    chain_eligible=True)
                errors.append((output - incoming).length)
        seams[origin] = tuple(round(error, 6) for error in errors)
        check(all(error < 3.0e-4 for error in errors),
              f"{origin} chain seams are discontinuous: {errors!r}")
    return seams


case("chain_origin_seam_continuity", chain_origin_seam_continuity)


def dense_chain_geometry_matches_reference():
    vertices = []
    ring_count = 37
    side_count = 12
    for ring in range(ring_count):
        y = -3.0 + 6.0 * ring / (ring_count - 1)
        for side in range(side_count):
            angle = math.tau * side / side_count
            vertices.append((0.65 * math.cos(angle), y,
                             0.65 * math.sin(angle)))

    target = make_object("SDH Dense Chain Geometry", vertices)
    check(
        bpy.ops.sdh.add_cage_chain(
            count=3, connection_mode="CHAINED", gap=0.0,
            auto_reconnect=True, sync_shared_end_scale=True,
            alignment="POS_Y", origin="BOTTOM",
        ) == {"FINISHED"},
        "dense chain creation failed",
    )
    stages = chain.chain_stages(target)
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    check(len(stages) == 3 and all(controllers),
          "dense chain did not create three complete stages")

    results = {}
    for origin in ("BOTTOM", "TOP", "CENTER", "SYMMETRIC"):
        for controller in controllers:
            properties = controller.sdh_cage_deform
            properties.origin = origin
            properties.bend_strength = math.radians(42.0)
            properties.twist_strength = 0.0
            properties.taper_factor = 0.0
            properties.stretch_factor = 0.0
            deform.sync_controller(controller, pull_transform=False)
        deform.core.flush_pending_chain_updates(target)

        expected = []
        for source in vertices:
            point = Vector(source)
            eligible = True
            for controller in controllers:
                matrix = chain._stage_local_matrix(target, controller)
                local = matrix.inverted_safe() @ point
                domain_local = deform.core.chain_input_point_from_properties(
                    local, controller.sdh_cage_deform)
                half_y = float(controller.sdh_cage_deform.size[1]) * 0.5
                next_eligible = (
                    eligible and domain_local.y >= half_y - 1.0e-4)
                deformed = deform.deform_point_from_properties(
                    local,
                    controller.sdh_cage_deform,
                    evaluator=True,
                    chain_eligible=eligible,
                )
                point = matrix @ deformed
                eligible = next_eligible
            expected.append(point)

        actual = evaluated_points(target)
        errors = tuple((a - e).length for a, e in zip(actual, expected))
        maximum = max(errors, default=0.0)
        changed_rings = {
            index // side_count
            for index, (actual_point, source) in enumerate(zip(actual, vertices))
            if (actual_point - Vector(source)).length > 1.0e-3
        }
        check(maximum < 5.0e-4,
              f"{origin} dense chain differs from reference by {maximum}")
        check(len(changed_rings) >= ring_count - 2,
              f"{origin} deformed only {len(changed_rings)}/{ring_count} rings")
        results[origin] = (round(maximum, 7), len(changed_rings))
    return results


case("dense_chain_geometry_matches_reference",
     dense_chain_geometry_matches_reference)


def single_stage_continuation_low_topology():
    """A sparse mesh must still inherit an isolated middle-stage bend."""
    results = {}
    side_count = 8
    for ring_count in (4, 5, 7):
        vertices = []
        for ring in range(ring_count):
            y = -3.0 + 6.0 * ring / (ring_count - 1)
            for side in range(side_count):
                angle = math.tau * side / side_count
                vertices.append((0.65 * math.cos(angle), y,
                                 0.65 * math.sin(angle)))

        target = make_object(
            f"SDH Sparse Middle Stage {ring_count}", vertices)
        check(
            bpy.ops.sdh.add_cage_chain(
                count=3, connection_mode="CHAINED", gap=0.0,
                auto_reconnect=True, sync_shared_end_scale=True,
                alignment="POS_Y", origin="BOTTOM",
            ) == {"FINISHED"},
            f"sparse {ring_count}-ring chain creation failed",
        )
        stages = chain.chain_stages(target)
        controllers = tuple(deform.find_controller(target, stage)
                            for stage in stages)
        check(len(stages) == 3 and all(controllers),
              f"sparse {ring_count}-ring chain is incomplete")

        for controller in controllers:
            properties = controller.sdh_cage_deform
            properties.bend_strength = 0.0
            properties.twist_strength = 0.0
            properties.taper_factor = 0.0
            properties.stretch_factor = 0.0
            deform.sync_controller(controller, pull_transform=False)
        # This mirrors the reported interaction: only the middle cage bends.
        controllers[1].sdh_cage_deform.bend_strength = math.radians(58.0)
        deform.sync_controller(controllers[1], pull_transform=False)
        deform.core.flush_pending_chain_updates(target)

        expected = []
        for source in vertices:
            point = Vector(source)
            eligible = True
            for controller in controllers:
                matrix = chain._stage_local_matrix(target, controller)
                local = matrix.inverted_safe() @ point
                domain_local = deform.core.chain_input_point_from_properties(
                    local, controller.sdh_cage_deform)
                half_y = float(controller.sdh_cage_deform.size[1]) * 0.5
                next_eligible = (
                    eligible and domain_local.y >= half_y - 1.0e-4)
                deformed = deform.deform_point_from_properties(
                    local,
                    controller.sdh_cage_deform,
                    evaluator=True,
                    chain_eligible=eligible,
                )
                point = matrix @ deformed
                eligible = next_eligible
            expected.append(point)

        actual = evaluated_points(target)
        errors = tuple((a - e).length for a, e in zip(actual, expected))
        check(max(errors, default=0.0) < 5.0e-4,
              f"sparse {ring_count}-ring chain differs from reference")

        changed_rings = {
            index // side_count
            for index, (actual_point, source) in enumerate(zip(actual, vertices))
            if (actual_point - Vector(source)).length > 1.0e-3
        }
        # The prefix before the middle cage is intentionally unchanged, while
        # its top and the downstream suffix must inherit the bend.
        check(0 not in changed_rings,
              f"sparse {ring_count}-ring prefix was unexpectedly deformed")
        check(max(changed_rings, default=-1) == ring_count - 1,
              f"sparse {ring_count}-ring suffix did not inherit the bend")
        results[ring_count] = (round(max(errors, default=0.0), 7),
                               tuple(sorted(changed_rings)))
    return results


case("single_stage_continuation_low_topology",
     single_stage_continuation_low_topology)


def subdivide_preserves_authored_range():
    vertices = (
        (-0.5, -3.0, -0.5), (0.5, -3.0, 0.5),
        (-0.7, 0.0, 0.4), (0.7, 0.0, -0.4),
        (-0.5, 3.0, -0.5), (0.5, 3.0, 0.5),
    )
    target = make_object("SDH Subdivide Cage", vertices)
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target)
    properties = controller.sdh_cage_deform
    properties.origin = "BOTTOM"
    deform.core.set_deform_layers(
        properties, ("BEND", "TWIST", "TAPER"), bpy.context)
    properties.bend_strength = math.radians(90.0)
    properties.twist_strength = math.radians(60.0)
    properties.taper_factor = 0.45
    properties.top_scale = (1.4, 0.8)
    properties.bottom_scale = (0.9, 1.1)
    deform.sync_controller(controller, pull_transform=False)
    original_length = float(properties.size[1])
    original_bend = float(properties.bend_strength)
    original_twist = float(properties.twist_strength)

    target.modifiers.active = modifier
    result = bpy.ops.sdh.subdivide_cage_to_chain(
        count=3,
        gap=0.1,
        auto_reconnect=True,
        sync_shared_end_scale=True,
        allow_mixed_bend_approximation=True,
    )
    check(result == {"FINISHED"}, "subdivide-to-chain operator failed")
    stages = chain.chain_stages(target)
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    check(len(stages) == 3 and all(controllers),
          "subdivision did not create a complete 3-stage chain")
    total_domain = (
        sum(item.sdh_cage_deform.size[1] for item in controllers) +
        sum(chain.stage_chain_gap(stage) for stage in stages[1:])
    )
    check(abs(total_domain - original_length) < 3.0e-4,
          "subdivision changed the authored cage range")
    occupied_ratio = (
        sum(item.sdh_cage_deform.size[1] for item in controllers) /
        max(original_length, 1.0e-9)
    )
    # With an authored gap, the physical cage intervals cover less than the
    # original span.  Bend/Twist are distributed over those intervals; the
    # gap is a visual/ownership continuation and must not be counted as a
    # local stage angle.
    check(abs(sum(item.sdh_cage_deform.bend_strength for item in controllers) -
              original_bend * occupied_ratio) < 3.0e-4,
          "subdivision did not distribute the Bend angle over cage spans")
    check(abs(sum(item.sdh_cage_deform.twist_strength for item in controllers) -
              original_twist * occupied_ratio) < 3.0e-4,
          "subdivision did not distribute the Twist angle over cage spans")
    for index in range(1, len(controllers)):
        previous_top = controllers[index - 1].sdh_cage_deform.top_scale
        current_bottom = controllers[index].sdh_cage_deform.bottom_scale
        if chain.stage_chain_gap(stages[index]) <= 1.0e-6:
            check(close_vector(previous_top, current_bottom),
                  f"subdivision introduced a scale discontinuity at seam {index}")
        else:
            check(
                all(math.isfinite(float(value))
                    for value in (*previous_top, *current_bottom)),
                f"subdivision produced a non-finite gapped seam {index}")
    return total_domain


case("subdivide_preserves_authored_range", subdivide_preserves_authored_range)


def subdivide_preserves_profiled_cage_preview():
    target = make_object(
        "SDH Profiled Cage Preview",
        ((-0.6, -3.0, -0.4), (0.6, -3.0, 0.4),
         (-0.8, 0.0, 0.5), (0.8, 0.0, -0.5),
         (-0.6, 3.0, -0.4), (0.6, 3.0, 0.4)),
    )
    modifier, controller, _previous = deform.create_deform_stage(
        bpy.context, target)
    properties = controller.sdh_cage_deform
    properties.size = (2.0, 6.0, 2.0)
    properties.origin = "BOTTOM"
    deform.core.set_deform_layers(properties, ("BEND",), bpy.context)
    properties.bend_strength = math.radians(15.0)
    properties.bottom_scale = (0.75, 1.1)
    properties.top_scale = (1.55, 0.7)
    deform.sync_controller(controller, pull_transform=False)

    activate(target)
    target.modifiers.active = modifier
    check(
        bpy.ops.sdh.subdivide_cage_to_chain(
            count=3,
            gap=0.0,
            auto_reconnect=True,
            sync_shared_end_scale=True,
        ) == {"FINISHED"},
        "profiled cage subdivision failed",
    )
    deform.core.flush_pending_chain_updates(target)
    stages = tuple(chain.chain_stages(target))
    controllers = tuple(deform.find_controller(target, stage) for stage in stages)
    check(len(controllers) == 3 and all(controllers),
          "profiled subdivision did not create three cage previews")

    def preview_corner(item, side, x_sign, z_sign):
        stage_properties = item.sdh_cage_deform
        half = Vector(stage_properties.size) * 0.5
        state = deform.gizmos.cage_preview_geometry_state(stage_properties)
        # Exercise the same display path used by the viewport.  Calling the
        # raw evaluator here skips the chain-global profile baseline and
        # reports a seam that cannot occur in the drawn cage.
        local = deform.core.deform_point_for_display(
            (x_sign * half.x,
             half.y if side == "TOP" else -half.y,
             z_sign * half.z),
            stage_properties,
            preview_output_frame=state[1],
            chain_prefix_state=deform.core.chain_global_prefix_preview_state(
                stage_properties),
        )
        return deform.cage_local_matrix(target, item) @ Vector(local)

    maximum = 0.0
    for index in range(1, len(controllers)):
        for x_sign, z_sign in ((-1, -1), (-1, 1), (1, 1), (1, -1)):
            previous = preview_corner(
                controllers[index - 1], "TOP", x_sign, z_sign)
            current = preview_corner(
                controllers[index], "BOTTOM", x_sign, z_sign)
            maximum = max(maximum, (previous - current).length)
    check(maximum < 5.0e-4,
          f"profiled cage previews separate at a subdivided seam: {maximum}")
    return round(maximum, 7)


case("subdivide_preserves_profiled_cage_preview",
     subdivide_preserves_profiled_cage_preview)


def subdivides_mixed_bend_without_shape_correction():
    target = make_object(
        "SDH Mixed Bend Protection",
        ((-0.5, -2.0, -0.4), (0.5, -2.0, 0.4),
         (-0.6, 2.0, 0.4), (0.6, 2.0, -0.4)),
    )
    try:
        modifier, controller, _previous = deform.create_deform_stage(
            bpy.context, target)
        # This regression predates the +Z creation default and exercises a
        # source authored along Y. Keep its intended longitudinal axis
        # explicit; +Z coverage lives in chain_shared_scale_axis_regression.
        deform.core.fit_controller_to_alignment(
            bpy.context, target, modifier, controller, "POS_Y")
        properties = controller.sdh_cage_deform
        deform.core.set_deform_layers(
            properties, ("BEND", "TWIST"), bpy.context)
        properties.bend_strength = math.radians(35.0)
        properties.twist_strength = math.radians(20.0)
        deform.sync_controller(controller, pull_transform=False)
        before = evaluated_points(target)
        target.modifiers.active = modifier
        activate(target)
        result = bpy.ops.sdh.subdivide_cage_to_chain(
            count=2,
            gap=0.0,
            auto_reconnect=True,
            sync_shared_end_scale=True,
        )
        check(result == {"FINISHED"},
              "mixed Bend subdivision did not finish")
        after = evaluated_points(target)
        maximum = max(
            ((after_point - before_point).length
             for before_point, after_point in zip(before, after)),
            default=0.0,
        )
        # Blender evaluates Geometry Nodes in single precision.  The analytic
        # chain mapping keeps the residual below this bound without storing a
        # point-domain correction attribute on the source mesh.
        check(maximum < 3.0e-4,
              f"mixed Bend subdivision changed geometry by {maximum}")
        stages = tuple(chain.chain_stages(target))
        check(len(stages) == 2,
              "mixed subdivision did not create two chain stages")
        check(not any(
            str(attribute.name).startswith("SDH_CHAIN_CORRECTION_")
            for attribute in target.data.attributes
        ), "mixed subdivision wrote a legacy shape correction attribute")
        for stage in stages:
            check("_sdh_chain_correction_attribute" not in stage.node_group,
                  "stage retained a legacy correction attribute key")
            check("_sdh_chain_correction_active" not in stage.node_group,
                  "stage retained a legacy correction active key")
        return result
    finally:
        if target.name in bpy.data.objects:
            mesh = target.data
            bpy.data.objects.remove(target, do_unlink=True)
            if mesh is not None and mesh.name in bpy.data.meshes:
                bpy.data.meshes.remove(mesh)


case("subdivides_mixed_bend_without_shape_correction",
     subdivides_mixed_bend_without_shape_correction)


def subdivide_preserves_mixed_bend_geometry():
    vertices = []
    length = 6.0
    for ring in range(21):
        y = -length * 0.5 + length * ring / 20.0
        for side in range(7):
            phase = math.tau * side / 7.0
            vertices.append((
                0.12 + 0.55 * math.cos(phase),
                y,
                -0.07 + 0.38 * math.sin(phase),
            ))
    cases = tuple(
        (layers, origin, 5, 0.0)
        for layers in (
            ("BEND", "TWIST"), ("TWIST", "BEND"), ("BEND", "TAPER"))
        for origin in ("TOP", "CENTER", "SYMMETRIC")
    ) + (
        (("BEND", "TAPER"), "BOTTOM", 5, 0.4),
        (("BEND", "TWIST"), "SYMMETRIC", 3, 0.4),
        (("BEND", "TWIST"), "SYMMETRIC", 4, 0.4),
        (("BEND", "TWIST"), "SYMMETRIC", 2, 0.4),
    )
    reports = {}
    for layers, origin, count, gap in cases:
        label = f"{'+'.join(layers)} {origin} {count} gap={gap}"
        target = make_object(f"SDH Mixed Subdivision {label}", vertices)
        controllers = ()
        try:
            modifier, controller, _previous = deform.create_deform_stage(
                bpy.context, target)
            controllers = (controller,)
            properties = controller.sdh_cage_deform
            properties.size = (2.2, length, 1.8)
            properties.mode = "LIMITED"
            properties.origin = origin
            deform.core.set_deform_layers(properties, layers, bpy.context)
            properties.bend_strength = math.radians(74.0)
            properties.bend_direction = math.radians(23.0)
            properties.twist_strength = math.radians(-67.0)
            properties.taper_factor = 0.48
            properties.bottom_scale = (0.82, 1.08)
            properties.top_scale = (1.35, 0.76)
            properties.bottom_offset = (-0.22, 0.13)
            properties.top_offset = (0.37, -0.18)
            controller.location = (0.0, 0.0, 0.0)
            controller.rotation_euler = (0.0, 0.0, 0.0)
            deform.sync_controller(controller, pull_transform=False)
            before = evaluated_points(target)

            activate(target)
            target.modifiers.active = modifier
            check(
                bpy.ops.sdh.subdivide_cage_to_chain(
                    count=count,
                    gap=gap,
                    auto_reconnect=True,
                    sync_shared_end_scale=True,
                ) == {"FINISHED"},
                f"{label} subdivision failed",
            )
            deform.core.flush_pending_chain_updates(target)
            stages = tuple(chain.chain_stages(target))
            controllers = tuple(
                deform.find_controller(target, stage) for stage in stages)
            check(len(controllers) == count and all(controllers),
                  f"{label} produced an incomplete chain")
            after = evaluated_points(target)
            maximum = max(
                ((left - right).length
                 for left, right in zip(before, after)),
                default=0.0,
            )
            if gap <= 0.0:
                check(maximum < 4.0e-3,
                      f"{label} changed geometry by {maximum}")
            else:
                # A requested gap is now deliberately unowned. It cannot
                # preserve the source cage's continuously evaluated shape;
                # the dedicated gap-neutrality regression verifies the new
                # rigid-interval contract. Keep this matrix focused on valid,
                # finite mixed-stack subdivision and chain metadata.
                check(all(
                    math.isfinite(float(component))
                    for point in after for component in point
                ), f"{label} produced non-finite geometry")
            if origin == "SYMMETRIC" and count % 2 == 0 and gap > 0.0:
                gaps = tuple(chain.stage_chain_gap(stage) for stage in stages)
                check(gaps[count // 2] <= 1.0e-7,
                      f"{label} left a gap across the symmetric pivot")
                if count > 2:
                    check(any(value > 1.0e-6 for value in gaps[1:]),
                          f"{label} removed every non-pivot gap")
            reports[(layers, origin, count, gap)] = maximum
        finally:
            for item in controllers:
                if item is not None and item.name in bpy.data.objects:
                    bpy.data.objects.remove(item, do_unlink=True)
            if target.name in bpy.data.objects:
                mesh = target.data
                bpy.data.objects.remove(target, do_unlink=True)
                if mesh is not None and mesh.name in bpy.data.meshes:
                    bpy.data.meshes.remove(mesh)
    return reports


case("subdivide_preserves_mixed_bend_geometry",
     subdivide_preserves_mixed_bend_geometry)


def subdivide_preserves_origin_modes():
    results = {}
    for origin in ("TOP", "CENTER", "SYMMETRIC"):
        target = make_object(
            f"SDH Subdivide {origin}",
            ((-0.5, -2.0, -0.4), (0.5, -2.0, 0.4),
             (-0.6, 2.0, 0.4), (0.6, 2.0, -0.4)),
        )
        _modifier, controller, _previous = deform.create_deform_stage(
            bpy.context, target)
        properties = controller.sdh_cage_deform
        properties.origin = origin
        properties.bend_strength = math.radians(48.0)
        properties.twist_strength = math.radians(22.0)
        deform.sync_controller(controller, pull_transform=False)
        target.modifiers.active = _modifier
        check(
            bpy.ops.sdh.subdivide_cage_to_chain(
                count=2, gap=0.0, auto_reconnect=True,
                sync_shared_end_scale=True,
                allow_mixed_bend_approximation=True,
            ) == {"FINISHED"},
            f"{origin} subdivision failed",
        )
        stages = chain.chain_stages(target)
        controllers = tuple(deform.find_controller(target, stage) for stage in stages)
        check(len(stages) == 2 and all(controllers),
              f"{origin} subdivision did not create two stages")
        expected_origins = (
            ("BOTTOM", "BOTTOM") if origin == "SYMMETRIC" else
            (origin, origin)
        )
        actual_origins = tuple(
            item.sdh_cage_deform.origin for item in controllers)
        check(actual_origins == expected_origins,
              f"{origin} subdivision origins are {actual_origins!r}")
        if origin == "SYMMETRIC":
            expected_bends = (-24.0, 24.0)
            actual_bends = tuple(round(math.degrees(
                item.sdh_cage_deform.bend_strength), 4)
                for item in controllers)
            check(actual_bends == expected_bends,
                  f"symmetric subdivision bends are {actual_bends!r}")
        results[origin] = tuple(item.sdh_cage_deform.origin for item in controllers)
    return results


case("subdivide_preserves_origin_modes", subdivide_preserves_origin_modes)


def subdivide_preserves_bend_geometry_for_all_origins():
    angle = math.radians(96.0)
    direction = math.radians(17.0)
    length = 6.0
    radius = 0.6
    reports = {}
    for origin in ("BOTTOM", "TOP", "CENTER", "SYMMETRIC"):
        for count in (2, 3, 4, 5):
            vertices = []
            for ring in range(25):
                y = -length * 0.5 + length * ring / 24.0
                vertices.append((0.0, y, 0.0))
                for side in range(8):
                    phase = math.tau * side / 8.0
                    vertices.append((
                        radius * math.cos(phase), y,
                        radius * math.sin(phase),
                    ))
            target = make_object(
                f"SDH Subdivide Geometry {origin} {count}", vertices)
            controllers = ()
            try:
                modifier, controller, _previous = deform.create_deform_stage(
                    bpy.context, target)
                controllers = (controller,)
                properties = controller.sdh_cage_deform
                properties.size = (2.0, length, 2.0)
                properties.mode = "LIMITED"
                properties.origin = origin
                deform.core.set_deform_layers(
                    properties, ("BEND",), bpy.context)
                properties.bend_strength = angle
                properties.bend_direction = direction
                properties.bottom_scale = (1.0, 1.0)
                properties.top_scale = (1.0, 1.0)
                properties.bottom_offset = (0.0, 0.0)
                properties.top_offset = (0.0, 0.0)
                controller.location = (0.0, 0.0, 0.0)
                controller.rotation_euler = (0.0, 0.0, 0.0)
                deform.sync_controller(controller, pull_transform=False)
                before = evaluated_points(target)

                activate(target)
                target.modifiers.active = modifier
                check(
                    bpy.ops.sdh.subdivide_cage_to_chain(
                        count=count,
                        gap=0.0,
                        auto_reconnect=True,
                        sync_shared_end_scale=True,
                    ) == {"FINISHED"},
                    f"{origin} {count}-stage subdivision failed",
                )
                deform.core.flush_pending_chain_updates(target)
                stages = chain.chain_stages(target)
                controllers = tuple(
                    deform.find_controller(target, stage) for stage in stages)
                check(len(controllers) == count and all(controllers),
                      f"{origin} {count}-stage chain is incomplete")
                after = evaluated_points(target)
                maximum = max(
                    ((left - right).length
                     for left, right in zip(before, after)),
                    default=0.0,
                )
                check(
                    maximum < 4.0e-3,
                    f"{origin} {count}-stage subdivision moved geometry: "
                    f"{maximum}",
                )
                reports[(origin, count)] = maximum
            finally:
                for controller in controllers:
                    if (
                            controller is not None and
                            controller.name in bpy.data.objects
                    ):
                        bpy.data.objects.remove(controller, do_unlink=True)
                if target.name in bpy.data.objects:
                    mesh = target.data
                    bpy.data.objects.remove(target, do_unlink=True)
                    if mesh is not None and mesh.name in bpy.data.meshes:
                        bpy.data.meshes.remove(mesh)
    return reports


case(
    "subdivide_preserves_bend_geometry_for_all_origins",
    subdivide_preserves_bend_geometry_for_all_origins,
)


def root_boundary_gizmo_exit_flushes_chain():
    """Closing a root boundary drag must commit downstream chain metadata."""
    target = make_object(
        "SDH Root Boundary Exit Flush",
        ((-0.6, -3.0, -0.5), (0.6, -3.0, 0.5),
         (-0.7, 3.0, 0.5), (0.7, 3.0, -0.5)),
    )
    check(
        bpy.ops.sdh.add_cage_chain(
            count=3,
            connection_mode="CHAINED",
            gap=0.15,
            auto_reconnect=True,
            sync_shared_end_scale=True,
            alignment="POS_Y",
            origin="CENTER",
        ) == {"FINISHED"},
        "root boundary flush chain creation failed",
    )
    stages = chain.chain_stages(target)
    controllers = tuple(
        deform.find_controller(target, stage) for stage in stages)
    check(len(stages) == 3 and all(controllers),
          "root boundary flush chain is incomplete")
    root = controllers[0]
    properties = root.sdh_cage_deform
    properties.bend_strength = math.radians(55.0)
    deform.sync_controller(root, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)

    source_start_before = float(
        deform.modifier_input(stages[1], "Chain Source Start"))
    initial_size = tuple(properties.size)
    initial_location = tuple(root.location)
    applied, _new_length = deform.move_cage_boundary(
        root,
        "BOTTOM",
        0.3,
        initial_size,
        initial_location,
        None,
    )
    check(abs(applied - 0.3) < 1.0e-5,
          "root boundary test drag was clamped")
    check(bool(deform.core._CHAIN_RECONNECT_QUEUE),
          "root boundary edit did not queue its downstream refresh")
    source_start_stale = float(
        deform.modifier_input(stages[1], "Chain Source Start"))
    check(abs(source_start_stale - source_start_before) < 1.0e-6,
          "root boundary metadata refreshed before the Gizmo exit contract")

    gizmo = SimpleNamespace(
        invoke_target=target,
        invoke_controller=root,
        side="BOTTOM",
    )
    context = SimpleNamespace(area=None)
    deform.SDHCageBoundaryGizmo.exit(gizmo, context, False)

    check(not deform.core._CHAIN_RECONNECT_QUEUE,
          "root boundary Gizmo exit left a pending chain refresh")
    source_start_after = float(
        deform.modifier_input(stages[1], "Chain Source Start"))
    check(abs(source_start_after - source_start_before) > 1.0e-4,
          "root boundary Gizmo exit left downstream metadata stale")
    stable_state = tuple(
        float(deform.modifier_input(stage, "Chain Source Start"))
        for stage in stages)
    deform.core.flush_pending_chain_updates(target)
    check(stable_state == tuple(
        float(deform.modifier_input(stage, "Chain Source Start"))
        for stage in stages),
        "a second interaction still changed the committed chain state")
    return tuple(round(value, 6) for value in stable_state)


case("root_boundary_gizmo_exit_flushes_chain",
     root_boundary_gizmo_exit_flushes_chain)


def root_end_offset_update_flushes_chain():
    """Direct end-offset RNA edits commit downstream chain frames immediately."""
    target = make_object(
        "SDH Root End Offset Update",
        ((-0.6, -3.0, -0.5), (0.6, -3.0, 0.5),
         (-0.7, 3.0, 0.5), (0.7, 3.0, -0.5)),
    )
    check(
        bpy.ops.sdh.add_cage_chain(
            count=3,
            connection_mode="CHAINED",
            gap=0.15,
            auto_reconnect=True,
            sync_shared_end_scale=True,
            alignment="POS_Y",
            origin="CENTER",
        ) == {"FINISHED"},
        "root end-offset chain creation failed",
    )
    stages = chain.chain_stages(target)
    controllers = tuple(
        deform.find_controller(target, stage) for stage in stages)
    check(len(stages) == 3 and all(controllers),
          "root end-offset chain is incomplete")
    root = controllers[0]
    properties = root.sdh_cage_deform
    properties.bend_strength = math.radians(55.0)
    deform.sync_controller(root, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    before = tuple(controllers[1].location)
    properties.top_offset = (0.3, 0.0)
    after = tuple(controllers[1].location)
    check(not deform.core._CHAIN_RECONNECT_QUEUE,
          "direct root end-offset edit left a pending chain refresh")
    check((Vector(after) - Vector(before)).length > 1.0e-4,
          "direct root end-offset edit left the next cage frame stale")
    properties.top_offset = (0.0, 0.0)
    deform.core.flush_pending_chain_updates(target)
    return tuple(round(value, 6) for value in after)


case("root_end_offset_update_flushes_chain",
     root_end_offset_update_flushes_chain)


def root_end_scale_update_refreshes_entire_chain():
    """A shared root end-scale edit must settle every downstream stage."""
    vertices = []
    for ring in range(25):
        y = -3.0 + 6.0 * ring / 24.0
        for side in range(8):
            angle = math.tau * side / 8.0
            vertices.append((
                0.65 * math.cos(angle), y, 0.65 * math.sin(angle)))
    target = make_object("SDH Root End Scale Update", vertices)
    check(
        bpy.ops.sdh.add_cage_chain(
            count=3,
            connection_mode="CHAINED",
            gap=0.15,
            auto_reconnect=True,
            sync_shared_end_scale=True,
            alignment="POS_Y",
            origin="CENTER",
        ) == {"FINISHED"},
        "root end-scale chain creation failed",
    )
    stages = chain.chain_stages(target)
    controllers = tuple(
        deform.find_controller(target, stage) for stage in stages)
    check(len(stages) == 3 and all(controllers),
          "root end-scale chain is incomplete")
    for controller, angle in zip(
            controllers, (math.radians(48.0), math.radians(-31.0), 0.0)):
        properties = controller.sdh_cage_deform
        properties.bend_strength = angle
        deform.sync_controller(controller, pull_transform=False)
    deform.core.flush_pending_chain_updates(target)

    root = controllers[0]
    root.sdh_cage_deform.top_scale = (1.6, 0.65)
    immediate = evaluated_points(target)
    immediate_frame = tuple(
        tuple(deform.modifier_input(stages[2], name))
        for name in (
            "Chain Input Pivot", "Chain Input Inverse X",
            "Chain Input Inverse Y", "Chain Input Inverse Z",
            "Chain Output Offset", "Chain Output X",
            "Chain Output Y", "Chain Output Z",
        )
    )

    # This is the formerly required second interaction on the visibly
    # affected cage. It must be a no-op after the root scale callback returns.
    deform.sync_controller(controllers[2], pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    settled = evaluated_points(target)
    settled_frame = tuple(
        tuple(deform.modifier_input(stages[2], name))
        for name in (
            "Chain Input Pivot", "Chain Input Inverse X",
            "Chain Input Inverse Y", "Chain Input Inverse Z",
            "Chain Output Offset", "Chain Output X",
            "Chain Output Y", "Chain Output Z",
        )
    )
    maximum = max(
        ((after - before).length
         for before, after in zip(immediate, settled)),
        default=0.0,
    )
    frame_error = max(
        ((Vector(after) - Vector(before)).length
         for before, after in zip(immediate_frame, settled_frame)),
        default=0.0,
    )
    check(maximum < 5.0e-4,
          f"root end-scale edit left downstream geometry stale: {maximum}")
    check(frame_error < 5.0e-5,
          f"root end-scale edit left downstream frames stale: {frame_error}")
    check(not deform.core._CHAIN_RECONNECT_QUEUE,
          "root end-scale edit left a pending chain refresh")

    # A later seam edit must absorb an older upstream request instead of
    # briefly propagating from the stale upstream frame.
    root.sdh_cage_deform.bend_strength += math.radians(7.0)
    check(bool(deform.core._CHAIN_RECONNECT_QUEUE),
          "upstream edit did not create the pending-frame fixture")
    controllers[1].sdh_cage_deform.top_scale = (1.25, 0.8)
    queued_immediate = evaluated_points(target)
    queued_frame = tuple(
        tuple(deform.modifier_input(stages[2], name))
        for name in (
            "Chain Input Pivot", "Chain Input Inverse X",
            "Chain Input Inverse Y", "Chain Input Inverse Z",
            "Chain Output Offset", "Chain Output X",
            "Chain Output Y", "Chain Output Z",
        )
    )
    check(not deform.core._CHAIN_RECONNECT_QUEUE,
          "shared scale did not consume the older upstream chain request")
    deform.sync_controller(controllers[2], pull_transform=False)
    deform.core.flush_pending_chain_updates(target)
    queued_settled = evaluated_points(target)
    settled_queued_frame = tuple(
        tuple(deform.modifier_input(stages[2], name))
        for name in (
            "Chain Input Pivot", "Chain Input Inverse X",
            "Chain Input Inverse Y", "Chain Input Inverse Z",
            "Chain Output Offset", "Chain Output X",
            "Chain Output Y", "Chain Output Z",
        )
    )
    queued_maximum = max(
        ((after - before).length
         for before, after in zip(queued_immediate, queued_settled)),
        default=0.0,
    )
    queued_frame_error = max(
        ((Vector(after) - Vector(before)).length
         for before, after in zip(queued_frame, settled_queued_frame)),
        default=0.0,
    )
    check(queued_maximum < 5.0e-4,
          f"shared scale left queued upstream geometry stale: {queued_maximum}")
    check(queued_frame_error < 5.0e-5,
          f"shared scale left queued upstream frames stale: {queued_frame_error}")
    return (
        round(max(maximum, queued_maximum), 7),
        round(max(frame_error, queued_frame_error), 7),
    )


case("root_end_scale_update_refreshes_entire_chain",
     root_end_scale_update_refreshes_entire_chain)


try:
    addon.unregister()
    check(not hasattr(bpy.types.Object, "sdh_cage_deform"),
          "cage properties survived unregister")
finally:
    if hasattr(bpy.types.Object, "sdh_cage_deform"):
        addon.unregister()
    bpy.context.preferences.addons.remove(entry)

if failures:
    print(f"SDH_CHAIN::SUMMARY::FAIL::{failures!r}")
    raise SystemExit(1)
print("SDH_CHAIN::SUMMARY::PASS")
