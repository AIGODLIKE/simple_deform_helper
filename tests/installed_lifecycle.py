"""Confirm that an extension installed with Blender's CLI can enable cleanly."""

import importlib
from types import SimpleNamespace

import addon_utils
import bpy
from mathutils import Vector


matches = [
    entry.module for entry in bpy.context.preferences.addons
    if entry.module == "bl_ext.sdh_test.simple_deform_helper"
]
if len(matches) != 1:
    raise RuntimeError(f"Expected one enabled Simple Deform Helper extension, got {matches!r}")

module = importlib.import_module(matches[0])

bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.object
modifier = obj.modifiers.new("Installed Lifecycle", "SIMPLE_DEFORM")
obj.modifiers.active = modifier
if not hasattr(obj, "SimpleDeformGizmo_PropertyGroup"):
    raise RuntimeError("Object properties were not registered")


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


obj.modifiers.new("Installed Lifecycle Second", "SIMPLE_DEFORM")
obj.modifiers.active = modifier
origin = bpy.data.objects.new("Installed External Origin", None)
bpy.context.collection.objects.link(origin)
modifier.origin = origin
fake_context = SimpleNamespace(
    object=obj,
    space_data=SimpleNamespace(type="VIEW_3D", show_gizmo=True),
)
header_module = importlib.import_module(f"{matches[0]}.ui.header")
header_module.SimpleDeformHelperToolHeader.draw_property(Layout(), fake_context)
modifier.origin = None
bpy.data.objects.remove(origin, do_unlink=True)

cage_module = importlib.import_module(f"{matches[0]}.cage_deform")
cage_modifier, cage_controller, _previous = cage_module.create_deform_stage(
    bpy.context, obj, name="Installed Cage Deform")
cage_properties = cage_controller.sdh_cage_deform
cage_properties.deform_type = "TWIST"
cage_properties.strength = 1.35
cage_properties.direction = 0.25
cage_properties.mode = "LIMITED"
cage_properties.origin = "BOTTOM"
cage_properties.top_scale = (1.45, 0.75)
cage_properties.bottom_scale = (0.85, 1.1)
cage_properties.top_offset = (0.25, -0.1)
cage_properties.bottom_offset = (-0.15, 0.05)
cage_module.sync_controller(cage_controller, pull_transform=False)
utils_module = importlib.import_module(f"{matches[0]}.utils")
if not cage_controller.hide_get() or not cage_controller.hide_select:
    raise RuntimeError("Installed controller is not hidden by default")
if not any(
        collection.get(utils_module.CONTROL_COLLECTION_MARKER, False)
        for collection in cage_controller.users_collection):
    raise RuntimeError("Installed controller is outside the helper collection")
if cage_controller.empty_display_type != cage_module.CONTROLLER_STYLES["TWIST"][0]:
    raise RuntimeError("Installed Twist controller style was not applied")
cage_module.move_cage_boundary(
    cage_controller,
    "TOP",
    0.4,
    tuple(cage_properties.size),
    tuple(cage_controller.location),
)
installed_boundary_size = tuple(cage_properties.size)


def evaluated_points(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        return tuple(vertex.co.copy() for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


installed_before_disable = evaluated_points(obj)
if not any((point - obj.data.vertices[index].co).length > 1.0e-4
           for index, point in enumerate(installed_before_disable)):
    raise RuntimeError("Installed Cage Deform did not deform evaluated geometry")
cage_uuid = cage_module.cage_modifier_uuid(cage_modifier)

addon_utils.disable(matches[0], default_set=False)
if hasattr(bpy.types.Object, "SimpleDeformGizmo_PropertyGroup"):
    raise RuntimeError("Object properties survived disable")
if hasattr(bpy.types.Object, "sdh_cage_deform"):
    raise RuntimeError("Cage Deform controller properties survived disable")
installed_while_disabled = evaluated_points(obj)
if any((before - after).length > 1.0e-4
       for before, after in zip(installed_before_disable, installed_while_disabled)):
    raise RuntimeError("Cage Deform geometry changed when the extension was disabled")
addon_utils.enable(matches[0], default_set=False)
if not hasattr(bpy.types.Object, "SimpleDeformGizmo_PropertyGroup"):
    raise RuntimeError("Object properties were not restored after enable")
if not hasattr(bpy.types.Object, "sdh_cage_deform"):
    raise RuntimeError("Cage Deform controller properties were not restored after enable")
cage_module = importlib.import_module(f"{matches[0]}.cage_deform")
restored_modifier = next(
    (item for item in cage_module.cage_modifiers(obj)
     if cage_module.cage_modifier_uuid(item) == cage_uuid),
    None,
)
restored_controller = cage_module.find_controller(obj, restored_modifier)
if restored_modifier is None or restored_controller is None:
    raise RuntimeError("Cage Deform ownership was not restored after enable")
if abs(Vector(cage_module.modifier_input(restored_modifier, "Center")).x -
       restored_controller.location.x) > 1.0e-4:
    raise RuntimeError("Cage Deform inputs were not synchronized after enable")
restored_properties = restored_controller.sdh_cage_deform
if restored_properties.deform_type != "TWIST":
    raise RuntimeError("Twist type did not survive re-enable")
if restored_controller.empty_display_type != cage_module.CONTROLLER_STYLES["TWIST"][0]:
    raise RuntimeError("Twist controller style was not restored after enable")
if (Vector(restored_properties.top_scale) - Vector((1.45, 0.75))).length > 1.0e-4:
    raise RuntimeError("Independent top shape did not survive re-enable")
if (Vector(restored_properties.bottom_offset) - Vector((-0.15, 0.05))).length > 1.0e-4:
    raise RuntimeError("Independent bottom shape did not survive re-enable")
if (Vector(cage_module.modifier_input(restored_modifier, "Top Scale")) -
        Vector((1.45, 1.0, 0.75))).length > 1.0e-4:
    raise RuntimeError("Independent end inputs were not synchronized after enable")
if (Vector(restored_properties.size) - Vector(installed_boundary_size)).length > 1.0e-4:
    raise RuntimeError("Independent cage length did not survive re-enable")
if (Vector(cage_module.modifier_input(restored_modifier, "Size")) -
        Vector(installed_boundary_size)).length > 1.0e-4:
    raise RuntimeError("Independent cage length did not resynchronize after enable")
if not restored_properties.show_boundary_handles:
    raise RuntimeError("Independent cage boundary handles were not restored")
addon_utils.disable(matches[0], default_set=False)
print(f"SDH::INSTALLED::PASS::{matches[0]}")
