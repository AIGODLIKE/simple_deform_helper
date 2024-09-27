import bpy
from bpy.types import Panel

from ..ops import KeyFrame, RemoveFrame


class SimpleDeformPanel(Panel):
    bl_idname = 'Simple_Deform_PT_Panel'
    bl_label = 'Simple Deform Helper'

    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.operator(KeyFrame.bl_idname)
        row.operator(RemoveFrame.bl_idname)


def register():
    bpy.utils.register_class(SimpleDeformPanel)


def unregister():
    bpy.utils.unregister_class(SimpleDeformPanel)
