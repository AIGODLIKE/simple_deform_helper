import math

import bpy
from bpy.props import PointerProperty, StringProperty, FloatProperty, EnumProperty
from bpy.types import PropertyGroup

from .utils import PublicData, GizmoUtils


class SimpleDeformGizmoObjectPropertyGroup(PropertyGroup, GizmoUtils):
    def _limits_up(self, context):
        if self.active_modifier_is_simple_deform:
            self.modifier.limits[1] = self.up_limits

    up_limits: FloatProperty(name='up',
                             description='UP Limits(Red)',
                             default=1,
                             update=_limits_up,
                             max=1,
                             min=0)

    def _limits_down(self, context):
        if self.active_modifier_is_simple_deform:
            self.modifier.limits[0] = self.down_limits

    down_limits: FloatProperty(name='down',
                               description='Lower limit(Green)',
                               default=0,
                               update=_limits_down,
                               max=1,
                               min=0)

    origin_mode_items = (
        ('UP_LIMITS',
         'Follow Upper Limit(Red)',
         'Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin '
         'position as the upper limit during operation'),
        ('DOWN_LIMITS',
         'Follow Lower Limit(Green)',
         'Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin '
         'position as the lower limit during operation'),
        ('LIMITS_MIDDLE',
         'Middle',
         'Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the '
         'origin position between the upper and lower limits during operation'),
        ('MIDDLE',
         'Bound Middle',
         'Add an empty object origin as the rotation axis (if there is an origin, do not add it), and set the origin '
         'position as the position between the bounding boxes during operation'),
        ('NOT', 'No origin operation', ''),
    )

    origin_mode: EnumProperty(name='Origin control mode',
                              default='NOT',
                              items=origin_mode_items)


def __get_rotate__(self):
    """bpy.context.object.constraints['ViewSimpleDeformGizmo_Constraints_Limit_Rotation']
    bpy.data.objects["ViewSimpleDeformGizmo__Empty_1dc82ce8-378e-4b68-bbad-099f1e2625"].constraints["ViewSimpleDeformGizmo_Constraints_Limit_Rotation"].max_z
    """
    name = PublicData.G_NAME_CON_LIMIT
    if name not in self.constraints:
        return -111
    con = self.constraints[name]
    axis = self.simple_deform_helper_rotate_axis
    return getattr(con, f"min_{axis.lower()}", -999)


def __set_rotate__(self, value):
    name = PublicData.G_NAME_CON_LIMIT
    if name not in self.constraints:
        return
    con = self.constraints[name]
    axis = self.simple_deform_helper_rotate_axis
    value = value % (math.pi * 2)
    setattr(con, f"max_{axis.lower()}", value)
    setattr(con, f"min_{axis.lower()}", value)


def register():
    bpy.utils.register_class(SimpleDeformGizmoObjectPropertyGroup)
    bpy.types.Object.SimpleDeformGizmo_PropertyGroup = PointerProperty(
        type=SimpleDeformGizmoObjectPropertyGroup,
        name='SimpleDeformGizmo_PropertyGroup')

    bpy.types.Object.simple_deform_helper_rotate_angle = FloatProperty(
        name='Origin Object Rotate Angle',
        default=0,
        get=__get_rotate__,
        set=__set_rotate__
    )
    bpy.types.Object.simple_deform_helper_rotate_axis = StringProperty(
        name='Origin Object Rotate Axis',
        default='Z'
    )


def unregister():
    bpy.utils.unregister_class(SimpleDeformGizmoObjectPropertyGroup)
    del bpy.types.Object.SimpleDeformGizmo_PropertyGroup

    del bpy.types.Object.simple_deform_helper_rotate_angle
    del bpy.types.Object.simple_deform_helper_rotate_axis
