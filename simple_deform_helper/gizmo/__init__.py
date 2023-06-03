import bpy

from .angle_and_factor import AngleGizmoGroup, AngleGizmo
from .bend_axis import BendAxiSwitchGizmoGroup, CustomGizmo
from .set_deform_axis import SetDeformGizmoGroup
from .up_down_limits_point import UpDownLimitsGizmo, UpDownLimitsGizmoGroup
from ..draw import Draw3D

class_list = (
    UpDownLimitsGizmo,
    UpDownLimitsGizmoGroup,

    AngleGizmo,
    AngleGizmoGroup,

    CustomGizmo,
    BendAxiSwitchGizmoGroup,

    SetDeformGizmoGroup,
)

register_class, unregister_class = bpy.utils.register_classes_factory(class_list)


def register():
    Draw3D.add_handler()
    register_class()


def unregister():
    Draw3D.del_handler()
    unregister_class()
