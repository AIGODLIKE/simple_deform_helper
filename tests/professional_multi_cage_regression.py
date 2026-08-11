"""Regression coverage for compact UI and multi-object cage creation."""

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
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


def add_cube(name, x):
    bpy.ops.mesh.primitive_cube_add(location=(x, 0.0, 0.0))
    obj = bpy.context.object
    obj.name = name
    return obj


class Layout:
    def __init__(self):
        self.properties = []
        self.operators = []
        self.enabled = True
        self.alert = False
        self.scale_y = 1.0

    def row(self, **_kwargs):
        return self

    def column(self, **_kwargs):
        return self

    def box(self):
        return self

    def grid_flow(self, **_kwargs):
        return self

    def split(self, **_kwargs):
        return self

    def prop(self, _data, identifier, **_kwargs):
        self.properties.append(identifier)

    def operator(self, identifier, **_kwargs):
        self.operators.append(identifier)
        return SimpleNamespace()

    def label(self, **_kwargs):
        return None

    def separator(self, **_kwargs):
        return None

    def template_list(self, *_args, **_kwargs):
        return None


entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()

core = importlib.import_module(f"{PACKAGE}.cage_deform.core")
merge_module = importlib.import_module(f"{PACKAGE}.cage_deform.merge")
ui_module = importlib.import_module(f"{PACKAGE}.cage_deform.ui")
utils = importlib.import_module(f"{PACKAGE}.utils")


first = add_cube("Overall Cage First", -2.0)
second = add_cube("Overall Cage Second", 2.0)
activate_many((first, second), second)
check(
    bpy.ops.sdh.add_cage_deform(cage_type="STANDARD") == {"FINISHED"},
    "ordinary multi-object cage creation failed",
)
overall_controller = bpy.context.object
overall_target = core.find_target(overall_controller)
check(merge_module.is_deform_merge(overall_target),
      "ordinary click did not create one live merge target")
check(len(merge_module.live_merge_sources(overall_target)) == 2,
      "ordinary click did not retain both merge sources")
check(len(core.cage_modifiers(overall_target)) == 1,
      "ordinary click did not add exactly one cage to the merged target")


third = add_cube("Separate Cage First", -2.0)
fourth = add_cube("Separate Cage Second", 2.0)
activate_many((third, fourth), fourth)
merge_count = sum(merge_module.is_deform_merge(obj) for obj in bpy.data.objects)
check(
    bpy.ops.sdh.add_cage_deform(
        cage_type="STANDARD", individual_objects=True) == {"FINISHED"},
    "Ctrl-style separate cage creation failed",
)
check(sum(merge_module.is_deform_merge(obj) for obj in bpy.data.objects) == merge_count,
      "Ctrl-style creation unexpectedly made another merge target")
for target in (third, fourth):
    stages = core.cage_modifiers(target)
    check(len(stages) == 1,
          f"{target.name} did not receive exactly one separate cage")
    controller = core.find_controller(target, stages[0])
    check(controller is not None,
          f"{target.name} is missing its separate cage controller")
check(core.find_target(bpy.context.object) == fourth,
      "separate cage creation did not preserve the active target")


preferences = utils.get_pref()
check(not preferences.professional_mode,
      "Professional Mode must default to the compact panel")
properties = core.find_controller(fourth, core.cage_modifiers(fourth)[0]).sdh_cage_deform
properties.show_cage_controls = False
properties.show_deform_axis = False
properties.show_end_shape_settings = False
properties.show_numeric_controls = False

compact = Layout()
ui_module.SDH_CAGE_PT_deform.draw(SimpleNamespace(layout=compact), bpy.context)
advanced_properties = {
    "show_deform_axis", "show_end_shape_settings", "show_numeric_controls",
}
check(not advanced_properties.intersection(compact.properties),
      "compact panel exposed professional-only sections")

preferences.professional_mode = True
professional = Layout()
ui_module.SDH_CAGE_PT_deform.draw(
    SimpleNamespace(layout=professional), bpy.context)
check(advanced_properties.issubset(set(professional.properties)),
      "Professional Mode did not expose every advanced section")


addon.unregister()
bpy.context.preferences.addons.remove(entry)
print("SDH::PROFESSIONAL_MULTI_CAGE::PASS")
