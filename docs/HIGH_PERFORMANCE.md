# High Performance reconstruction

The reconstruction worker now uses an adaptive, evidence-preserving pipeline.

* CPU workers default to all logical processors except one. Independent storeys
  run concurrently, while BLAS thread pools are limited so nested parallelism
  does not oversubscribe the machine. Wall evidence, opening detection, and
  stair sampling also use the resolved worker count.
* Height levels are found with a streaming histogram over every source Z value.
  Only spatially distributed representatives near the detected peaks are
  retained for footprint fitting.
* Detection budgets grow up to 5,000,000 points, subject to a 20 GiB policy,
  the current available-RAM safety cap, source-cloud reservation, and bounded
  processing chunks. The policy is a ceiling, not a promise to allocate 20 GiB.
* Voxel indexing uses Open3D CUDA when an NVIDIA CUDA build is installed, or
  OpenCL double-precision kernels when a compatible GPU driver is available.
  CPU NumPy remains the deterministic fallback. Fitting, topology, and IFC
  construction remain CPU algorithms in this release.
* Every reconstruction records stage duration, process CPU time, RSS peak,
  available memory, source/sample counts, detected element counts, backend
  calls, and available GPU counters. The desktop writes
  `last-performance.json`; the CLI writes `performance.json`.

Use `--compare-budgets` with `demo`, `convert-xyz`, or `convert-e57` to run
250k, 500k, 1M, 2M, and 5M candidate budgets. The run stops after two
consecutive geometry-stable comparisons. This is a convergence diagnostic,
not a survey-accuracy certification; a registered or annotated reference is
still required for that claim.

For an optional Windows NVIDIA path, install a matching Open3D CUDA wheel in
the worker environment. AMD hardware can use the OpenCL path when its driver
exposes a double-precision GPU device.
