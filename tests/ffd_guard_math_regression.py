"""Pure regression checks for the FFD anti-foldover guard."""
from __future__ import annotations

import importlib.util
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "sdh_ffd_guard", SOURCE / "cage_deform" / "ffd_guard.py")
guard = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(guard)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


resolution = (2, 2, 2)
size = (2.0, 2.0, 2.0)
count = 8
zero = tuple((0.0, 0.0, 0.0) for _index in range(count))
influences = (1.0,) * count

identity_ratio = guard.minimum_jacobian_ratio(
    guard._effective_points(size, resolution, zero, influences),
    size,
    resolution,
)
check(abs(identity_ratio - 1.0) < 1.0e-8,
      f"identity FFD ratio drifted: {identity_ratio}")

translated = tuple((0.5, -0.25, 0.75) for _index in range(count))
translated_result, translated_fraction, _, _ = guard.clamp_offsets(
    size, resolution, zero, translated, influences)
check(translated_fraction == 1.0 and translated_result == translated,
      "rigid FFD translation was unexpectedly clamped")

# Collapse the top X edge through the bottom edge. The guard should retain the
# last positive cell Jacobian instead of allowing the lattice to invert.
folded = list(zero)
for index in (4, 6):
    folded[index] = (3.0, 0.0, 0.0)
for index in (5, 7):
    folded[index] = (-3.0, 0.0, 0.0)
folded_result, fraction, baseline_ratio, candidate_ratio = guard.clamp_offsets(
    size, resolution, zero, tuple(folded), influences)
safe_points = guard._effective_points(
    size, resolution, folded_result, influences)
safe_ratio = guard.minimum_jacobian_ratio(
    safe_points, size, resolution)
check(candidate_ratio < guard.MIN_JACOBIAN_RATIO,
      f"folded candidate unexpectedly passed: {candidate_ratio}")
check(baseline_ratio >= guard.MIN_JACOBIAN_RATIO,
      f"identity baseline rejected: {baseline_ratio}")
check(0.0 < fraction < 1.0,
      f"folded edit was not partially clamped: {fraction}")
check(safe_ratio >= guard.MIN_JACOBIAN_RATIO,
      f"clamped FFD remained unsafe: {safe_ratio}")

# A point edit only needs to inspect the cells touching that point. The local
# result must agree with the full-field result used for the safety contract.
local_ratio = guard.minimum_jacobian_ratio(
    safe_points, size, resolution, cell_indices=((0, 0, 0),))
check(abs(local_ratio - safe_ratio) < 1.0e-8,
      f"local Jacobian check drifted: {local_ratio} != {safe_ratio}")

cached_result, cached_fraction, cached_baseline, cached_candidate = (
    guard.clamp_offsets(
        size, resolution, zero, tuple(folded), influences,
        baseline_ratio=1.0))
check(cached_fraction == fraction and
      cached_baseline == 1.0 and
      cached_candidate == candidate_ratio and
      cached_result == folded_result,
      "cached baseline changed the FFD clamp result")

# Corner/center-only sampling can miss a negative Jacobian between samples.
# Keep this deliberately awkward field as a regression for the denser safety
# sample set used by the interactive guard.
interior_fold = (
    (-0.370769, -3.088915, 0.415240),
    (2.755720, -2.834296, -0.365851),
    (-2.126862, -0.057640, -0.925866),
    (-1.859408, -0.355702, -2.784000),
    (-2.414380, -0.063696, 0.828402),
    (-0.252568, -3.441626, 3.801318),
    (-0.634022, 0.900097, 3.445995),
    (1.199223, -0.532316, -1.896725),
)
coarse_ratio = guard.minimum_jacobian_ratio(
    interior_fold, size, resolution, samples=(0.0, 0.5, 1.0))
safe_ratio = guard.minimum_jacobian_ratio(
    interior_fold, size, resolution)
check(coarse_ratio >= guard.MIN_JACOBIAN_RATIO,
      f"interior-fold fixture no longer represents the old miss: {coarse_ratio}")
check(safe_ratio < guard.MIN_JACOBIAN_RATIO,
      f"dense Jacobian sampling missed an interior fold: {safe_ratio}")

print("SDH_FFD_GUARD_MATH::PASS")
