"""Screen-space projection cache shared by FFD click and box selection."""
from __future__ import annotations

import math
from collections import OrderedDict


def _quantized(value, digits=6):
    return round(float(value), digits)


class FFDProjectedEntityCache:
    """Cache projected FFD entities by geometry, view probe, and mode."""

    def __init__(self, limit=32):
        self.limit = max(int(limit), 1)
        self._values = OrderedDict()
        self.hits = 0
        self.misses = 0

    def clear(self):
        self._values.clear()
        self.hits = 0
        self.misses = 0

    def info(self):
        return {
            "size": len(self._values),
            "hits": self.hits,
            "misses": self.misses,
        }

    @staticmethod
    def _owner_pointer(properties):
        try:
            return int(properties.as_pointer())
        except (AttributeError, ReferenceError, TypeError, ValueError):
            return id(properties)

    @staticmethod
    def _geometry_signature(properties, resolution):
        point_count = math.prod(resolution)
        points = getattr(properties, "ffd_points", ())
        offsets = tuple(
            tuple(_quantized(component, 7)
                  for component in points[index].offset)
            for index in range(min(len(points), point_count))
        )
        return (
            FFDProjectedEntityCache._owner_pointer(properties),
            tuple(int(value) for value in resolution),
            bool(getattr(properties, "ffd_use_outside", False)),
            tuple(_quantized(value, 7)
                  for value in getattr(properties, "size", ())),
            offsets,
        )

    @staticmethod
    def _probe_indices(resolution, point_index):
        indices = {
            point_index(u, v, w, resolution)
            for u in (0, resolution[0] - 1)
            for v in (0, resolution[1] - 1)
            for w in (0, resolution[2] - 1)
        }
        center = tuple(max((value - 1) // 2, 0) for value in resolution)
        indices.add(point_index(*center, resolution))
        return tuple(sorted(indices))

    @staticmethod
    def _view_probe(project_point, indices, screen_value):
        values = []
        for index in indices:
            screen, depth = screen_value(project_point(index))
            values.append(
                None if screen is None else (
                    _quantized(screen.x),
                    _quantized(screen.y),
                    None if depth is None else _quantized(depth, 7),
                )
            )
        return tuple(values)

    def get(
            self, properties, project_point, mode, *, builder,
            resolution_function, point_index_function, screen_value_function,
            line_ratio=0.60, face_ratio=0.35):
        resolution = tuple(resolution_function(properties))
        key = (
            self._geometry_signature(properties, resolution),
            str(mode),
            _quantized(line_ratio),
            _quantized(face_ratio),
            self._view_probe(
                project_point,
                self._probe_indices(resolution, point_index_function),
                screen_value_function,
            ),
        )
        cached = self._values.get(key)
        if cached is not None:
            self.hits += 1
            self._values.move_to_end(key)
            return cached

        self.misses += 1
        result = builder(
            properties,
            project_point,
            mode,
            line_ratio=line_ratio,
            face_ratio=face_ratio,
        )
        self._values[key] = result
        self._values.move_to_end(key)
        while len(self._values) > self.limit:
            self._values.popitem(last=False)
        return result


projected_entity_cache = FFDProjectedEntityCache()
