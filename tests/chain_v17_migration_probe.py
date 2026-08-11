"""Verify automatic, lossless migration of a historical v17 chain scene."""

from __future__ import annotations

import hashlib
import importlib
import math
import sys
from pathlib import Path

import bpy


SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE.name
sys.path.insert(0, str(SOURCE.parent))

GROUP_MARKER = "_sdh_cage_deform_group"
SOURCE_MIN = -3.0
SOURCE_MAX = 3.0
SOURCE_RADIUS = 0.65
RING_SIDES = 12
DENSE_STEP = 0.05
LIMIT_STEP = 0.005


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def boundaries_for(count, gap):
    segment = ((SOURCE_MAX - SOURCE_MIN) - gap * (count - 1)) / count
    return tuple(
        SOURCE_MIN + index * segment + index * gap
        for index in range(1, count)
    )


def y_values(boundaries):
    steps = int(round((SOURCE_MAX - SOURCE_MIN) / DENSE_STEP))
    values = {
        round(SOURCE_MIN + (SOURCE_MAX - SOURCE_MIN) * index / steps, 10)
        for index in range(steps + 1)
    }
    for boundary in boundaries:
        for offset in range(-3, 4):
            values.add(round(boundary + offset * LIMIT_STEP, 10))
    return tuple(sorted(values))


def ring_starts_for(count, gap):
    return {
        y: index * (RING_SIDES + 1)
        for index, y in enumerate(y_values(boundaries_for(count, gap)))
    }


def evaluated_world_points(target):
    bpy.context.view_layer.update()
    evaluated = target.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    try:
        matrix = evaluated.matrix_world
        return tuple(matrix @ vertex.co for vertex in mesh.vertices)
    finally:
        evaluated.to_mesh_clear()


def ring(points, starts, y):
    start = starts[round(float(y), 10)]
    return points[start:start + RING_SIDES + 1]


def limit(first, second, third):
    return first * 3.0 - second * 3.0 + third


def left_derivative(first, second, third):
    return (first * 2.5 - second * 4.0 + third * 1.5) / LIMIT_STEP


def right_derivative(first, second, third):
    return (first * -2.5 + second * 4.0 - third * 1.5) / LIMIT_STEP


def angle_degrees(left, right):
    if left.length <= 1.0e-10 or right.length <= 1.0e-10:
        return math.inf
    cosine = max(min(left.normalized().dot(right.normalized()), 1.0), -1.0)
    return math.degrees(math.acos(cosine))


def mean_radius(sample):
    center = sample[0]
    return sum((point - center).length for point in sample[1:]) / RING_SIDES


def seam_metrics(points, starts, boundary):
    left = tuple(
        ring(points, starts, boundary - offset * LIMIT_STEP)
        for offset in (1, 2, 3)
    )
    right = tuple(
        ring(points, starts, boundary + offset * LIMIT_STEP)
        for offset in (1, 2, 3)
    )
    exact = ring(points, starts, boundary)
    c0 = 0.0
    exact_residual = 0.0
    tangent_angle = 0.0
    tangent_speed = 0.0
    for slot in range(RING_SIDES + 1):
        left_limit = limit(left[0][slot], left[1][slot], left[2][slot])
        right_limit = limit(right[0][slot], right[1][slot], right[2][slot])
        c0 = max(c0, (right_limit - left_limit).length)
        exact_residual = max(
            exact_residual,
            (exact[slot] - left_limit).length,
            (exact[slot] - right_limit).length,
        )
        left_tangent = left_derivative(
            left[0][slot], left[1][slot], left[2][slot])
        right_tangent = right_derivative(
            right[0][slot], right[1][slot], right[2][slot])
        tangent_angle = max(
            tangent_angle, angle_degrees(left_tangent, right_tangent))
        tangent_speed = max(
            tangent_speed,
            abs(left_tangent.length - right_tangent.length) /
            max(left_tangent.length, right_tangent.length, 1.0e-10),
        )
    left_radius = limit(*(mean_radius(sample) for sample in left))
    right_radius = limit(*(mean_radius(sample) for sample in right))
    exact_radius = mean_radius(exact)
    radius_growth = max(
        right_radius - left_radius,
        exact_radius - max(left_radius, right_radius),
        0.0,
    )
    return {
        "source_y": boundary,
        "c0": max(c0, exact_residual),
        "c0_limits": c0,
        "c0_exact": exact_residual,
        "tangent_angle_deg": tangent_angle,
        "tangent_speed_change": tangent_speed,
        "radius_left": left_radius,
        "radius_right": right_radius,
        "radius_exact": exact_radius,
        "radius_growth": radius_growth,
        "radius_growth_relative": radius_growth /
        max(left_radius, SOURCE_RADIUS, 1.0e-10),
    }


def measure(target, points=None):
    count = int(target["_sdh_probe_count"])
    gap = float(target["_sdh_probe_gap"])
    starts = ring_starts_for(count, gap)
    if points is None:
        points = evaluated_world_points(target)
    check(len(points) == len(starts) * (RING_SIDES + 1),
          f"unexpected topology on {target.name}")
    seams = tuple(
        seam_metrics(points, starts, boundary)
        for boundary in boundaries_for(count, gap)
    )
    return {
        "seams": seams,
        "max_c0": max(item["c0"] for item in seams),
        "max_tangent_angle_deg": max(
            item["tangent_angle_deg"] for item in seams),
        "max_tangent_speed_change": max(
            item["tangent_speed_change"] for item in seams),
        "max_radius_growth_relative": max(
            item["radius_growth_relative"] for item in seams),
    }


def graph_fingerprint(group):
    nodes = tuple(sorted(
        (node.name, node.bl_idname, node.label)
        for node in group.nodes
    ))
    links = tuple(sorted(
        (link.from_node.name, link.from_socket.name,
         link.to_node.name, link.to_socket.name)
        for link in group.links
    ))
    payload = repr((nodes, links)).encode("utf-8")
    return {
        "name": group.name,
        "marker": int(group.get(GROUP_MARKER, -1)),
        "nodes": len(nodes),
        "links": len(links),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def managed_groups(targets):
    groups = []
    for target in targets:
        for modifier in target.modifiers:
            group = getattr(modifier, "node_group", None)
            if group is None or GROUP_MARKER not in group:
                continue
            if group not in groups:
                groups.append(group)
    return tuple(groups)


def max_point_delta(left, right):
    check(len(left) == len(right), "point snapshots have different lengths")
    return max(((a - b).length for a, b in zip(left, right)), default=0.0)


def raw_mesh_state(targets):
    return tuple(
        (
            target.name,
            tuple(tuple(float(value) for value in vertex.co)
                  for vertex in target.data.vertices),
            tuple(tuple(int(value) for value in edge.vertices)
                  for edge in target.data.edges),
            tuple(tuple(int(value) for value in polygon.vertices)
                  for polygon in target.data.polygons),
        )
        for target in targets
    )


def authored_state(deform, chain, targets):
    def floats(values):
        return tuple(float(value) for value in values)

    result = []
    for target in targets:
        stages = tuple(deform.cage_modifiers(target))
        records = []
        for modifier in stages:
            controller = deform.find_controller(target, modifier)
            check(controller is not None,
                  f"missing controller before migration: {modifier.name}")
            properties = controller.sdh_cage_deform
            chain_index = chain.stage_chain_index(modifier)
            records.append((
                modifier.name,
                modifier.node_group.name,
                controller.name,
                # Only the root transform is authored. Auto-reconnect derives
                # every downstream controller frame from the preceding cage,
                # so a graph repair may legitimately refine those values.
                floats(controller.location) if chain_index == 0 else None,
                floats(controller.rotation_euler) if chain_index == 0 else None,
                floats(properties.size),
                str(properties.mode),
                str(properties.origin),
                bool(properties.preserve_volume),
                tuple(sorted(properties.deform_types)),
                tuple(deform.core.ordered_deform_types(properties)),
                tuple(sorted(properties.muted_deform_types)),
                float(properties.bend_strength),
                float(properties.bend_direction),
                float(properties.twist_strength),
                float(properties.taper_factor),
                float(properties.stretch_factor),
                bool(properties.stage_enabled),
                floats(properties.top_scale),
                floats(properties.bottom_scale),
                floats(properties.top_offset),
                floats(properties.bottom_offset),
                chain.stage_chain_uuid(modifier),
                chain_index,
                chain.stage_chain_count(modifier),
                chain.stage_chain_mode(modifier),
                float(chain.stage_chain_gap(modifier)),
            ))
        result.append((
            target.name,
            tuple(modifier.name for modifier in target.modifiers),
            tuple(records),
        ))
    return tuple(result)


targets = tuple(sorted(
    (obj for obj in bpy.data.objects if obj.get("_sdh_migration_fixture", False)),
    key=lambda obj: obj.name,
))
check(targets, "no migration fixtures were found in the loaded .blend")
groups = managed_groups(targets)
check(groups, "loaded fixture has no managed node groups")

before_graphs = tuple(graph_fingerprint(group) for group in groups)
before_points = {target.name: evaluated_world_points(target) for target in targets}
before_metrics = {
    target.name: measure(target, before_points[target.name]) for target in targets
}
before_markers = tuple(sorted({item["marker"] for item in before_graphs}))

entry = bpy.context.preferences.addons.new()
entry.module = PACKAGE
addon = importlib.import_module(PACKAGE)
addon.register()
deform = importlib.import_module(f"{PACKAGE}.cage_deform")
chain = deform.chain

try:
    current_version = int(deform.GROUP_VERSION)
    before_authored_state = authored_state(deform, chain, targets)
    before_raw_mesh_state = raw_mesh_state(targets)
    skipped_upgrade_count = deform.upgrade_managed_stages()
    # Match the normal one-shot maintenance work performed after registration.
    chain.normalize_all_chain_metadata()
    deform.core.sync_all_controllers(pull_transform=True, sync_mode="timer")
    for target in targets:
        deform.core.flush_pending_chain_updates(target)
    bpy.context.view_layer.update()

    stale_groups = managed_groups(targets)
    stale_graphs = tuple(graph_fingerprint(group) for group in stale_groups)
    stale_points = {target.name: evaluated_world_points(target) for target in targets}
    stale_metrics = {
        target.name: measure(target, stale_points[target.name]) for target in targets
    }
    migrated_authored_state = authored_state(deform, chain, targets)
    migrated_raw_mesh_state = raw_mesh_state(targets)
    if migrated_authored_state != before_authored_state:
        for before_item, after_item in zip(
                before_authored_state, migrated_authored_state):
            if before_item != after_item:
                print(
                    "SDH_V17_MIGRATION::AUTHORED_DIFF::"
                    f"{before_item!r}::{after_item!r}")
                break
    check(migrated_authored_state == before_authored_state,
          "v17 migration changed authored stage or chain values")
    check(migrated_raw_mesh_state == before_raw_mesh_state,
          "v17 migration changed source mesh topology or coordinates")

    idempotent_upgrade_count = deform.upgrade_managed_stages()
    idempotent_graphs = tuple(
        graph_fingerprint(group) for group in managed_groups(targets))
    idempotent_points = {
        target.name: evaluated_world_points(target) for target in targets}
    check(idempotent_upgrade_count == 0,
          "a second migration pass rebuilt current node groups")
    check(idempotent_graphs == stale_graphs,
          "a second migration pass changed the managed graph")
    check(all(
        max_point_delta(stale_points[target.name],
                        idempotent_points[target.name]) < 1.0e-7
        for target in targets
    ), "a second migration pass changed evaluated geometry")

    same_marker_fixture = before_markers == (current_version,)
    if same_marker_fixture:
        # Reproduce the historical risk by forcing the migration that a
        # distinct node-group version would have triggered.
        for group in stale_groups:
            group[deform.GROUP_MARKER] = current_version - 1
        forced_upgrade_count = deform.upgrade_managed_stages()
        chain.normalize_all_chain_metadata()
        deform.core.sync_all_controllers(pull_transform=False)
        for target in targets:
            deform.core.flush_pending_chain_updates(target)
        bpy.context.view_layer.update()

        forced_groups = managed_groups(targets)
        forced_graphs = tuple(
            graph_fingerprint(group) for group in forced_groups)
        forced_points = {
            target.name: evaluated_world_points(target) for target in targets}
        forced_metrics = {
            target.name: measure(target, forced_points[target.name])
            for target in targets
        }
    else:
        # A real version bump should already have rebuilt the fixture above.
        forced_upgrade_count = 0
        forced_graphs = stale_graphs
        forced_points = stale_points
        forced_metrics = stale_metrics

    reports = []
    for target in targets:
        name = target.name
        report = {
            "target": name,
            "count": int(target["_sdh_probe_count"]),
            "gap": float(target["_sdh_probe_gap"]),
            "pattern": str(target["_sdh_probe_pattern"]),
            "config": str(target["_sdh_probe_config"]),
            "before": before_metrics[name],
            "stale": stale_metrics[name],
            "forced": forced_metrics[name],
            "before_to_stale_delta": max_point_delta(
                before_points[name], stale_points[name]),
            "stale_to_forced_delta": max_point_delta(
                stale_points[name], forced_points[name]),
        }
        reports.append(report)
        print(f"SDH_V17_MIGRATION::TARGET::{report!r}")

    same_marker_skipped = (
        same_marker_fixture and skipped_upgrade_count == 0)
    stale_graph_unchanged = (
        tuple(item["sha256"] for item in before_graphs) ==
        tuple(item["sha256"] for item in stale_graphs))
    forced_graph_changed = (
        tuple(item["sha256"] for item in stale_graphs) !=
        tuple(item["sha256"] for item in forced_graphs))
    bad_key, fixed_key = (
        ("stale", "forced") if same_marker_fixture else
        ("before", "stale")
    )
    fixed_gap_bend = tuple(
        report for report in reports
        if (
            report["gap"] > 0.0 and report["config"] == "BEND" and
            report[bad_key]["max_c0"] > 1.0e-2 and
            report[fixed_key]["max_c0"] < 5.0e-4
        )
    )
    version_bump_migrated = (
        not same_marker_fixture and skipped_upgrade_count > 0 and
        not stale_graph_unchanged)
    summary = {
        "current_group_version": current_version,
        "before_markers": before_markers,
        "groups": len(groups),
        "skipped_upgrade_count": skipped_upgrade_count,
        "forced_upgrade_count": forced_upgrade_count,
        "idempotent_upgrade_count": idempotent_upgrade_count,
        "authored_state_preserved": (
            migrated_authored_state == before_authored_state),
        "raw_mesh_preserved": migrated_raw_mesh_state == before_raw_mesh_state,
        "same_marker_skipped": same_marker_skipped,
        "version_bump_migrated": version_bump_migrated,
        "stale_graph_unchanged": stale_graph_unchanged,
        "forced_graph_changed": forced_graph_changed,
        "fixed_gap_bend_targets": tuple(
            report["target"] for report in fixed_gap_bend),
    }
    print(f"SDH_V17_MIGRATION::BEFORE_GRAPHS::{before_graphs!r}")
    print(f"SDH_V17_MIGRATION::STALE_GRAPHS::{stale_graphs!r}")
    print(f"SDH_V17_MIGRATION::FORCED_GRAPHS::{forced_graphs!r}")
    print(f"SDH_V17_MIGRATION::SUMMARY::{summary!r}")

    if same_marker_fixture:
        check(same_marker_skipped,
              "historical groups were not reproduced as a skipped migration")
        check(stale_graph_unchanged,
              "same-marker load unexpectedly rebuilt the historical graph")
        check(forced_upgrade_count > 0 and forced_graph_changed,
              "simulated version bump did not rebuild the historical graph")
    else:
        check(version_bump_migrated,
              "version bump did not rebuild the historical graph")
    check(fixed_gap_bend,
          "forced graph rebuild did not repair a historical gap Bend seam")
    print(
        "SDH_V17_MIGRATION::"
        f"{'RISK_REPRODUCED' if same_marker_fixture else 'VERSION_BUMP_APPLIED'}"
        "::PASS"
    )
finally:
    addon.unregister()
    bpy.context.preferences.addons.remove(entry)
