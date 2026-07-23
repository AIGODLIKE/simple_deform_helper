import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, Matrix

from .update import ChangeActiveObject, simple_update
from .utils import GizmoUtils
from .stages import StageCache


class DrawPublic(GizmoUtils):
    G_HandleData = {}  # Save draw Handle
    G_ShaderData = {}

    @classmethod
    def get_shader(cls, shader_name):
        shader = cls.G_ShaderData.get(shader_name)
        if shader is None:
            shader = gpu.shader.from_builtin(shader_name)
            cls.G_ShaderData[shader_name] = shader
        return shader

    @classmethod
    def draw_3d_shader(cls, pos, indices, color=None, *,
                       shader_name="UNIFORM_COLOR", draw_type="LINES"):
        shader = cls.get_shader(shader_name)
        if draw_type == "POINTS":
            batch = batch_for_shader(shader, draw_type, {"pos": pos})
        else:
            batch = batch_for_shader(
                shader, draw_type, {"pos": pos}, indices=indices)

        shader.bind()
        if color:
            shader.uniform_float("color", color)
        batch.draw(shader)

    @classmethod
    def draw_smooth_3d_shader(cls, pos, indices, color):
        shader = cls.get_shader("POLYLINE_SMOOTH_COLOR")
        batch = batch_for_shader(
            shader, "LINES",
            {"pos": pos, "color": [color for _ in pos]},
            indices=indices,
        )
        batch.draw(shader)

    @property
    def draw_poll(self) -> bool:
        from .cage_deform import resolve_context_deform
        target, modifier, controller = resolve_context_deform(
            bpy.context, fallback=False)
        if target and modifier and controller and modifier.show_viewport:
            return True
        if simple_update.timers_update_poll():
            is_switch_obj = ChangeActiveObject.is_change_active_object(False)
            if self.poll_simple_deform_public(bpy.context) and not is_switch_obj:
                return True
        return False


class DrawText(DrawPublic):
    font_info = {
        "font_id": 0,
        "handler": None,
    }
    text_key = "handler_text"

    @classmethod
    def add_text_handler(cls):
        key = cls.text_key
        if key not in cls.G_HandleData:
            cls.G_HandleData[key] = bpy.types.SpaceView3D.draw_handler_add(
                DrawText().draw_text_handler, (), "WINDOW", "POST_PIXEL")

    @classmethod
    def del_text_handler(cls):
        key = cls.text_key
        if key in cls.G_HandleData:
            bpy.types.SpaceView3D.draw_handler_remove(
                cls.G_HandleData[key], "WINDOW")
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
        font_id = self.font_info["font_id"]
        y = 80
        blf.size(font_id, 15)
        blf.color(font_id, 1, 1, 1, 1)
        text_list = [
            "The scaling value of the object is not 1",
            "which will cause the deformation of the simple deformation "
            "modifier.",
            "Please apply the scaling before deformation.",
        ]
        for text in text_list[::-1]:
            blf.position(font_id, 200, y, 0)
            blf.draw(font_id, bpy.app.translations.pgettext_iface(text))
            y += 20

    @classmethod
    def draw_text(cls, x, y, text="Hello Word", font_id=0, size=10, *,
                  color=(0.5, 0.5, 0.5, 1), column=0):
        blf.position(font_id, x, y - (size * (column + 1)), 0)
        blf.size(font_id, size)
        blf.color(font_id, *color)
        blf.draw(font_id, text)


class DrawHandler(DrawText):
    @classmethod
    def add_handler(cls):
        if "handler" not in cls.G_HandleData:
            cls.G_HandleData[
                "handler"] = bpy.types.SpaceView3D.draw_handler_add(
                Draw3D().draw_post_view, (), "WINDOW", "POST_VIEW")

        cls.add_text_handler()

    @classmethod
    def del_handler(cls):
        cls.del_text_handler()
        if "handler" in cls.G_HandleData:
            bpy.types.SpaceView3D.draw_handler_remove(
                cls.G_HandleData["handler"], "WINDOW")
        cls.G_HandleData.clear()
        cls.G_ShaderData.clear()


class Draw3D(DrawHandler):

    def _shader_set_prop_(self):
        gpu.state.line_width_set(1)
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("ALWAYS")

    def _set_front_(self):
        gpu.state.line_width_set(1)
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("LESS_EQUAL" if not self.pref.show_wireframe_in_front else "ALWAYS")

    def draw_post_view(self):
        try:
            if self.draw_poll:
                self._shader_set_prop_()
                self.draw_3d(bpy.context)
        except (ReferenceError, RuntimeError, AttributeError, TypeError, ValueError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            if self.G_HandleData.get("draw_error") != message:
                print("Simple Deform Helper draw:", message)
                self.G_HandleData["draw_error"] = message
        finally:
            gpu.state.line_width_set(1)
            gpu.state.depth_test_set("NONE")
            gpu.state.blend_set("NONE")

    def draw_3d(self, context):
        if self.draw_cage_deform(context):
            return
        if not self.modifier_origin_is_available:
            self.draw_bound_box()
        elif self.simple_deform_show_gizmo_poll(context):
            # draw bound box
            self.draw_other_stage_bounds()
            self.draw_bound_box()
            self.draw_deform_mesh()
            self.draw_limits_line()
            self.draw_limits_bound_box()

            self.draw_text_handler()
        elif self.poll_simple_deform_show_bend_axis_witch(context):
            self.draw_bound_box()

    def draw_cage_deform(self, context):
        from .cage_deform import (
            cage_boundary_points_local,
            cage_local_matrix,
            deform_point_local,
            resolve_context_deform,
        )
        target, modifier, controller = resolve_context_deform(
            context, fallback=False)
        if not target or not modifier or not controller:
            return False
        properties = controller.sdh_cage_deform
        if not properties.show_cage:
            return True

        # The cage is an editing control rather than a surface preview, so it
        # remains readable through the deformed object.
        gpu.state.line_width_set(2.0)
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set("ALWAYS")
        half = Vector(properties.size) * 0.5
        matrix = cage_local_matrix(target, controller)

        def deformed_cage_point(point):
            return deform_point_local(
                point,
                properties.size,
                properties.deform_type,
                properties.strength,
                properties.factor,
                properties.direction,
                properties.mode,
                properties.origin,
                properties.preserve_volume,
                properties.top_scale,
                properties.bottom_scale,
                properties.top_offset,
                properties.bottom_offset,
            )

        # Draw the editable cage from the same formula as the geometry. The
        # frame therefore shows the final bend/twist/profile instead of an
        # undeformed reference box.
        steps = 40
        rail_indices = tuple((index, index + 1) for index in range(steps))
        corner_signs = ((-1, -1), (-1, 1), (1, 1), (1, -1))
        for x_sign, z_sign in corner_signs:
            rail_local = [
                deformed_cage_point((
                    x_sign * half.x,
                    -half.y + properties.size.y * index / steps,
                    z_sign * half.z,
                ))
                for index in range(steps + 1)
            ]
            rail = self.matrix_calculation(matrix, rail_local)
            self.draw_smooth_3d_shader(
                rail, rail_indices, (0.0, 0.72, 1.0, 0.78))

        ring_indices = ((0, 1), (1, 2), (2, 3), (3, 0))
        for ring_t in (0.0, 0.25, 0.5, 0.75, 1.0):
            ring_y = -half.y + properties.size.y * ring_t
            ring_local = [
                deformed_cage_point((
                    x_sign * half.x, ring_y, z_sign * half.z))
                for x_sign, z_sign in corner_signs
            ]
            ring = self.matrix_calculation(matrix, ring_local)
            self.draw_smooth_3d_shader(
                ring, ring_indices, (0.0, 0.72, 1.0, 0.72))

        if properties.show_boundary_handles:
            for side, color in (
                    ("TOP", (1.0, 0.82, 0.05, 0.9)),
                    ("BOTTOM", (1.0, 0.55, 0.02, 0.9))):
                boundary, handle = cage_boundary_points_local(properties, side)
                connector = self.matrix_calculation(matrix, (boundary, handle))
                self.draw_smooth_3d_shader(
                    connector, ((0, 1),), color)

        if properties.deform_type == "BEND":
            rail_offsets = ((0.0, 0.0),)
        elif properties.deform_type in {"TWIST", "TAPER"}:
            rail_offsets = tuple(
                (x * half.x * 0.65, z * half.z * 0.65)
                for x, z in ((-1, -1), (-1, 1), (1, -1), (1, 1))
            )
        else:
            rail_offsets = (
                (0.0, 0.0),
                (half.x * 0.65, 0.0),
                (0.0, half.z * 0.65),
            )

        guide_indices = tuple((index, index + 1) for index in range(steps))
        endpoints = []
        for rail_x, rail_z in rail_offsets:
            guide_local = [
                deformed_cage_point(
                    (
                        rail_x,
                        -half.y + properties.size.y * index / steps,
                        rail_z,
                    )
                )
                for index in range(steps + 1)
            ]
            guide = self.matrix_calculation(matrix, guide_local)
            self.draw_smooth_3d_shader(
                guide, guide_indices, (1.0, 0.28, 0.02, 0.95))
            endpoints.append(guide[-1])
        self.draw_3d_shader(
            endpoints, (), (1.0, 0.55, 0.05, 1.0),
            shader_name="UNIFORM_COLOR", draw_type="POINTS")
        self._shader_set_prop_()
        return True

    def draw_bound_box(self):
        self._set_front_()
        mat = Matrix.Translation(Vector((0.0025, 0.0025, 0.0025))) @ self.obj_matrix_world
        coords = self.matrix_calculation(mat, self.tow_co_to_coordinate(self.modifier_bound_co))
        self.draw_smooth_3d_shader(coords, self.G_INDICES, self.pref.bound_box_color)
        self._shader_set_prop_()

    def draw_other_stage_bounds(self):
        if not getattr(self.pref, "show_other_stage_bounds", True):
            return
        obj = self.obj
        active = self.modifier
        if not obj or not active:
            return
        active_pointer = int(active.as_pointer())
        colors = (
            (0.20, 0.65, 1.00, 0.16),
            (1.00, 0.55, 0.20, 0.16),
            (0.55, 0.90, 0.35, 0.16),
            (0.75, 0.45, 1.00, 0.16),
        )
        for stage in StageCache.stages_for(obj):
            if stage.modifier_pointer == active_pointer:
                continue
            coords = self.matrix_calculation(
                self.obj_matrix_world,
                self.tow_co_to_coordinate(stage.input_bounds),
            )
            color = colors[stage.simple_index % len(colors)]
            self.draw_smooth_3d_shader(coords, self.G_INDICES, color)

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
                            shader_name="UNIFORM_COLOR", draw_type="POINTS")
        self.draw_3d_shader([up_point], (), (1, 0, 0, 0.5),
                            shader_name="UNIFORM_COLOR", draw_type="POINTS")
        self._shader_set_prop_()

    def draw_deform_mesh(self):
        self._set_front_()
        deform_data = self.G_DeformDrawData
        # draw deform mesh
        if (
                "simple_deform_bound_data" in deform_data and
                self.pref.update_deform_wireframe
        ):
            self._set_front_()
            data = deform_data["simple_deform_bound_data"]
            # The preview is intentionally rate-limited. Keep the last complete
            # frame visible for the same object/modifier until its replacement
            # is ready, instead of blinking off between mouse events.
            if self.preview_data_matches_context(data):
                self.draw_smooth_3d_shader(
                    data["positions"], data["indices"],
                    self.pref.deform_wireframe_color)
            self._shader_set_prop_()
        self._shader_set_prop_()

    def draw_origin_error(self):
        self._set_front_()
        ...
        self._shader_set_prop_()
