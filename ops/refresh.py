from bpy.types import Operator
from ..utils import GizmoUtils

class Refresh(Operator, GizmoUtils):
    bl_idname = 'simple_deform_gizmo.refresh'
    bl_label = 'Refresh'

    def invoke(self, context, event):
        self.update_deform_wireframe()
        self.update_object_origin_matrix()
        return {"FINISHED"}

