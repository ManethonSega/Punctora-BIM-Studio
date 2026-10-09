"""Point-budget convergence checks, distinct from survey accuracy."""
from dataclasses import replace
import numpy as np
from .reconstruction import ReconstructionSettings, reconstruct

BUDGETS = (250_000, 500_000, 1_000_000, 2_000_000, 5_000_000)


def _point(value):
    return np.asarray(value, dtype=float)


def _element_distance(kind, first, second):
    if kind == "walls":
        first_start, first_end = _point(first.start), _point(first.end)
        second_start, second_end = _point(second.start), _point(second.end)
        direct = max(np.linalg.norm(first_start-second_start), np.linalg.norm(first_end-second_end))
        reverse = max(np.linalg.norm(first_start-second_end), np.linalg.norm(first_end-second_start))
        return max(min(direct, reverse), abs(first.base-second.base), abs(first.height-second.height), abs(first.thickness-second.thickness))
    if kind == "stairs":
        return max(np.linalg.norm(_point(first.start)-_point(second.start)),
                   np.linalg.norm(_point(first.end)-_point(second.end)), abs(first.base-second.base),
                   abs(first.width-second.width), abs(first.rise-second.rise), abs(first.going-second.going),
                   abs(first.steps-second.steps)*max(first.going, second.going))
    if kind == "openings":
        return max(abs(first.offset-second.offset), abs(first.sill-second.sill),
                   abs(first.width-second.width), abs(first.height-second.height),
                   1.0 if first.kind != second.kind else 0.0)
    if kind == "storeys":
        return max(abs(first.elevation-second.elevation), abs(first.ceiling-second.ceiling))
    if kind == "slabs":
        return max(abs(first.base-second.base), abs(first.thickness-second.thickness))
    return 0.0


def geometry_change(previous, current):
    changes, counts_changed = [], False
    kinds = ("storeys", "walls", "slabs", "spaces", "openings", "stairs")
    for kind in kinds:
        first, second = list(getattr(previous, kind)), list(getattr(current, kind))
        if len(first) != len(second):
            counts_changed = True
            changes.append({"kind": kind, "previous_count": len(first), "current_count": len(second),
                            "maximum_geometry_change_m": None})
            continue
        distances = [_element_distance(kind, a, b) for a, b in zip(first, second)]
        changes.append({"kind": kind, "previous_count": len(first), "current_count": len(second),
                        "maximum_geometry_change_m": max(distances, default=0.0)})
    maximum = max((x["maximum_geometry_change_m"] or 0 for x in changes), default=0.0)
    return {"counts_changed": counts_changed, "classes": changes,
            "maximum_geometry_change_m": float(maximum)}


def compare_budgets(cloud, settings=None, storeys=None, budgets=BUDGETS, tolerance_m=.01,
                    progress=lambda *_: None, diagnostics=None):
    settings = settings or ReconstructionSettings()
    budgets = tuple(budgets)
    if not budgets or list(budgets) != sorted(set(budgets)) or any(not isinstance(x, int) or x < 30 for x in budgets):
        raise ValueError("Comparison budgets must be increasing integers >=30")
    if not np.isfinite(tolerance_m) or tolerance_m <= 0:
        raise ValueError("tolerance_m must be positive and finite")
    previous, stable_steps, runs = None, 0, []
    chosen = None
    for index, budget in enumerate(budgets):
        progress(10+int(index*65/len(budgets)), f"Comparing geometry at {budget:,} points")
        model = reconstruct(cloud, replace(settings, maximum_detection_points=budget,
                                           region_minimum_points=min(settings.region_minimum_points, budget)),
                            storeys=storeys, diagnostics=diagnostics)
        counts = {kind: len(getattr(model, kind)) for kind in ("storeys", "walls", "slabs", "spaces", "openings", "stairs")}
        change = geometry_change(previous, model) if previous is not None else None
        stable = change is not None and not change["counts_changed"] and change["maximum_geometry_change_m"] <= tolerance_m
        stable_steps = stable_steps+1 if stable else 0
        runs.append({"requested_points": budget, "counts": counts,
                     "effective_detection": model.metadata["detection"],
                     "performance": model.metadata["performance"],
                     "change_from_previous": change, "stable_with_previous": stable})
        previous, chosen = model, model
        if stable_steps >= 2:
            break
    report = {"budgets": list(budgets), "runs": runs,
              "tolerance_m": tolerance_m,
              "stop_reason": "two_consecutive_stable_comparisons" if stable_steps >= 2 else "maximum_budget_reached",
              "stable": stable_steps >= 2,
              "selected_requested_points": runs[-1]["requested_points"],
              "accuracy_verified": False,
              "scope": "candidate geometry stability; surveyed or annotated reference is required to establish accuracy"}
    chosen.metadata["budget_comparison"] = report
    return chosen, report
