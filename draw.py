import blf
import logging
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, Matrix

from .utils import GizmoUtils
from .stages import StageCache


_CAGE_DEFORM_ORDER = ("BEND", "TWIST", "TAPER", "STRETCH")
_LOGGER = logging.getLogger(__name__)


def _cage_deform_types(properties):
    legacy_type = getattr(properties, "deform_type", "BEND")
    try:
        present = set(getattr(properties, "deform_types"))
    except (AttributeError, TypeError, ValueError):
        present = {legacy_type}
    try:
        muted = set(getattr(properties, "muted_deform_types"))
    except (AttributeError, TypeError, ValueError):
        muted = set()
    return present.difference(muted).intersection(_CAGE_DEFORM_ORDER)


def _depth_cued_line_colors(
        positions, indices, view_matrix, color, far_strength=0.22):
    """Fade far cage segments while retaining their X-ray readability."""
    positions = tuple(positions)
    indices = tuple(indices)
    color = tuple(float(component) for component in color)
    if len(color) != 4 or not positions:
        return tuple(color for _position in positions)
    try:
        depths = tuple(
            float((view_matrix @ (
                (Vector(positions[first]) + Vector(positions[second])) * 0.5
            ))[2])
            for first, second in indices
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        return tuple(color for _position in positions)
    if not depths:
        return tuple(color for _position in positions)
    minimum = min(depths)
    span = max(depths) - minimum
    if span <= 1.0e-7:
        return tuple(color for _position in positions)

    far_strength = min(max(float(far_strength), 0.0), 1.0)
    colors = [color for _position in positions]
    for (first, second), depth in zip(indices, depths):
        depth_factor = (depth - minimum) / span
        alpha = color[3] * (
            far_strength + (1.0 - far_strength) * depth_factor)
        segment_color = (color[0], color[1], color[2], alpha)
        colors[first] = segment_color
        colors[second] = segment_color
    return tuple(colors)


def _curve_cage_layer_positions(
        station_factors, range_start, range_end, epsilon=1.0e-5):
    """Separate stable structural rings from movable effect-range caps."""
    structural = tuple(sorted(set((
        0.0,
        1.0,
        *(min(max(float(factor), 0.0), 1.0)
          for factor in station_factors),
    ))))
    range_start = min(max(float(range_start), 0.0), 1.0)
    range_end = min(max(float(range_end), 0.0), 1.0)
    if range_start > range_end:
        range_start, range_end = range_end, range_start
    caps = []
    if range_start > epsilon:
        caps.append(("BOTTOM", range_start))
    if range_end < 1.0 - epsilon:
        caps.append(("TOP", range_end))
    return structural, tuple(caps)


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
        cls.draw_smooth_3d_shader_colors(
            pos, indices, [color for _ in pos])

    @classmethod
    def draw_smooth_3d_shader_colors(cls, pos, indices, colors):
        shader = cls.get_shader("POLYLINE_SMOOTH_COLOR")
        batch = batch_for_shader(
            shader, "LINES",
            {"pos": pos, "color": colors},
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
        return self.poll_simple_deform_public(bpy.context)

    def refresh_legacy_wireframe_preview(self):
        """Refresh the optional legacy preview only after its input changed."""
        if not self.pref.update_deform_wireframe:
            return
        if not self.active_modifier_is_simple_deform:
            return
        data = self.G_DeformDrawData.get("simple_deform_bound_data")
        try:
            context_changed = not self.preview_data_matches_context(data)
            stale = (
                context_changed or
                data.get("signature") != self.preview_signature()
            )
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            context_changed = True
            stale = True
        if not stale:
            return
        # Only a new object/modifier needs the expensive stage evaluator.
        # Parameter drags reuse the cached input bounds and let the preview's
        # own FPS limiter decide when to replace the last complete frame.
        if context_changed and not self.update_multiple_modifiers_data():
            return
        self.update_deform_wireframe(force=context_changed)


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
        try:
            from .cage_deform import resolve_context_deform
            target, modifier, controller = resolve_context_deform(
                bpy.context, fallback=False)
            if target and modifier and controller:
                ob = target
        except (ImportError, AttributeError, ReferenceError, RuntimeError,
                TypeError, ValueError):
            pass
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
                _LOGGER.debug("Simple Deform Helper draw: %s", message)
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
            self.refresh_legacy_wireframe_preview()
            self.draw_deform_mesh()
            self.draw_limits_line()
            self.draw_limits_bound_box()

            self.draw_text_handler()
        elif self.poll_simple_deform_show_bend_axis_witch(context):
            self.draw_bound_box()

    def _draw_other_cage_previews(
            self, context, target, active_modifier, active_controller):
        """Draw dimmed, selectable previews for the other managed cages.

        The active stage keeps the detailed cage below. Standard and Shear
        stages use a lightweight rail/ring preview, while FFD stages retain
        their complete lattice grid so neighboring chain segments remain
        visually continuous and distinguishable after switching stages.
        """
        from .cage_deform import cage_local_matrix
        from .cage_deform.core import (
            CONTROLLER_STYLES,
            cage_modifiers,
            find_controller,
            ordered_deform_types,
        )
        from .cage_deform.gizmos import (
            cage_preview_wire_indices,
            cage_preview_wire_vertices,
            ffd_wire_geometry,
        )
        active_properties = getattr(
            active_controller, "sdh_cage_deform", None)
        if not getattr(active_properties, "show_other_cages", True):
            return

        # Keep inactive previews deliberately quieter than the active cage.
        # The RGB values still follow each operation's controller type color.
        preview_alpha = 0.19
        ring_alpha = 0.12
        steps = 12
        ring_positions = (0.0, 0.5, 1.0)
        rail_indices, ring_indices = cage_preview_wire_indices(
            steps=steps, ring_positions=ring_positions)

        rail_positions = []
        rail_colors = []
        rail_segments = []
        ring_positions_world = []
        ring_colors = []
        ring_segments = []

        def extend_geometry(
                positions, colors, segments, vertices, indices, color):
            offset = len(positions)
            positions.extend(vertices)
            colors.extend(color for _vertex in vertices)
            segments.extend(
                (offset + first, offset + second)
                for first, second in indices)

        for stage_modifier in cage_modifiers(target):
            if stage_modifier == active_modifier or not stage_modifier.show_viewport:
                continue
            stage_controller = find_controller(target, stage_modifier)
            if stage_controller is None:
                continue
            properties = getattr(stage_controller, "sdh_cage_deform", None)
            if properties is None or not properties.show_cage:
                continue

            active_types = _cage_deform_types(properties)
            ordered_types = tuple(
                name for name in ordered_deform_types(properties)
                if name in active_types)
            primary_type = (
                ordered_types[0] if ordered_types else
                getattr(properties, "deform_type", "BEND")
            )
            style = CONTROLLER_STYLES.get(
                primary_type,
                CONTROLLER_STYLES["BEND"],
            )
            rgb = style[1][:3]
            matrix = cage_local_matrix(target, stage_controller)
            if str(getattr(properties, "cage_type", "STANDARD")) == "FFD":
                wire_local, wire_indices = ffd_wire_geometry(
                    properties, effective=True)
                wire = self.matrix_calculation(matrix, wire_local)
                extend_geometry(
                    rail_positions, rail_colors, rail_segments,
                    wire, wire_indices, (*rgb, preview_alpha))
                continue
            try:
                preview_key = ("PREVIEW", int(stage_controller.as_pointer()))
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                preview_key = ("PREVIEW", id(stage_controller))
            wire_local = cage_preview_wire_vertices(
                properties, steps=steps, ring_positions=ring_positions,
                throttle_key=preview_key)
            wire = self.matrix_calculation(matrix, wire_local)
            extend_geometry(
                rail_positions, rail_colors, rail_segments,
                wire, rail_indices, (*rgb, preview_alpha))
            extend_geometry(
                ring_positions_world, ring_colors, ring_segments,
                wire, ring_indices, (*rgb, ring_alpha))

        if rail_positions:
            self.draw_smooth_3d_shader_colors(
                rail_positions, rail_segments, rail_colors)
        if ring_positions_world:
            self.draw_smooth_3d_shader_colors(
                ring_positions_world, ring_segments, ring_colors)

    def draw_cage_deform(self, context):
        from .cage_deform import (
            cage_boundary_points_local,
            cage_local_matrix,
            curve_effect_range,
            resolve_context_deform,
        )
        from .cage_deform.gizmos import (
            cage_preview_guide_geometry,
            cage_preview_geometry_state,
            cage_preview_ring_vertices,
            cage_preview_wire_indices,
            cage_preview_wire_vertices,
            ffd_wire_geometry,
        )
        from .cage_deform.viewport import cage_overlay_depth_test
        target, modifier, controller = resolve_context_deform(
            context, fallback=False)
        if not target or not modifier or not controller:
            return False
        properties = controller.sdh_cage_deform
        enabled_types = _cage_deform_types(properties)
        if not properties.show_cage:
            # ``Show Cage`` controls the active editing preview.  Keep the
            # optional stack overview available so users can still locate and
            # switch to another stage when the active one is muted.
            gpu.state.line_width_set(1.5)
            gpu.state.blend_set("ALPHA")
            gpu.state.depth_test_set(cage_overlay_depth_test())
            self._draw_other_cage_previews(
                context, target, modifier, controller)
            self._shader_set_prop_()
            return True

        bend_trend_mode = (
            properties.show_axis_gizmo and "BEND" in enabled_types)

        # Cage previews share the traditional In Front preference. When users
        # disable it, the controlled object naturally occludes them.
        gpu.state.line_width_set(2.0)
        gpu.state.blend_set("ALPHA")
        gpu.state.depth_test_set(cage_overlay_depth_test())

        self._draw_other_cage_previews(
            context, target, modifier, controller)

        cage_alpha = 0.38
        ring_alpha = 0.32
        guide_alpha = 0.42
        boundary_alpha = 0.55

        half = Vector(properties.size) * 0.5
        matrix = cage_local_matrix(target, controller)
        cage_type = str(getattr(properties, "cage_type", "STANDARD"))
        is_curve = cage_type == "CURVE"
        view_matrix = getattr(
            getattr(context, "region_data", None), "view_matrix", None)

        # Trend selection and ordinary editing share this exact cached sample.
        # The chooser therefore previews the current combined deformation and
        # never overlays the old undeformed reference box.
        steps = 24
        effect_caps = ()
        if is_curve:
            range_start, range_end = curve_effect_range(properties)
            ring_positions, cap_positions = _curve_cage_layer_positions(
                (
                    float(station.factor)
                    for station in getattr(properties, "curve_stations", ())
                ),
                range_start,
                range_end,
            )
            cap_colors = {
                "BOTTOM": (
                    1.0, 0.55, 0.02, min(1.0, boundary_alpha + 0.12)),
                "TOP": (
                    1.0, 0.82, 0.05, min(1.0, boundary_alpha + 0.12)),
            }
            effect_caps = tuple(
                (factor, cap_colors[side])
                for side, factor in cap_positions
            )
        else:
            ring_positions = (0.0, 0.25, 0.5, 0.75, 1.0)
        preview_state = cage_preview_geometry_state(properties)
        if cage_type == "FFD":
            wire_local, wire_indices = ffd_wire_geometry(properties)
            wire = self.matrix_calculation(matrix, wire_local)
            effective_local, _effective_indices = ffd_wire_geometry(
                properties, effective=True)
            effective_wire = self.matrix_calculation(matrix, effective_local)
            if any(
                    (Vector(authored) - Vector(effective)).length > 1.0e-7
                    for authored, effective in zip(wire, effective_wire)
            ):
                # Weight is a deformation mask, not a handle sensitivity.
                # Keep the authored cage under the cursor and show the actual
                # evaluated lattice as a quiet secondary reference.
                self.draw_smooth_3d_shader(
                    effective_wire, wire_indices,
                    (1.0, 0.58, 0.18, 0.22))
            self.draw_smooth_3d_shader(
                wire, wire_indices, (0.0, 0.72, 1.0, cage_alpha))
        else:
            try:
                active_key = ("ACTIVE_WIRE", int(controller.as_pointer()))
            except (AttributeError, ReferenceError, RuntimeError, TypeError,
                    ValueError):
                active_key = ("ACTIVE_WIRE", id(controller))
            wire_local = cage_preview_wire_vertices(
                properties, steps=steps, ring_positions=ring_positions,
                preview_state=preview_state, throttle_key=active_key)
            rail_indices, ring_indices = cage_preview_wire_indices(
                steps=steps, ring_positions=ring_positions)
            wire = self.matrix_calculation(matrix, wire_local)
            if is_curve and view_matrix is not None:
                self.draw_smooth_3d_shader_colors(
                    wire,
                    rail_indices,
                    _depth_cued_line_colors(
                        wire, rail_indices, view_matrix,
                        (0.0, 0.72, 1.0, cage_alpha)),
                )
                self.draw_smooth_3d_shader_colors(
                    wire,
                    ring_indices,
                    _depth_cued_line_colors(
                        wire, ring_indices, view_matrix,
                        (0.0, 0.72, 1.0, ring_alpha)),
                )
            else:
                self.draw_smooth_3d_shader(
                    wire, rail_indices, (0.0, 0.72, 1.0, cage_alpha))
                self.draw_smooth_3d_shader(
                    wire, ring_indices, (0.0, 0.72, 1.0, ring_alpha))

        # Curve effect limits are not a second cage.  Draw only their two cap
        # loops, in the same top/bottom colors as the boundary handles.  The
        # stable full-source cage remains blue and its rails are sampled once.
        if effect_caps:
            gpu.state.line_width_set(2.5)
            for factor, color in effect_caps:
                cap_local = cage_preview_ring_vertices(
                    properties, (factor,), preview_state=preview_state)
                cap = self.matrix_calculation(matrix, cap_local)
                cap_indices = tuple(
                    (index, index + 1)
                    for index in range(0, len(cap), 2))
                if view_matrix is not None:
                    self.draw_smooth_3d_shader_colors(
                        cap,
                        cap_indices,
                        _depth_cued_line_colors(
                            cap, cap_indices, view_matrix, color,
                            far_strength=0.32),
                    )
                else:
                    self.draw_smooth_3d_shader(cap, cap_indices, color)
            gpu.state.line_width_set(2.0)

        if bend_trend_mode:
            self._shader_set_prop_()
            return True

        if properties.show_boundary_handles:
            for side, color in (
                    ("TOP", (1.0, 0.82, 0.05, boundary_alpha)),
                    ("BOTTOM", (1.0, 0.55, 0.02, boundary_alpha))):
                boundary, handle = cage_boundary_points_local(properties, side)
                connector = self.matrix_calculation(matrix, (boundary, handle))
                self.draw_smooth_3d_shader(
                    connector, ((0, 1),), color)

        rail_offsets = []
        if not enabled_types or enabled_types & {"BEND", "STRETCH"}:
            rail_offsets.append((0.0, 0.0))
        if enabled_types & {"TWIST", "TAPER"}:
            rail_offsets.extend(
                (x * half.x * 0.65, z * half.z * 0.65)
                for x, z in ((-1, -1), (-1, 1), (1, -1), (1, 1))
            )
        if "STRETCH" in enabled_types:
            rail_offsets.extend((
                (half.x * 0.65, 0.0),
                (0.0, half.z * 0.65),
            ))
        rail_offsets = tuple(dict.fromkeys(rail_offsets))

        guide_local, guide_indices, endpoint_indices = (
            cage_preview_guide_geometry(
                properties, rail_offsets, steps=steps,
                preview_state=preview_state))
        guide = self.matrix_calculation(matrix, guide_local)
        if guide:
            self.draw_smooth_3d_shader(
                guide, guide_indices, (1.0, 0.28, 0.02, guide_alpha))
        endpoints = tuple(guide[index] for index in endpoint_indices)
        self.draw_3d_shader(
            endpoints, (), (1.0, 0.55, 0.05, min(1.0, guide_alpha + 0.35)),
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
