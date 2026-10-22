"""CPU scheduling policy, independent of model weights and recognition thresholds."""


def runtime_plan(cpu_workers, working_budget, largest_asset_bytes, cached_sessions):
    # Reserve estimated graph/session storage AND concurrent activation space.
    # This is admission plus live RSS monitoring, never an OS memory guarantee.
    lanes = max(1, min(5, cpu_workers, cached_sessions,
                       int(working_budget * .40) // max(1, largest_asset_bytes * 4)))
    return {"version": "bounded-cpu-v2", "cpu_budget": cpu_workers,
            "image_workers": lanes, "image_intra_op_threads": max(1, cpu_workers // lanes),
            "point_intra_op_threads": cpu_workers, "normal_workers": cpu_workers,
            "inter_op_threads": 1, "execution_mode": "sequential",
            "allow_spinning": False,
            "admission_scope": "estimated graph/activation bytes plus sampled combined RSS"}
