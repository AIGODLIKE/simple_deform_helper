from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import bpy
from mathutils import Vector


RUNTIME_STAGE_OBJECT = "_simple_deform_helper_runtime_stage_object"


def _pointer(value) -> int:
    try:
        return int(value.as_pointer())
    except (AttributeError, ReferenceError, TypeError):
        return 0


def hide_runtime_object(obj, scene=None) -> bool:
    """Hide a transient evaluator without excluding it from evaluation."""
    view_layers = tuple(getattr(scene, "view_layers", ())) if scene else ()
    try:
        if view_layers:
            for view_layer in view_layers:
                obj.hide_set(True, view_layer=view_layer)
        else:
            obj.hide_set(True)
        return True
    except (ReferenceError, RuntimeError, TypeError):
        return False


def _freeze_bounds(minimum: Vector, maximum: Vector):
    minimum = Vector(minimum)
    maximum = Vector(maximum)
    minimum.freeze()
    maximum.freeze()
    return minimum, maximum


def _bounds_from_points(points: Iterable, fallback=None):
    points = [Vector(point[:3]) for point in points]
    if not points:
        return fallback

    # An invalid Object.bound_box is eight copies of (-1, -1, -1).
    if len(points) == 8 and all(point == points[0] for point in points):
        if points[0] == Vector((-1.0, -1.0, -1.0)):
            return fallback

    minimum = Vector((
        min(point.x for point in points),
        min(point.y for point in points),
        min(point.z for point in points),
    ))
    maximum = Vector((
        max(point.x for point in points),
        max(point.y for point in points),
        max(point.z for point in points),
    ))
    return _freeze_bounds(minimum, maximum)


def _object_fallback_bounds(obj):
    bounds = _bounds_from_points(getattr(obj, "bound_box", ()))
    if bounds is not None:
        return bounds
    return _freeze_bounds(Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 0.0)))


def render_job_running() -> bool:
    is_job_running = getattr(bpy.app, "is_job_running", None)
    if not is_job_running:
        return False
    for job_type in ("RENDER", "RENDER_PREVIEW"):
        try:
            if is_job_running(job_type):
                return True
        except (TypeError, ValueError):
            continue
    return False


@dataclass(frozen=True)
class DeformStage:
    object_pointer: int
    modifier_pointer: int
    stack_index: int
    simple_index: int
    simple_count: int
    modifier_name: str
    input_bounds: tuple


class StageCache:
    """Runtime-only modifier-stage bounds for the active object.

    A stage describes the geometry immediately before a Simple Deform modifier.
    The cache is keyed by RNA pointers so duplicate modifier names are safe.
    """

    _stages_by_object: dict[int, tuple[DeformStage, ...]] = {}
    _stages_by_modifier: dict[tuple[int, int], DeformStage] = {}
    _last_error: str | None = None

    @classmethod
    def clear(cls, obj=None):
        if obj is None:
            cls._stages_by_object.clear()
            cls._stages_by_modifier.clear()
            cls._last_error = None
            return

        object_pointer = _pointer(obj)
        stages = cls._stages_by_object.pop(object_pointer, ())
        for stage in stages:
            cls._stages_by_modifier.pop(
                (stage.object_pointer, stage.modifier_pointer), None)

    @classmethod
    def stages_for(cls, obj) -> tuple[DeformStage, ...]:
        return cls._stages_by_object.get(_pointer(obj), ())

    @classmethod
    def stage_for(cls, obj, modifier) -> DeformStage | None:
        return cls._stages_by_modifier.get((_pointer(obj), _pointer(modifier)))

    @classmethod
    def bounds_for(cls, obj, modifier):
        stage = cls.stage_for(obj, modifier)
        return stage.input_bounds if stage else None

    @classmethod
    def position_for(cls, obj, modifier):
        stage = cls.stage_for(obj, modifier)
        if not stage:
            modifiers = tuple(
                mod for mod in getattr(obj, "modifiers", ())
                if mod.type == "SIMPLE_DEFORM"
            )
            try:
                return modifiers.index(modifier) + 1, len(modifiers)
            except ValueError:
                return 0, len(modifiers)
        return stage.simple_index + 1, stage.simple_count

    @classmethod
    def rebuild(cls, context, obj) -> bool:
        if obj is None or render_job_running():
            return False
        if obj.type not in {"MESH", "LATTICE", "CURVE", "FONT"}:
            cls.clear()
            return False

        original_modifiers = tuple(obj.modifiers)
        simple_indices = tuple(
            index for index, modifier in enumerate(original_modifiers)
            if modifier.type == "SIMPLE_DEFORM"
        )
        if not simple_indices:
            cls.clear()
            return False

        collection = getattr(context, "collection", None)
        if collection is None:
            layer_collection = getattr(context.view_layer, "active_layer_collection", None)
            collection = getattr(layer_collection, "collection", None)
        if collection is None:
            return False

        clone = None
        new_stages = []
        try:
            clone = obj.copy()
            clone.name = f"{obj.name}_SDH_STAGE_EVAL"
            clone[RUNTIME_STAGE_OBJECT] = True
            clone.hide_render = True
            clone.hide_select = True
            clone.display_type = "BOUNDS"
            try:
                clone.animation_data_clear()
            except (AttributeError, RuntimeError):
                pass
            collection.objects.link(clone)
            hide_runtime_object(clone, getattr(context, "scene", None))

            clone_modifiers = tuple(clone.modifiers)
            depsgraph = context.evaluated_depsgraph_get()
            simple_count = len(simple_indices)

            for simple_index, stack_index in enumerate(simple_indices):
                for index, clone_modifier in enumerate(clone_modifiers):
                    clone_modifier.show_viewport = (
                        index < stack_index and
                        original_modifiers[index].show_viewport
                    )

                context.view_layer.update()
                evaluated = clone.evaluated_get(depsgraph)
                bounds = _bounds_from_points(
                    evaluated.bound_box,
                    fallback=_object_fallback_bounds(obj),
                )
                original_modifier = original_modifiers[stack_index]
                new_stages.append(DeformStage(
                    object_pointer=_pointer(obj),
                    modifier_pointer=_pointer(original_modifier),
                    stack_index=stack_index,
                    simple_index=simple_index,
                    simple_count=simple_count,
                    modifier_name=original_modifier.name,
                    input_bounds=bounds,
                ))

        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            if message != cls._last_error:
                print("Simple Deform Helper stage evaluation:", message)
                cls._last_error = message
            return False
        finally:
            if clone is not None:
                try:
                    bpy.data.objects.remove(clone, do_unlink=True)
                except (ReferenceError, RuntimeError):
                    pass

        # Only the active object's stages are drawn. Keeping one object also
        # prevents pointer-keyed cache entries from accumulating as users move
        # through large scenes.
        cls.clear()
        stages = tuple(new_stages)
        cls._stages_by_object[_pointer(obj)] = stages
        for stage in stages:
            cls._stages_by_modifier[
                (stage.object_pointer, stage.modifier_pointer)
            ] = stage
        cls._last_error = None
        return True

    @classmethod
    def cleanup_runtime_objects(cls):
        for obj in tuple(bpy.data.objects):
            try:
                is_runtime = bool(obj.get(RUNTIME_STAGE_OBJECT, False))
            except ReferenceError:
                continue
            if is_runtime:
                bpy.data.objects.remove(obj, do_unlink=True)
