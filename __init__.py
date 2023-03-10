# SPDX-License-Identifier: GPL-2.0-or-later
from . import gizmo, operators, preferences, data,timers,translate

bl_info = {
    "name": "SimpleDeformHelper",
    "author": "AIGODLIKE Community(BlenderCN辣椒,小萌新)",
    "version": (0, 1, 1),
    "blender": (3, 0, 0),
    "location": "3D View -> Select an object and the active modifier is simple deformation",
    "description": "Simple Deform visualization adjustment tool",
    "doc_url": "https://github.com/AIGODLIKE/simple_deform_helper/blob/main/README.md",
    "category": "3D View"
}

module_tuple = (
    gizmo,
    timers,
    translate,
    operators,
    preferences,
)


def register():
    data.Data.load_gizmo_data()

    for item in module_tuple:
        item.register()


def unregister():
    for item in module_tuple:
        item.unregister()
