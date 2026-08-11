"""Verify unified management of cage and native Simple Deform stages."""
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


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def add_cage(target, cage_type="STANDARD"):
    activate(target)
    check(
        bpy.ops.sdh.add_cage_deform(cage_type=cage_type) == {"FINISHED"},
        "could not add cage stage",
    )
    activate(target)
    return tuple(
        modifier for modifier in target.modifiers
        if cage.is_cage_modifier(modifier)
    )[-1]


def add_legacy(target):
    activate(target)
    check(
        bpy.ops.sdh.add_legacy_simple_deform() == {"FINISHED"},
        "could not add traditional Simple Deform stage",
    )
    return target.modifiers.active


addon = importlib.import_module(PACKAGE)
if not INSTALLED_PACKAGE:
    entry = bpy.context.preferences.addons.new()
    entry.module = PACKAGE
    addon.register()
cage = importlib.import_module(f"{PACKAGE}.cage_deform")
stack_ui = importlib.import_module(f"{PACKAGE}.cage_deform.ui")


mesh = bpy.data.meshes.new("Unified Deform Stack")
mesh.from_pydata(
    ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)), (), ())
target = bpy.data.objects.new("Unified Deform Stack", mesh)
bpy.context.collection.objects.link(target)

first_cage = add_cage(target)
legacy = add_legacy(target)
check(legacy.deform_method == "BEND", "traditional stage did not default to Bend")
check(legacy.deform_axis == "Y", "traditional stage did not default to +Y")
check(abs(legacy.angle) < 1.0e-8, "traditional Bend was not neutral at creation")
legacy_viewport_controls = stack_ui._stack_viewport_controls(legacy, None)
check(
    legacy_viewport_controls[1:] == (
        "display_bend_axis_switch_gizmo",
        "show_other_stage_bounds",
    ),
    "traditional stack header controls target the wrong display settings",
)
legacy_origin = legacy.origin
check(
    cage.core.GizmoUtils.is_managed_origin(legacy_origin, target),
    "traditional stage did not create a managed Origin",
)
check(
    legacy_origin.SimpleDeformGizmo_PropertyGroup.origin_mode == "DOWN_LIMITS",
    "traditional Origin did not default to following the lower limit",
)
check(
    bpy.ops.sdh.insert_cage_keyframes() == {"FINISHED"},
    "unified keyframe insertion did not support the traditional stage",
)
check(
    bpy.ops.sdh.delete_cage_keyframes() == {"FINISHED"},
    "unified keyframe deletion did not support the traditional stage",
)
check(
    bpy.ops.sdh.bake_cage_animation.poll(),
    "mesh-animation baking was unavailable for a traditional stage",
)
second_cage = add_cage(target)
check(
    cage.deform_stack_modifiers(target) ==
    (first_cage, legacy, second_cage),
    "mixed stages were not listed in evaluated modifier order",
)

activate(target)
check(
    bpy.ops.sdh.select_cage_stage(
        index=1, include_legacy=True) == {"FINISHED"},
    "traditional stage could not be selected from the unified stack",
)
check(target.modifiers.active == legacy, "traditional stage did not become active")
check(bpy.context.object == target, "traditional stage exposed a cage helper object")

check(
    bpy.ops.sdh.move_cage_deform(
        index=1, direction="EARLIER", include_legacy=True) == {"FINISHED"},
    "traditional stage could not move earlier",
)
check(
    cage.deform_stack_modifiers(target) ==
    (legacy, first_cage, second_cage),
    "traditional stage moved to the wrong stack position",
)
check(
    bpy.ops.sdh.move_cage_deform(
        index=0, direction="LATER", include_legacy=True) == {"FINISHED"},
    "traditional stage could not move later",
)
check(
    cage.deform_stack_modifiers(target) ==
    (first_cage, legacy, second_cage),
    "traditional stage did not return to its original position",
)

check(
    bpy.ops.sdh.remove_cage_deform(
        index=1, include_legacy=True) == {"FINISHED"},
    "traditional stage could not be removed from the unified stack",
)
check(legacy not in tuple(target.modifiers), "traditional stage survived removal")
check(
    cage.deform_stack_modifiers(target) == (first_cage, second_cage),
    "removing a traditional stage damaged adjacent cage stages",
)

legacy = add_legacy(target)
activate(target)
check(
    bpy.ops.sdh.remove_cage_stack(include_legacy=False) == {"FINISHED"},
    "legacy cage-only stack removal failed",
)
check(
    cage.deform_stack_modifiers(target) == (legacy,),
    "cage-only removal unexpectedly removed the traditional stage",
)
check(
    bpy.ops.sdh.remove_cage_stack(include_legacy=True) == {"FINISHED"},
    "unified stack removal failed",
)
check(not cage.deform_stack_modifiers(target), "unified stack was not cleared")


ffd_mesh = bpy.data.meshes.new("Unified FFD Stack")
ffd_mesh.from_pydata(
    ((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)), (), ())
ffd_target = bpy.data.objects.new("Unified FFD Stack", ffd_mesh)
bpy.context.collection.objects.link(ffd_target)
ffd_stage = add_cage(ffd_target, cage_type="FFD")
ffd_legacy = add_legacy(ffd_target)
check(
    cage.deform_stack_modifiers(ffd_target) == (ffd_stage, ffd_legacy),
    "FFD companion modifier leaked into the unified stack",
)
activate(ffd_target)
check(
    bpy.ops.sdh.move_cage_deform(
        index=1, direction="EARLIER", include_legacy=True) == {"FINISHED"},
    "traditional stage could not move before an FFD stage",
)
check(
    cage.deform_stack_modifiers(ffd_target) == (ffd_legacy, ffd_stage),
    "traditional stage moved to the wrong side of the FFD stage",
)
ffd_companion = next(
    modifier for modifier in ffd_target.modifiers
    if modifier.type == "LATTICE")
check(
    tuple(ffd_target.modifiers).index(ffd_companion) ==
    tuple(ffd_target.modifiers).index(ffd_stage) + 1,
    "FFD companion no longer follows its owner stage",
)
check(
    bpy.ops.sdh.move_cage_deform(
        index=0, direction="LATER", include_legacy=True) == {"FINISHED"},
    "traditional stage could not move after an FFD stage",
)
check(
    cage.deform_stack_modifiers(ffd_target) == (ffd_stage, ffd_legacy),
    "traditional stage did not return after the FFD stage",
)
check(
    tuple(ffd_target.modifiers).index(ffd_companion) ==
    tuple(ffd_target.modifiers).index(ffd_stage) + 1,
    "moving past FFD split its companion from the owner stage",
)
check(
    bpy.ops.sdh.remove_cage_stack(include_legacy=True) == {"FINISHED"},
    "mixed FFD stack could not be cleared",
)
check(not tuple(ffd_target.modifiers), "clearing FFD stack kept companion data")


lattice_data = bpy.data.lattices.new("Unified Lattice Stack")
lattice = bpy.data.objects.new("Unified Lattice Stack", lattice_data)
bpy.context.collection.objects.link(lattice)
first_lattice_stage = add_legacy(lattice)
second_lattice_stage = add_legacy(lattice)
check(
    cage.deform_stack_modifiers(lattice) ==
    (first_lattice_stage, second_lattice_stage),
    "lattice traditional stages were not added to the unified stack",
)
activate(lattice)
check(
    bpy.ops.sdh.select_cage_stage(
        index=0, include_legacy=True) == {"FINISHED"},
    "lattice traditional stage could not be selected",
)
check(
    bpy.ops.sdh.move_cage_deform(
        index=0, direction="LATER", include_legacy=True) == {"FINISHED"},
    "lattice traditional stage could not be reordered",
)
check(
    cage.deform_stack_modifiers(lattice) ==
    (second_lattice_stage, first_lattice_stage),
    "lattice traditional stage order did not update",
)
check(
    bpy.ops.sdh.remove_cage_stack(include_legacy=True) == {"FINISHED"},
    "lattice unified stack could not be cleared",
)
check(not cage.deform_stack_modifiers(lattice), "lattice stack was not cleared")

# A lattice cannot parent its managed Origin without a dependency cycle.  The
# detached Origin must still follow a target transform through the safe queue.
activate(lattice)
lattice_stage = add_legacy(lattice)
lattice_origin = lattice_stage.origin
before_location = tuple(lattice_origin.matrix_world.translation)
lattice.location.x += 2.0
bpy.context.view_layer.update()
check(
    cage.core.request_lattice_origin_sync(lattice),
    "lattice transform did not queue detached Origin synchronization",
)
cage.core._drain_lattice_origin_sync_queue()
after_location = tuple(lattice_origin.matrix_world.translation)
check(
    abs((after_location[0] - before_location[0]) - 2.0) < 1.0e-4,
    "detached lattice Origin did not follow target translation",
)
lower_location = lattice_origin.matrix_world.translation.copy()
lattice_origin.SimpleDeformGizmo_PropertyGroup.origin_mode = "UP_LIMITS"
upper_location = lattice_origin.matrix_world.translation.copy()
check(
    (upper_location - lower_location).length > 0.5,
    "detached lattice Origin did not respond to an Origin-mode change",
)
origin_name = lattice_origin.name
bpy.data.objects.remove(lattice, do_unlink=True)
cage.core.cleanup_orphan_deform_helpers()
check(
    bpy.data.objects.get(origin_name) is None,
    "detached lattice Origin survived target deletion",
)


print("SDH_UNIFIED_DEFORM_STACK::PASS")

if not INSTALLED_PACKAGE:
    addon.unregister()
