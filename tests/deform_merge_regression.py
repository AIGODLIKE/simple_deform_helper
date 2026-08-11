"""Blender runtime regression for the live multi-object deform merge."""
from __future__ import annotations

import importlib
import math
import os
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
PACKAGE = os.environ.get("SDH_TEST_MODULE", PACKAGE)
sys.path.insert(0, str(SOURCE.parent))
failures = []


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def case(name, function):
    try:
        value = function()
    except Exception as error:
        failures.append((name, type(error).__name__, str(error)))
        print(f"SDH_MERGE::{name}::FAIL::{type(error).__name__}::{error}")
        traceback.print_exc()
    else:
        print(f"SDH_MERGE::{name}::PASS::{value!r}")


def activate_many(objects, active):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


def cube_source(name, location):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    return obj


def curve_source(name, location):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.bevel_depth = 0.2
    curve.bevel_resolution = 1
    spline = curve.splines.new("POLY")
    spline.points.add(1)
    spline.points[0].co = (0.0, 0.0, -1.0, 1.0)
    spline.points[1].co = (0.0, 0.0, 1.0, 1.0)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    return obj


def evaluated_snapshot(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.data
    xs = tuple(vertex.co.x for vertex in mesh.vertices)
    return evaluated, len(mesh.vertices), (min(xs), max(xs)) if xs else (0.0, 0.0)


def evaluated_mesh_signature(obj):
    """Return stable world-space points and face count for evaluated geometry."""
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        points = tuple(sorted({
            tuple(round(value, 5) for value in (matrix @ vertex.co))
            for vertex in mesh.vertices
        }))
        return points, len(mesh.polygons)
    finally:
        evaluated.to_mesh_clear()


def evaluated_source_signature(merge, source_index):
    """Return the final points/faces belonging to one tagged merged source."""
    bpy.context.view_layer.update()
    evaluated = merge.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        attribute = mesh.attributes.get(merge_module.SOURCE_INDEX_ATTRIBUTE)
        check(attribute is not None and attribute.domain == "FACE",
              "final merged geometry lost its source index attribute")
        polygons = tuple(
            polygon for polygon, item in zip(mesh.polygons, attribute.data)
            if int(item.value) == source_index
        )
        used_vertices = {
            vertex_index
            for polygon in polygons
            for vertex_index in polygon.vertices
        }
        matrix = evaluated.matrix_world
        points = tuple(sorted({
            tuple(round(value, 5) for value in (
                matrix @ mesh.vertices[vertex_index].co))
            for vertex_index in used_vertices
        }))
        return points, len(polygons)
    finally:
        evaluated.to_mesh_clear()


def source_preview(entry):
    preview = getattr(entry, "final_preview", None)
    check(preview is not None, "active source has no final-state preview")
    check(preview.name in bpy.data.objects,
          "active source preview is not linked to Blender data")
    check(preview.get(merge_module.SOURCE_PREVIEW_MARKER, False),
          "active source preview is missing its runtime marker")
    return preview


def marked_source_previews():
    return tuple(
        obj for obj in bpy.data.objects
        if obj.get(merge_module.SOURCE_PREVIEW_MARKER, False)
    )


addon_entry = bpy.context.preferences.addons.new()
addon_entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
registered_here = not hasattr(bpy.types.Object, "sdh_deform_merge_sources")
if registered_here:
    addon.register()
merge_module = importlib.import_module(f"{PACKAGE}.cage_deform.merge")
core_module = importlib.import_module(f"{PACKAGE}.cage_deform.core")

mesh_source = cube_source("Merge Cube", (-2.0, 0.0, 0.0))
curve = curve_source("Merge Curve", (2.0, 0.0, 0.0))
activate_many((mesh_source, curve), mesh_source)


def create_and_evaluate():
    check(bpy.ops.sdh.create_deform_merge() == {"FINISHED"},
          "merge operator failed")
    merge = bpy.context.object
    check(merge_module.is_deform_merge(merge), "active object is not a merge")
    sources = merge_module.live_merge_sources(merge)
    check(len(sources) == 2, f"expected two sources, got {len(sources)}")
    check(hasattr(bpy.types, "SDH_UL_merge_sources"),
          "merged source UIList was not registered")
    check(merge.sdh_deform_merge_active_source_index == 0,
          "merged source list did not start at its first row")
    # UIList RNA classes cannot be instantiated with a normal Python call in
    # background mode; exercise the filter method with its documented bitflag.
    ui_list = SimpleNamespace(bitflag_filter_item=1 << 30)
    flags, _ = merge_module.SDH_UL_merge_sources.filter_items(
        ui_list, bpy.context, merge, "sdh_deform_merge_sources")
    check(len(flags) == len(sources) and all(
        flag & ui_list.bitflag_filter_item for flag in flags),
        "valid merged source rows were filtered out")
    check(all(source.type == "MESH" for _index, _entry, source in sources),
          "non-mesh source was not converted")
    check(all(source.hide_get() for _index, _entry, source in sources),
          "merged sources remain visible")
    check(all(source.sdh_deform_merge_owner == merge
              for _index, _entry, source in sources),
          "source owner pointer is missing")
    evaluated, vertex_count, x_bounds = evaluated_snapshot(merge)
    check(vertex_count > 8, "merged evaluated geometry is incomplete")
    check(x_bounds[0] < -2.9 and x_bounds[1] > 1.7,
          f"source transforms were not preserved: {x_bounds}")
    attribute = evaluated.data.attributes.get(
        merge_module.SOURCE_INDEX_ATTRIBUTE)
    check(attribute is not None and attribute.domain == "FACE",
          "source index face attribute is missing")
    values = {int(item.value) for item in attribute.data}
    check(values == {0, 1}, f"source index values are wrong: {values}")
    return merge.name, vertex_count, x_bounds


case("create_and_evaluate", create_and_evaluate)
merge = bpy.context.object


def source_modifiers_update_merge():
    source = merge_module.live_merge_sources(merge)[0][2]
    _evaluated, before, _bounds = evaluated_snapshot(merge)
    array = source.modifiers.new("Merge Source Array", "ARRAY")
    array.count = 2
    array.relative_offset_displace = (0.0, 2.0, 0.0)
    _evaluated, after, _bounds = evaluated_snapshot(merge)
    check(after > before, f"source modifier did not update merge: {before} -> {after}")
    return before, after


case("source_modifiers_update_merge", source_modifiers_update_merge)

cage_state = {}


def source_identity_survives_cage():
    core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
    modifier, controller, _previous = core.create_deform_stage(
        bpy.context, merge)
    cage_state["core"] = core
    cage_state["modifier"] = modifier
    cage_state["controller"] = controller
    merge.modifiers.active = modifier
    controller.sdh_cage_deform.bend_strength = 0.0
    evaluated, _count, _bounds = evaluated_snapshot(merge)
    attribute = evaluated.data.attributes.get(
        merge_module.SOURCE_INDEX_ATTRIBUTE)
    check(attribute is not None, "cage stage removed source identity")
    values = {int(item.value) for item in attribute.data}
    check(values == {0, 1}, f"cage stage changed source identity: {values}")
    hit, _location, _normal, face_index = evaluated.ray_cast(
        (-2.0, 0.0, 10.0), (0.0, 0.0, -1.0))
    check(hit, "evaluated merged cube was not ray-castable")
    check(merge_module._source_index_from_hit(evaluated, face_index) == 0,
          "ray hit did not resolve the cube source")
    return modifier.name, face_index


case("source_identity_survives_cage", source_identity_survives_cage)


def final_state_preview_tracks_merged_stack():
    source_index = 0
    entry = merge.sdh_deform_merge_sources[source_index]
    source = entry.object
    controller = cage_state["controller"]
    properties = controller.sdh_cage_deform
    properties.bend_strength = math.radians(55.0)
    cage_state["core"].sync_controller(controller, pull_transform=False)
    source_points, _source_faces = evaluated_mesh_signature(source)

    check(merge_module.enter_source_edit(bpy.context, merge, source_index),
          "could not enter source edit for final-state preview")
    preview = source_preview(entry)
    preview_points, preview_faces = evaluated_mesh_signature(preview)
    expected_points, expected_faces = evaluated_source_signature(
        merge, source_index)
    check(preview_faces == expected_faces,
          f"preview contains geometry outside the active source: "
          f"{preview_faces} != {expected_faces}")
    check(preview_points == expected_points,
          "preview geometry does not match the active source's final state")
    check(preview_points != source_points,
          "preview shows the undeformed source instead of the final merged state")
    check(len(marked_source_previews()) == 1,
          "source editing created more than one final-state preview")
    check(all(
        index == source_index or getattr(candidate, "final_preview", None) is None
        for index, candidate, _source in merge_module.live_merge_sources(merge)
    ), "an inactive source retained a final-state preview")

    source_attribute = preview.data.attributes.get(
        merge_module.SOURCE_INDEX_ATTRIBUTE)
    if source_attribute is not None:
        values = {int(item.value) for item in source_attribute.data}
        check(values == {source_index},
              f"preview retained faces from another source: {values}")

    triangulate = merge.modifiers.new(
        "Final Preview Refresh", "TRIANGULATE")
    bpy.context.view_layer.update()
    refresh_preview = getattr(merge_module, "refresh_final_preview", None)
    check(callable(refresh_preview),
          "final-state preview has no deterministic refresh API")
    refresh_preview(bpy.context, merge, source_index)
    refreshed = source_preview(entry)
    refreshed_points, refreshed_faces = evaluated_mesh_signature(refreshed)
    expected_refreshed_points, expected_refreshed_faces = (
        evaluated_source_signature(merge, source_index))
    check(refreshed_faces == expected_refreshed_faces,
          "preview did not refresh to the final modifier-stack geometry")
    check(refreshed_points == expected_refreshed_points,
          "refreshed preview points do not match the final merged result")
    check(refreshed_faces > preview_faces,
          "test modifier changed the merge but not the active source preview")
    check(triangulate in merge.modifiers[:],
          "preview refresh unexpectedly removed the test modifier")
    return preview_faces, refreshed_faces


case("final_state_preview_tracks_merged_stack",
     final_state_preview_tracks_merged_stack)


def unrelated_scene_updates_do_not_queue_preview():
    """Lighting/camera edits must not rebuild an active source preview."""
    merge_module._preview_pending.clear()
    light_data = bpy.data.lights.new("SDH Unrelated Light", type="POINT")
    light = bpy.data.objects.new("SDH Unrelated Light", light_data)
    bpy.context.scene.collection.objects.link(light)
    merge_module._preview_pending.clear()
    bpy.context.view_layer.update()
    check(not merge_module._preview_pending,
          "an unrelated scene object queued the source preview")
    bpy.data.objects.remove(light, do_unlink=True)
    bpy.data.lights.remove(light_data)
    return "unrelated scene updates ignored"


case("unrelated_scene_updates_do_not_queue_preview",
     unrelated_scene_updates_do_not_queue_preview)


def unchanged_scene_does_not_queue_preview():
    merge_module._preview_pending.clear()
    bpy.context.view_layer.update()
    check(not merge_module._preview_pending,
          "an unchanged dependency graph queued the source preview")
    return "unchanged graph ignored"


case("unchanged_scene_does_not_queue_preview",
     unchanged_scene_does_not_queue_preview)


def return_cleans_final_state_preview():
    entry = merge.sdh_deform_merge_sources[0]
    preview = source_preview(entry)
    preview_name = preview.name
    preview_mesh_name = preview.data.name
    check(merge_module.return_to_merge(bpy.context, merge),
          "could not return after final-state preview")
    check(getattr(entry, "final_preview", None) is None,
          "returning to the merge kept the preview pointer")
    check(bpy.data.objects.get(preview_name) is None,
          "returning to the merge kept the preview object")
    check(bpy.data.meshes.get(preview_mesh_name) is None,
          "returning to the merge kept the preview mesh")
    check(not marked_source_previews(),
          "returning to the merge kept a marked preview object")
    return preview_name


case("return_cleans_final_state_preview", return_cleans_final_state_preview)


def add_cage_to_final_source_is_scoped():
    core = cage_state["core"]
    source_index = 1
    source = merge.sdh_deform_merge_sources[source_index].object
    other_index = 0
    check(merge_module.enter_source_edit(bpy.context, merge, source_index),
          "could not enter source edit before adding a final-source cage")
    source_preview(merge.sdh_deform_merge_sources[source_index])
    expected_bounds = merge_module.evaluated_source_bounds(
        bpy.context, merge, source_index)
    selected_before, selected_faces = evaluated_source_signature(
        merge, source_index)
    other_before, other_faces = evaluated_source_signature(merge, other_index)
    merge_before = len(core.cage_modifiers(merge))
    source_before = len(core.cage_modifiers(source))
    result = bpy.ops.sdh.add_cage_to_merge_result()
    check(result == {"FINISHED"},
          f"add-cage-to-final-source operator failed: {result}")
    check(len(core.cage_modifiers(merge)) == merge_before + 1,
          "final-source cage stage was not added after the merge stack")
    check(len(core.cage_modifiers(source)) == source_before,
          "final-source cage was incorrectly added before the merge stack")
    new_modifier = core.cage_modifiers(merge)[-1]
    new_controller = core.find_controller(merge, new_modifier)
    check(new_controller is not None and new_controller.parent == merge,
          "final-source cage controller is not owned by the merge container")
    node_group = new_modifier.node_group
    check(node_group.get(merge_module.FINAL_SOURCE_STAGE_MARKER, False),
          "final-source cage is missing its source filter marker")
    check(int(node_group.get(merge_module.FINAL_SOURCE_INDEX, -1)) == source_index,
          "final-source cage stored the wrong source index")
    set_position = next(
        node for node in node_group.nodes
        if node.bl_idname == "GeometryNodeSetPosition")
    check(set_position.inputs["Selection"].is_linked,
          "final-source cage does not filter Set Position")
    expected_center = (expected_bounds[0] + expected_bounds[1]) * 0.5
    check((new_controller.location - expected_center).length < 1.0e-4,
          "final-source cage was not fitted to the selected final geometry")
    core.fit_controller(bpy.context, merge, new_modifier, new_controller)
    check((new_controller.location - expected_center).length < 1.0e-4,
          "refitting a final-source cage used the whole merged bounds")
    selected_after, selected_after_faces = evaluated_source_signature(
        merge, source_index)
    other_after, other_after_faces = evaluated_source_signature(
        merge, other_index)
    check(selected_after_faces == selected_faces and
          selected_after != selected_before,
          "final-source cage did not deform the selected source")
    check(other_after_faces == other_faces and other_after == other_before,
          "final-source cage changed another merged source")
    check(not marked_source_previews(),
          "adding a final-source cage kept the source-edit preview")
    return new_modifier.name


case("add_cage_to_final_source_is_scoped",
     add_cage_to_final_source_is_scoped)


def source_edit_round_trip():
    source = merge_module.live_merge_sources(merge)[1][2]
    check(merge_module.enter_source_edit(bpy.context, merge, 1),
          "could not enter source edit")
    check(merge.sdh_deform_merge_active_source_index == 1,
          "source list active row did not follow source editing")
    check(bpy.context.object == source and source.select_get(),
          "source was not selected")
    check(not source.hide_get() and source.display_type == "WIRE" and
          source.show_in_front, "source edit display is wrong")
    check(merge_module.return_to_merge(bpy.context, merge),
          "could not return to merge")
    check(bpy.context.object == merge and source.hide_get(),
          "source was not hidden after returning")
    return source.name


case("source_edit_round_trip", source_edit_round_trip)


def release_restores_sources():
    merge_name = merge.name
    sources = tuple(source for _index, _entry, source
                    in merge_module.live_merge_sources(merge))
    check(merge_module.enter_source_edit(bpy.context, merge, 0),
          "could not enter source edit before release cleanup")
    preview = source_preview(merge.sdh_deform_merge_sources[0])
    preview_name = preview.name
    preview_mesh_name = preview.data.name
    check(merge_module.release_deform_merge(bpy.context, merge),
          "release failed")
    check(bpy.data.objects.get(merge_name) is None, "merge object survived")
    check(bpy.data.objects.get(preview_name) is None,
          "release kept the final-state preview object")
    check(bpy.data.meshes.get(preview_mesh_name) is None,
          "release kept the final-state preview mesh")
    check(not marked_source_previews(),
          "release kept a marked final-state preview")
    check(all(not source.hide_get() for source in sources),
          "source visibility was not restored")
    check(all(source.sdh_deform_merge_owner is None for source in sources),
          "source owner pointer survived")
    return tuple(source.name for source in sources)


case("release_restores_sources", release_restores_sources)


def uv_layers_survive_merge_round_trip():
    """Each source keeps its displayed UV set through a live merge."""
    first = cube_source("UV Merge First", (-3.0, 0.0, 0.0))
    second = cube_source("UV Merge Second", (3.0, 0.0, 0.0))

    def author_uv(obj, name, value):
        layers = obj.data.uv_layers
        layer = layers.new(name=name, do_init=False)
        for loop in layer.data:
            loop.uv = value
        layers.active_index = next(
            index for index, candidate in enumerate(layers)
            if candidate.name == name)
        if hasattr(layers, "active_render_index"):
            layers.active_render_index = layers.active_index
        else:
            for candidate in layers:
                candidate.active_render = candidate.name == name

    author_uv(first, "UV Source First", (0.17, 0.23))
    author_uv(second, "UV Source Second", (0.71, 0.83))
    activate_many((first, second), first)
    check(bpy.ops.sdh.create_deform_merge() == {"FINISHED"},
          "UV merge operator failed")
    merge = bpy.context.object
    entries = tuple(merge.sdh_deform_merge_sources)
    check(len(entries) == 2, "UV merge did not keep both sources")
    common_name = entries[0].merge_uv_name
    check(common_name and all(entry.merge_uv_name == common_name for entry in entries),
          "sources do not share one generated merge UV layer")
    evaluated = merge.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        uv = mesh.uv_layers.get(common_name)
        attribute = mesh.attributes.get(merge_module.SOURCE_INDEX_ATTRIBUTE)
        check(uv is not None and attribute is not None,
              "merged evaluated mesh lost its common UV/source attributes")
        values = {0: [], 1: []}
        for polygon, source_item in zip(mesh.polygons, attribute.data):
            source_index = int(source_item.value)
            values[source_index].extend(
                tuple(round(component, 3) for component in uv.data[loop_index].uv)
                for loop_index in polygon.loop_indices)
        check(set(values[0]) == {(0.17, 0.23)},
              f"first source UVs changed in merged result: {set(values[0])}")
        check(set(values[1]) == {(0.71, 0.83)},
              f"second source UVs changed in merged result: {set(values[1])}")
    finally:
        evaluated.to_mesh_clear()
    check(merge_module.release_deform_merge(bpy.context, merge),
          "UV merge release failed")
    for obj, name in ((first, "UV Source First"), (second, "UV Source Second")):
        check(obj.data.uv_layers.get(name) is not None,
              f"{obj.name} lost its original UV layer")
        check(merge_module._uv_layer_name(obj.data) == name and
              merge_module._uv_layer_name(obj.data, render=True) == name,
              f"{obj.name} did not restore active/render UV selection")
        check(obj.data.uv_layers.get(common_name) is None,
              f"{obj.name} kept temporary merge UV layer")
        bpy.data.objects.remove(obj, do_unlink=True)
    return common_name


case("uv_layers_survive_merge_round_trip", uv_layers_survive_merge_round_trip)


def collection_merge_recurses_and_samples_sources():
    parent = bpy.data.collections.new("SDH Merge Parent Collection")
    child = bpy.data.collections.new("SDH Merge Child Collection")
    bpy.context.scene.collection.children.link(parent)
    parent.children.link(child)
    first = cube_source("Collection Merge First", (0.0, -3.0, 0.0))
    second = cube_source("Collection Merge Second", (0.0, 3.0, 0.0))

    def move_to(obj, collection):
        for owner in tuple(obj.users_collection):
            owner.objects.unlink(obj)
        collection.objects.link(obj)

    move_to(first, parent)
    move_to(second, child)
    light_data = bpy.data.lights.new("Collection Merge Skipped Light", "POINT")
    light = bpy.data.objects.new("Collection Merge Skipped Light", light_data)
    child.objects.link(light)
    bpy.context.scene.sdh_deform_merge_collection = parent
    sources, skipped = merge_module.collection_merge_sources(parent)
    check(sources == (first, second),
          "collection merge did not recurse in deterministic object order")
    check(skipped == 1, "collection merge did not count unsupported objects")
    check(bpy.ops.sdh.create_collection_deform_merge() == {"FINISHED"},
          "collection merge operator failed")
    merge = bpy.context.object
    controller = bpy.data.objects.new("Collection Sample Controller", None)
    bpy.context.scene.collection.objects.link(controller)
    try:
        check(core_module.cage_axis_sample_count(merge, controller) == 4,
              "merge topology warning did not sample source meshes")
    finally:
        bpy.data.objects.remove(controller, do_unlink=True)
    check(merge_module.release_deform_merge(bpy.context, merge),
          "collection merge release failed")
    bpy.context.scene.sdh_deform_merge_collection = None
    for obj in (first, second, light):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.lights.remove(light_data)
    bpy.data.collections.remove(child)
    bpy.data.collections.remove(parent)
    return "recursive collection merge with one skipped object"


case("collection_merge_recurses_and_samples_sources",
     collection_merge_recurses_and_samples_sources)


def clean_lifecycle():
    if not registered_here:
        return "skipped for auto-enabled installed extension"
    addon.unregister()
    check(not hasattr(bpy.types, "SDH_UL_merge_sources"),
          "merged source UIList survived unregister")
    check(not hasattr(bpy.types.Object, "sdh_deform_merge_sources"),
          "merge source collection survived unregister")
    check(not hasattr(bpy.types.Object, "sdh_deform_merge_owner"),
          "merge owner pointer survived unregister")
    check(not hasattr(bpy.types.Object, "sdh_deform_merge_active_source_index"),
          "merge source active index survived unregister")
    check(not hasattr(bpy.types.Scene, "sdh_deform_merge_collection"),
          "merge collection pointer survived unregister")
    addon.register()
    check(hasattr(bpy.types, "SDH_UL_merge_sources"),
          "merged source UIList is missing after re-register")
    check(hasattr(bpy.types.Object, "sdh_deform_merge_sources"),
          "merge source collection is missing after re-register")
    check(hasattr(bpy.types.Object, "sdh_deform_merge_active_source_index"),
          "merge source active index is missing after re-register")
    check(hasattr(bpy.types.Scene, "sdh_deform_merge_collection"),
          "merge collection pointer is missing after re-register")
    addon.unregister()
    return "register/unregister/register/unregister"


case("clean_lifecycle", clean_lifecycle)
bpy.context.preferences.addons.remove(addon_entry)

if failures:
    print(f"SDH_MERGE::SUMMARY::FAIL::{failures!r}")
    raise SystemExit(1)
print("SDH_MERGE::SUMMARY::PASS")
