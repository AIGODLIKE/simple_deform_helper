# SPDX-License-Identifier: GPL-2.0-or-later
import bgl
import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector

from .data import G_INDICES, G_MODIFIERS_PROPERTY, G_NAME, Data
from .utils import Pref, Utils


class Handler(Data):
    @classmethod
    def add_handler(cls):
        """向3d视图添加绘制handler
        并将其存储下来
        """
        if 'handler' not in cls.G_SimpleDeformGizmoHandlerDit:
            cls.G_SimpleDeformGizmoHandlerDit['handler'] = bpy.types.SpaceView3D.draw_handler_add(
                Draw3D.draw_bound_box, (), 'WINDOW', 'POST_VIEW')

    @classmethod
    def del_handler_text(cls):

        if 'handler_text' in cls.G_SimpleDeformGizmoHandlerDit:
            bpy.types.SpaceView3D.draw_handler_remove(
                cls.G_SimpleDeformGizmoHandlerDit['handler_text'], 'WINDOW')
            cls.G_SimpleDeformGizmoHandlerDit.pop('handler_text')

    @classmethod
    def del_handler(cls):
        data = bpy.data
        if data.meshes.get(G_NAME):
            data.meshes.remove(data.meshes.get(G_NAME))

        if data.objects.get(G_NAME):
            data.objects.remove(data.objects.get(G_NAME))

        cls.del_handler_text()

        if 'handler' in cls.G_SimpleDeformGizmoHandlerDit:
            bpy.types.SpaceView3D.draw_handler_remove(
                cls.G_SimpleDeformGizmoHandlerDit['handler'], 'WINDOW')
            cls.G_SimpleDeformGizmoHandlerDit.clear()


class Draw3D(Pref, Data):

    @classmethod
    def draw_3d_shader(cls, pos, indices, color=None, *, shader_name='3D_UNIFORM_COLOR', draw_type='LINES'):
        """
        :param draw_type:
        :param shader_name:
        :param color:
        :param indices:
        :param pos:
        :type pos:list ((0,0,0),(1,1,1))
        2D_FLAT_COLOR - 2D_IMAGE - 2D_SMOOTH_COLOR - 2D_UNIFORM_COLOR - 3D_FLAT_COLOR - 3D_SMOOTH_COLOR - 3D_UNIFORM_COLOR - 3D_POLYLINE_FLAT_COLOR - 3D_POLYLINE_SMOOTH_COLOR - 3D_POLYLINE_UNIFORM_COLOR
        ('POINTS', 'LINES', 'TRIS', 'LINE_STRIP', 'LINE_LOOP','TRI_STRIP',
        'TRI_FAN', 'LINES_ADJ', 'TRIS_ADJ', 'LINE_STRIP_ADJ')
        `NONE`, `ALWAYS`, `LESS`, `LESS_EQUAL`, `EQUAL`, `GREATER` and `GREATER_EQUAL`
        """

        shader = gpu.shader.from_builtin(shader_name)
        if draw_type == 'POINTS':
            batch = batch_for_shader(shader, draw_type, {'pos': pos})
        else:
            batch = batch_for_shader(
                shader, draw_type, {'pos': pos}, indices=indices)

        shader.bind()
        if color:
            shader.uniform_float('color', color)

        batch.draw(shader)

    font_info = {
        'font_id': 0,
        'handler': None,
    }

    @classmethod
    def draw_str(cls):
        obj = bpy.context.object
        font_id = cls.font_info['font_id']

        blf.position(font_id, 200, 80, 0)
        blf.size(font_id, 15, 72)
        blf.color(font_id, 1, 1, 1, 1)
        blf.draw(
            font_id,
            f'The scaling value of the object {obj.name_full} is not 1,'
            f' which will cause the deformation of the simple deformation modifier.'
            f' Please apply the scaling before deformation')
        if obj.scale == Vector((1, 1, 1)):
            Handler.del_handler_text()

    @classmethod
    def draw_text(cls, x, y, text='Hello Word', font_id=0, size=10, *, color=(0.5, 0.5, 0.5, 1), dpi=72, column=0):
        blf.position(font_id, x, y - (size * (column + 1)), 0)
        blf.size(font_id, size, dpi)
        blf.draw(font_id, text)
        blf.color(font_id, *color)

    @classmethod
    def draw_box(cls, data, mat):
        pref = cls._pref()
        coords = Utils.matrix_calculation(mat,
                                          cls.data_to_calculation(data))
        cls.draw_3d_shader(coords, G_INDICES, pref.bound_box_color)

    @classmethod
    def data_to_calculation(cls, data):
        ((min_x, min_y, min_z), (max_x, max_y, max_z)) = data
        return (
            (max_x, min_y, min_z),
            (min_x, min_y, min_z),
            (max_x, max_y, min_z),
            (min_x, max_y, min_z),
            (max_x, min_y, max_z),
            (min_x, min_y, max_z),
            (max_x, max_y, max_z),
            (min_x, max_y, max_z))

    @classmethod
    def draw_limits_bound_box(cls):

        pref = cls._pref()
        handler_dit = cls.G_SimpleDeformGizmoHandlerDit
        if 'draw_limits_bound_box' in handler_dit:
            # draw limits_bound_box
            mat, data = handler_dit['draw_limits_bound_box']
            bgl.glEnable(bgl.GL_DEPTH_TEST)
            coords = Utils.matrix_calculation(mat, cls.data_to_calculation(data))
            cls.draw_3d_shader(coords,
                               G_INDICES,
                               pref.limits_bound_box_color)

    @classmethod
    def draw_limits_line(cls):
        handler_dit = cls.G_SimpleDeformGizmoHandlerDit
        if 'draw_line' in handler_dit:
            line_pos, limits_pos, = handler_dit['draw_line']
            bgl.glDisable(bgl.GL_DEPTH_TEST)
            # draw limits line
            cls.draw_3d_shader(limits_pos, ((1, 0),), (1, 1, 0, 0.5))
            # draw  line
            cls.draw_3d_shader(line_pos, ((1, 0),), (1, 1, 0, 0.3))
            # draw pos
            cls.draw_3d_shader([line_pos[1]], (), (0, 1, 0, 0.5),
                               shader_name='3D_UNIFORM_COLOR', draw_type='POINTS')

    @classmethod
    def draw_deform_mesh(cls, ob, context):
        pref = cls._pref()
        handler_dit = cls.G_SimpleDeformGizmoHandlerDit
        active = context.object.modifiers.active
        # draw deform mesh
        if 'draw' in handler_dit:
            pos, indices, mat, mod_data, limits = handler_dit['draw']
            if ([getattr(active, i) for i in G_MODIFIERS_PROPERTY] == mod_data) and (
                    ob.matrix_world == mat) and limits == active.limits[:]:
                bgl.glEnable(bgl.GL_DEPTH_TEST)
                cls.draw_3d_shader(
                    pos, indices, pref.deform_wireframe_color)

    @classmethod
    def draw_scale_text(cls, ob):
        if (ob.scale != Vector((1, 1, 1))) and ('handler_text' not in cls.G_SimpleDeformGizmoHandlerDit):
            cls.G_SimpleDeformGizmoHandlerDit['handler_text'] = bpy.types.SpaceView3D.draw_handler_add(
                cls.draw_str, (), 'WINDOW', 'POST_PIXEL')

    @classmethod
    def is_draw_box(cls, context):
        obj = context.object  # 活动物体
        matrix = obj.matrix_world  # 活动物体矩阵
        modifier = context.object.modifiers.active  # 活动修改器

        pref = cls._pref()
        simple_poll = Utils.simple_deform_poll(context)
        bend = modifier and (modifier.deform_method == 'BEND')
        display_switch_axis = False == pref.display_bend_axis_switch_gizmo

        cls.draw_scale_text(obj)
        Utils.update_co_data(obj, modifier)

        co_data = Utils.generate_co_data()

        if simple_poll and ((not bend) or display_switch_axis):
            # draw bound box
            cls.draw_box(co_data, matrix)
            cls.draw_deform_mesh(obj, context)
            cls.draw_limits_line()
            cls.draw_limits_bound_box()
        elif simple_poll and (bend and not display_switch_axis):
            bgl.glDisable(bgl.GL_DEPTH_TEST)
            cls.draw_box(co_data, matrix)
            Utils.new_empty(obj, modifier)

    @classmethod
    def draw_bound_box(cls):
        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(1)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_ALPHA)
        bgl.glDisable(bgl.GL_DEPTH_TEST)

        context = bpy.context
        if Utils.simple_deform_poll(context):
            cls.is_draw_box(context)
        else:
            Handler.del_handler()
