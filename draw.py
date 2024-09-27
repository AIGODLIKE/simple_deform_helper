import blf
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, Matrix

from .update import ChangeActiveObject, simple_update
from .utils import GizmoUtils, get_loc_matrix, from_curve_get_animation_offset


class DrawPublic(GizmoUtils):
    G_HandleData = {}  # Save draw Handle

    @classmethod
    def draw_3d_shader(cls, pos, indices, color=None, *,
                       shader_name='UNIFORM_COLOR', draw_type='LINES'):
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

    @classmethod
    def draw_smooth_3d_shader(cls, pos, indices, color):
        shader = gpu.shader.from_builtin('POLYLINE_SMOOTH_COLOR')
        batch = batch_for_shader(
            shader, 'LINES',
            {"pos": pos, "color": [color for _ in pos]},
            indices=indices,
        )
        batch.draw(shader)

    @property
    def draw_poll(self) -> bool:
        if simple_update.timers_update_poll():
            is_switch_obj = ChangeActiveObject.is_change_active_object(False)
            if self.poll_simple_deform_public(
                    bpy.context) and not is_switch_obj:
                return True
        return False


class DrawText(DrawPublic):
    font_info = {
        'font_id': 0,
        'handler': None,
    }
    text_key = 'handler_text'

    @classmethod
    def add_text_handler(cls):
        key = cls.text_key
        if key not in cls.G_HandleData:
            cls.G_HandleData[key] = bpy.types.SpaceView3D.draw_handler_add(
                DrawText().draw_text_handler, (), 'WINDOW', 'POST_PIXEL')

    @classmethod
    def del_text_handler(cls):
        key = cls.text_key
        if key in cls.G_HandleData:
            bpy.types.SpaceView3D.draw_handler_remove(
                cls.G_HandleData[key], 'WINDOW')
            cls.G_HandleData.pop(key)

    @classmethod
    def obj_is_scale(cls) -> bool:
        ob = bpy.context.object
        scale_error = ob and (ob.scale != Vector((1, 1, 1)))
        return scale_error

    def draw_text_handler(self):
        if self.draw_poll and self.obj_is_scale():
            self.draw_scale_text()

    def draw_scale_text(self):
        font_id = self.font_info['font_id']
        y = 80
        blf.size(font_id, 15)
        blf.color(font_id, 1, 1, 1, 1)
        text_list = [
            'The scaling value of the object is not 1',
            'which will cause the deformation of the simple deformation '
            'modifier.',
            'Please apply the scaling before deformation.',
        ]
        for text in text_list[::-1]:
            blf.position(font_id, 200, y, 0)
            blf.draw(font_id, bpy.app.translations.pgettext_iface(text))
            y += 20

    @classmethod
    def draw_text(cls, x, y, text='Hello Word', font_id=0, size=10, *,
                  color=(0.5, 0.5, 0.5, 1), dpi=72, column=0):
        blf.position(font_id, x, y - (size * (column + 1)), 0)
        blf.size(font_id, size, dpi)
        blf.draw(font_id, text)
        blf.color(font_id, *color)


class DrawHandler(DrawText):
    @classmethod
    def add_handler(cls):
        if 'handler' not in cls.G_HandleData:
            cls.G_HandleData[
                'handler'] = bpy.types.SpaceView3D.draw_handler_add(
                Draw3D().draw_post_view, (), 'WINDOW', 'POST_VIEW')

        cls.add_text_handler()

    @classmethod
    def del_handler(cls):
        data = bpy.data
        if data.meshes.get(cls.G_NAME):
            data.meshes.remove(data.meshes.get(cls.G_NAME))

        if data.objects.get(cls.G_NAME):
            data.objects.remove(data.objects.get(cls.G_NAME))
        cls.del_text_handler()
        if 'handler' in cls.G_HandleData:
            bpy.types.SpaceView3D.draw_handler_remove(
                cls.G_HandleData['handler'], 'WINDOW')
            cls.G_HandleData.clear()


class Draw3D(DrawHandler):

    def _shader_set_prop_(self):
        gpu.state.line_width_set(1)
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('ALWAYS')

    def _set_front_(self):
        gpu.state.line_width_set(1)
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('LESS_EQUAL' if not self.pref.show_wireframe_in_front else 'ALWAYS')

    def draw_post_view(self):
        if self.draw_poll:
            self._shader_set_prop_()
            self.draw_3d(bpy.context)
            self._shader_set_prop_()

    def draw_3d(self, context):
        if not self.modifier_origin_is_available:
            self.draw_bound_box()
        elif self.simple_deform_show_gizmo_poll(context):
            # draw bound box
            self.draw_bound_box()
            self.draw_deform_mesh()
            self.draw_limits_line()
            self.draw_limits_bound_box()

            self.draw_text_handler()
        elif self.poll_simple_deform_show_bend_axis_witch(context):
            self.draw_bound_box()

    def draw_bound_box(self):
        self._set_front_()
        mat = Matrix.Translation(Vector((0.0025, 0.0025, 0.0025))) @ self.obj_matrix_world
        coords = self.matrix_calculation(mat, self.tow_co_to_coordinate(self.modifier_bound_co))
        self.draw_smooth_3d_shader(coords, self.G_INDICES, self.pref.bound_box_color)
        self._shader_set_prop_()

    def draw_limits_bound_box(self):
        self._set_front_()
        self.draw_smooth_3d_shader(self.modifier_limits_bound_box,
                                   self.G_INDICES,
                                   self.pref.limits_bound_box_color,
                                   )
        self._shader_set_prop_()

    def draw_limits_line(self):
        self._shader_set_prop_()
        up_point, down_point, up_limits, down_limits = \
            self.modifier_limits_point
        # draw limits line
        self.draw_smooth_3d_shader((up_limits, down_limits), ((1, 0),), (1, 1, 0, 0.5))
        # draw  line
        self.draw_smooth_3d_shader((up_point, down_point), ((1, 0),), (1, 1, 0, 0.3))

        # draw pos
        self.draw_3d_shader([down_point], (), (0, 1, 0, 0.5),
                            shader_name='UNIFORM_COLOR', draw_type='POINTS')
        self.draw_3d_shader([up_point], (), (1, 0, 0, 0.5),
                            shader_name='UNIFORM_COLOR', draw_type='POINTS')
        self._shader_set_prop_()

    def draw_deform_mesh(self):
        self._set_front_()
        ob = self.obj
        deform_data = self.G_DeformDrawData
        active = self.modifier
        # draw deform mesh
        if (
                'simple_deform_bound_data' in deform_data and
                self.pref.update_deform_wireframe
        ):
            self._set_front_()
            modifiers = self.get_modifiers_parameter(self.modifier)

            act = self.obj.modifiers.active
            if act and act.origin:
                active_con = self.get_constraints_parameter_from_object(act.origin)
            else:
                active_con = self.get_constraints_parameter_from_object(self.obj)

            pos, indices, mat, mod_data, limits, con = deform_data['simple_deform_bound_data']

            is_mod = modifiers == mod_data
            is_limits = limits == active.limits[:]
            is_mat = ob.matrix_world == mat
            is_con = active_con == con

            if is_mod and is_mat and is_limits and is_con:
                self.draw_smooth_3d_shader(pos, indices,
                                           self.pref.deform_wireframe_color)
            self._shader_set_prop_()
        self._shader_set_prop_()

    def draw_origin_error(self):
        self._set_front_()
        ...
        self._shader_set_prop_()
