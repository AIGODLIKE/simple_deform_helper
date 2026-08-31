"""Keep a pre-existing deform merge selected after cage creation workflows."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
INSTALLED_PACKAGE = os.environ.get("SDH_TEST_MODULE")
PACKAGE = INSTALLED_PACKAGE or SOURCE.name
if not INSTALLED_PACKAGE:
    sys.path.insert(0, str(SOURCE.parent))


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def activate_many(objects, active):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.hide_set(False)
        obj.select_set(True)
    bpy.context.view_layer.objects.active = active


case_index = 0


def create_merge(label):
    global case_index
    case_index += 1
    sources = []
    for index, x in enumerate((-1.5, 1.5)):
        bpy.ops.mesh.primitive_cube_add(location=(x, case_index * 4.0, 0.0))
        source = bpy.context.object
        source.name = f"{label} Source {index + 1}"
        sources.append(source)
    activate_many(sources, sources[0])
    result = bpy.ops.sdh.create_deform_merge()
    check(result == {"FINISHED"}, f"{label}: merge creation failed: {result!r}")
    merge = bpy.context.object
    check(merge_module.is_deform_merge(merge),
          f"{label}: active object is not the generated merge")
    return merge, tuple(sources)


def cage_controllers(merge):
    controllers = []
    for modifier in core_module.cage_modifiers(merge):
        controller = core_module.find_controller(merge, modifier)
        check(controller is not None,
              f"{merge.name}: cage modifier has no controller")
        controllers.append(controller)
    return tuple(controllers)


def assert_merge_selection(label, merge, expected_stages):
    bpy.context.view_layer.update()
    active = bpy.context.view_layer.objects.active
    controllers = cage_controllers(merge)
    check(len(controllers) == expected_stages,
          f"{label}: expected {expected_stages} stages, got {len(controllers)}")
    check(active is merge, f"{label}: merge is not the active object")
    check(merge.select_get(), f"{label}: merge is not selected")
    check(all(controller.select_get() for controller in controllers),
          f"{label}: one or more cage controllers are not selected")
    selected = tuple(bpy.context.selected_objects)
    check(merge in selected and all(item in selected for item in controllers),
          f"{label}: target/controller selection is not synchronized")


def cleanup_merge(merge, sources):
    merge_name = merge.name
    check(merge_module.release_deform_merge(bpy.context, merge),
          f"{merge_name}: merge cleanup failed")
    for source in sources:
        if source.name in bpy.data.objects:
            bpy.data.objects.remove(source, do_unlink=True)


if INSTALLED_PACKAGE:
    import addon_utils
    addon_utils.enable(INSTALLED_PACKAGE, default_set=False, persistent=False)
    addon = None
    addon_entry = None
else:
    addon_entry = bpy.context.preferences.addons.new()
    addon_entry.module = PACKAGE
    addon = importlib.import_module(PACKAGE)
    addon.register()

merge_module = importlib.import_module(f"{PACKAGE}.cage_deform.merge")
core_module = importlib.import_module(f"{PACKAGE}.cage_deform.core")

try:
    merge, sources = create_merge("Existing Merge Standard")
    result = bpy.ops.sdh.add_cage_deform(cage_type="STANDARD")
    check(result == {"FINISHED"},
          f"existing merge Standard add failed: {result!r}")
    assert_merge_selection("existing merge Standard add", merge, 1)
    cleanup_merge(merge, sources)

    for cage_type in ("STANDARD", "SHEAR", "FFD"):
        label = f"Existing Merge {cage_type} Chain"
        merge, sources = create_merge(label)
        result = bpy.ops.sdh.add_cage_chain(
            count=3,
            cage_type=cage_type,
            connection_mode="CHAINED",
        )
        check(result == {"FINISHED"},
              f"{cage_type} existing merge chain add failed: {result!r}")
        assert_merge_selection(
            f"{cage_type} existing merge chain add", merge, 3)
        cleanup_merge(merge, sources)

    for cage_type in ("STANDARD", "SHEAR", "FFD"):
        label = f"Existing Merge {cage_type} Subdivide"
        merge, sources = create_merge(label)
        result = bpy.ops.sdh.add_cage_deform(cage_type=cage_type)
        check(result == {"FINISHED"},
              f"{cage_type} subdivide source cage add failed: {result!r}")
        assert_merge_selection(
            f"{cage_type} subdivide source cage add", merge, 1)
        result = bpy.ops.sdh.subdivide_cage_to_chain(count=3, gap=0.0)
        check(result == {"FINISHED"},
              f"{cage_type} existing merge cage subdivision failed: {result!r}")
        assert_merge_selection(
            f"{cage_type} existing merge cage subdivision", merge, 3)
        cleanup_merge(merge, sources)

    print("SDH_MERGE_SELECTION::PASS")
finally:
    if addon is not None:
        addon.unregister()
        bpy.context.preferences.addons.remove(addon_entry)
