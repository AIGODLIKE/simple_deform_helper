# SPDX-License-Identifier: GPL-2.0-or-later

import bpy
from bpy.app import timers


def remove_not_use_empty(remove_name: str = "ViewSimpleDeformGizmo__Empty_"):
    """循环场景内的所有物体,找出没用的空物体并删掉
    """
    context = bpy.context
    for obj in context.scene.objects:
        is_empty = obj.type == "EMPTY"
        not_parent = not obj.parent
        name_ok = obj.name.count(remove_name)
        if name_ok and not_parent and is_empty:
            bpy.data.objects.remove(obj)  # remove object


def update_timers() -> float:
    remove_not_use_empty()
    return 3


def register():
    timers.register(update_timers, persistent=True)


def unregister():
    if timers.is_registered(update_timers):
        timers.unregister(update_timers)
