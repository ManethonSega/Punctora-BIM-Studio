# High Performance reconstruction

The reconstruction worker now uses an adaptive, evidence-preserving pipeline.

* CPU workers default to all logical processors except one. Independent storeys
  run concurrently, while BLAS thread pools are limited so nested parallelism
  does not oversubscribe the machine. Wall evidence, opening detection, and
  stair sampling also use the resolved worker count.
* Height levels are found with a streaming histogram over every source Z value.
  Only spatially distributed representatives near the detected peaks are
  retained for footprint fitting.
* Detection budgets grow up to 5,000,000 points. Automatic planning may use at
  most 70% of the physical memory available at job start, after accounting for
  the current process and source-cloud working estimate. The remaining 30% is
  reserved for the OS, desktop and other applications. A positive
  `maximum_working_memory_gb` setting can impose a stricter ceiling. The budget
  is a ceiling, not a promise to allocate that memory.
* Voxel indexing uses Open3D CUDA when an NVIDIA CUDA build is installed, or
  OpenCL double-precision kernels when a compatible GPU driver is available.
  CPU NumPy remains the deterministic fallback. Fitting, topology, and IFC
  construction remain CPU algorithms in this release.
* Every reconstruction records stage duration, point-cloud pass equivalents,
  processed-point throughput, planned workers, sampled process thread count,
  process CPU time, unused CPU capacity, I/O byte counters, RSS peak and growth,
  available memory, temporary-wave estimates, source/sample counts, detected
  element counts, backend calls, and available GPU counters. Direct blocked-I/O
  wait is not portable and remains explicitly null instead of being guessed.
* The desktop atomically updates `last-performance.json` and a per-job file in
  the project's `diagnostics` directory at every stage boundary and at five
  second heartbeats. A worker termination therefore retains the last valid
  snapshot; the desktop subsequently marks it `cancelled`. Imports separately
  record combined E57 read, decompression, validation, coordinate conversion
  and cache-writing time. The CLI writes `performance.json`.

Use `--compare-budgets` with `demo`, `convert-xyz`, or `convert-e57` to run
250k, 500k, 1M, 2M, and 5M candidate budgets. The run stops after two
consecutive geometry-stable comparisons. This is a convergence diagnostic,
not a survey-accuracy certification; a registered or annotated reference is
still required for that claim.

For an optional Windows NVIDIA path, install a matching Open3D CUDA wheel in
the worker environment. AMD hardware can use the OpenCL path when its driver
exposes a double-precision GPU device.
