import bpy

from .deform_axis import DeformAxisOperator
from .key_frame import KeyFrame, RemoveFrame

class_list = (
    DeformAxisOperator,

    KeyFrame,
    RemoveFrame,
)

register_class, unregister_class = bpy.utils.register_classes_factory(class_list)


def register():
    register_class()


def unregister():
    unregister_class()
