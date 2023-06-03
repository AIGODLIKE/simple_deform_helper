# SPDX-License-Identifier: GPL-2.0-or-later
from functools import cache

import bpy

from .utils import GizmoUpdate

gizmo = GizmoUpdate()

"""depsgraph_update_post cannot listen to users modifying modifier parameters
Use timers to watch and use cache
"""


class update_public:
    _events_func_list = {}
    run_time = 0.2

    @classmethod
    def timers_update_poll(cls) -> bool:
        return True

    @classmethod
    @cache
    def update_poll(cls) -> bool:
        return True

    @classmethod
    def _update_func_call_timer(cls):
        if cls.timers_update_poll():
            for c, func_list in cls._events_func_list.items():
                if func_list and c.update_poll():
                    for func in func_list:
                        func()
        cls.clear_cache_events()
        return cls.run_time

    @classmethod
    def clear_cache_events(cls):
        for cl in cls._events_func_list.keys():
            if getattr(cl, 'clear_cache', False):
                cl.clear_cache()

    @classmethod
    def clear_cache(cls):
        cls.update_poll.cache_clear()

    @classmethod
    def append(cls, item):
        if cls not in cls._events_func_list:
            cls._events_func_list[cls] = []
        cls._events_func_list[cls].append(item)

    @classmethod
    def remove(cls, item):
        if item in cls._events_func_list[cls]:
            cls._events_func_list[cls].remove(item)

    # ---------------   reg and unreg
    @classmethod
    def register(cls):
        from bpy.app import timers
        func = cls._update_func_call_timer
        if not timers.is_registered(func):
            timers.register(func, persistent=True)
        else:
            print('cls timers is registered', cls)

    @classmethod
    def unregister(cls):
        from bpy.app import timers
        func = cls._update_func_call_timer
        if timers.is_registered(func):
            timers.unregister(func)
        else:
            print('cls timers is not registered', cls)
        cls._events_func_list.clear()


class simple_update(update_public, GizmoUpdate):
    tmp_save_data = {}

    @classmethod
    def timers_update_poll(cls):
        obj = bpy.context.object
        if not cls.poll_context_mode_is_object():
            ...
        elif not obj:
            ...
        elif not cls.obj_type_is_mesh_or_lattice(obj):
            ...
        elif cls.mod_is_simple_deform_type(obj.modifiers.active):
            return True
        return False


class ChangeActiveObject(simple_update):
    @classmethod
    @cache
    def update_poll(cls):
        return cls.is_change_active_object()

    @classmethod
    def is_change_active_object(cls, change_data=True):
        import bpy
        obj = bpy.context.object
        name = obj.name
        key = 'active_object'
        if key not in cls.tmp_save_data or cls.tmp_save_data[key] != name:
            if change_data:
                cls.tmp_save_data[key] = name
            return True
        return False


class ChangeActiveSimpleDeformModifier(simple_update):

    @classmethod
    @cache
    def update_poll(cls):
        return cls.is_change_active_simple_deform()

    @classmethod
    def is_change_active_simple_deform(cls) -> bool:
        import bpy
        obj = bpy.context.object
        modifiers = cls.get_modifiers_data(obj)

        def update():
            cls.tmp_save_data['modifiers'] = modifiers

        if ChangeActiveObject.update_poll():
            update()
        elif 'modifiers' not in cls.tmp_save_data:
            update()
        elif cls.tmp_save_data['modifiers'] != modifiers:
            update()
            return True
        return False

    @classmethod
    def get_modifiers_data(cls, obj):
        return {'obj': obj.name,
                'active_modifier': getattr(obj.modifiers.active, 'name', None),
                'modifiers': list(i.name for i in obj.modifiers)}


class ChangeActiveModifierParameter(simple_update):
    key = 'active_modifier_parameter'

    @classmethod
    @cache
    def update_poll(cls):
        return gizmo.active_modifier_is_simple_deform and cls.is_change_active_simple_parameter()

    @classmethod
    def update_modifier_parameter(cls, modifier_parameter=None):
        """Run this function when the gizmo is updated to avoid duplicate updates
        """
        if not modifier_parameter:
            modifier_parameter = cls.get_modifiers_parameter(gizmo.modifier)
        cls.tmp_save_data[cls.key] = modifier_parameter

    @classmethod
    def change_modifier_parameter(cls) -> bool:
        mod_data = cls.get_modifiers_parameter(gizmo.modifier)
        return cls.key in cls.tmp_save_data and cls.tmp_save_data[cls.key] == mod_data

    @classmethod
    def is_change_active_simple_parameter(cls):
        parameter = cls.get_modifiers_parameter(gizmo.modifier)
        if ChangeActiveObject.update_poll():
            cls.update_modifier_parameter(parameter)
        elif ChangeActiveSimpleDeformModifier.update_poll():
            cls.update_modifier_parameter(parameter)
        elif cls.key not in cls.tmp_save_data:
            cls.update_modifier_parameter(parameter)
        elif cls.tmp_save_data[cls.key] != parameter:
            cls.update_modifier_parameter(parameter)
            return True
        return False


def register():
    simple_update.register()

    def p():
        gizmo.update_multiple_modifiers_data()

    ChangeActiveObject.append(p)
    ChangeActiveModifierParameter.append(p)
    ChangeActiveSimpleDeformModifier.append(p)


def unregister():
    simple_update.unregister()
