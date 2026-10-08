# M3 desktop implementation plan

Recorded 2026-10-08. Status: planned, not implemented. M2 supplies E57 import, CPU reconstruction, evidence and IFC export. M3 turns that core into an interactive desktop review workflow. The user clarified that automatic GPU use and multicore CPU acceleration primarily concern **point-cloud-to-IFC conversion**. GPU rendering is a separate M3 design choice, not a substitute for accelerating conversion.

## Current GPU status

The repository has no desktop viewport or GPU compute backend. pye57 import, NumPy/SciPy/OpenCV reconstruction, source-record fitting and IfcOpenShell export currently run on the CPU. Available graphics hardware does not automatically accelerate these Python algorithms.

Avalonia's [Windows documentation](https://docs.avaloniaui.net/docs/platform-specific-guides/windows) describes GPU-backed UI rendering and software fallback. That does not supply the application's 3D cloud/model engine. A dedicated batched GPU viewport must be built and benchmarked. Avalonia exposes [OpenGlControlBase](https://api-docs.avaloniaui.net/docs/T_Avalonia_OpenGL_Controls_OpenGlControlBase) as one possible integration route. A native Direct3D viewport is another prototype option on Windows; Microsoft's [WARP guidance](https://learn.microsoft.com/en-us/windows/win32/direct3darticles/directx-warp) documents hardware/software rendering and the importance of efficient batching. Choose and pin the renderer after a small working prototype, rather than claiming a particular API is already integrated.

The user's known desktop RX 7800 XT 16 GB is an intended test target, not tested hardware for Punctora. Use a vendor-neutral graphics path so AMD, NVIDIA and Intel adapters can be supported without requiring CUDA. Validate the actual device, driver and rendering capabilities. Graphics support, GPU compute support and AI checkpoint support are separate checks.

## Implementation order

| Step | Work | Completion evidence |
| --- | --- | --- |
| 1. Desktop and job connection | Create the .NET 10/Avalonia application and versioned worker protocol; import/demo commands, progress, warnings and cancellation; bulk data through project-local files | A long job leaves controls responsive; malformed messages, cancellation and worker crashes preserve the last saved project |
| 2. Preview store and GPU prototype | Generate bounded preview blocks near the local origin; upload batched points and meshes; GPU camera transforms and depth; hardware selection and software fallback | Both supplied E57 files load for viewing; actual adapter/backend is reported; GPU and forced-fallback modes measured; canonical coordinates/source files unchanged |
| 3. Cloud/model review | Orbit, pan, zoom, fit view, cloud/model toggles, transparency, storey filters, section/crop controls, element selection and evidence display | Cloud and generated model align using the same coordinate mapping; selected elements are identifiable; inferred and unresolved geometry remains visible |
| 4. Supported corrections | Edit supported wall endpoints, base, height and thickness, slab base/thickness and explicit storey parameters; reject/flag unsupported proposals; validate changes and preserve observations | Valid edits appear immediately and keep stable element identity; invalid dimensions cannot silently enter an accepted model; source evidence is retained separately from edits |
| 5. Project persistence | Validated schema loading, persistent project/element IDs, atomic save/reopen, relative cache/evidence references and generation lifecycle management | Edits, warnings, coordinates and review states survive reopening; failed saves do not destroy the previous version; required generations are not deleted while in use |
| 6. Reviewed IFC export | Export the edited model through the existing IFC service and show validation findings | Export reflects supported edits, retains mapping and identity, and distinguishes file validity from survey/model acceptance |
| 7. End-to-end verification | Fixture import/reconstruct/review/edit/save/reopen/export; sample import/view walkthroughs; cancellation/failure tests; graphics measurements | Reproducible reports identify hardware, backend, settings and limits. Windows physical GPU testing is required before claiming the target card works |

Steps 1 and 2 are the immediate implementation work. Establish the worker connection and a measurable GPU cloud viewport before building the full property editor. The first M3 review model can use generated fixtures; the unannotated E57 examples test import and viewing, not accepted architectural reconstruction.

## GPU rendering requirements

- Default to automatic hardware use. Prefer an appropriate hardware adapter when initialization and required graphics capabilities succeed; a driver failure must not make an existing project unusable.
- Show the actual cloud-viewport mode, for example hardware GPU versus software preview. Keep it distinct from the worker's CPU/GPU-compute mode. A graphics card name alone is not evidence of active hardware rendering.
- Use batched buffers and GPU point/mesh transformation rather than projecting millions of points individually on the UI thread. Apply depth testing consistently to the cloud/model overlay.
- Bound GPU memory, preview residency and uploads. Use view-dependent detail and progressive refinement; report displayed versus total points when a reduced preview is used. A preview limit must not truncate fitting evidence or source data.
- Preserve double-precision canonical coordinates and all reversible mappings. Local-origin float preview geometry is for display; coordinate readout, corrections and IFC use canonical values.
- Recover from unavailable hardware or a failed renderer with a reduced software preview. Exercise that path explicitly, including reopening a project created in hardware mode.

## Processing acceleration policy

GPU rendering is the M3 viewport design where compatible hardware is available. GPU reconstruction and coordinated multicore conversion are separate measured improvements, not implied benefits of the UI framework. The original M2 functionality is implemented; this performance extension has not been implemented or benchmarked.

Code inspection found `workers=1` for both region-growing neighbour queries and sequential storey/face orchestration. Native NumPy/OpenCV operations can already use library-managed CPU threads, but the number depends on the distribution and process settings. The existing comparison runner caps BLAS/OpenMP threads for reproducibility; this is not a maximum-throughput multicore benchmark, and those environment variables alone do not establish every native library's thread count.

| Conversion stage | Multicore experiment | GPU experiment |
| --- | --- | --- |
| E57 decoding and cache | Independent scans only with separate readers, bounded buffers and stable ordering; measure storage contention | Keep current CPU/native decoder unless a specific compatible decoder is implemented and verified |
| Detection and normals | Configurable neighbour-query workers; independent storey/crop jobs where memory permits | Evaluate a supported bulk neighbourhood/normal backend; include index construction and transfers |
| Original-record fitting/evidence | Bounded independent wall/face batches and shared read-only mapped points; deterministic output assembly | Evaluate batched distances/residuals/reductions while preserving double-precision fitting requirements and point identity |
| IFC creation and validation | Parallelize only independent preparation/checks whose APIs permit it; avoid concurrent mutation of the same IFC model | Keep the existing CPU IFC service; no GPU implementation or demonstrated benefit |

First measure import, detection, fitting, evidence output and IFC/validation separately on a representative building crop. Then compare one worker with bounded 2/4/8-worker configurations and selected GPU kernels. Avoid multiplying outer workers by uncontrolled inner BLAS/OpenCV threads. Preserve UI responsiveness and cap total RAM/VRAM. Mapped-file residency and repeated full-cloud wall reads can limit scaling even when more cores are available.

Primary references: [SciPy 1.17 neighbour-query workers](https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.spatial.cKDTree.query.html), [NumPy 2.3 native-thread configuration](https://numpy.org/doc/2.3/reference/global_state.html), and [NVIDIA's profiling/transfer guidance](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html). The last reference explains performance principles; it is not an AMD-compatible backend selection or a decision to use CUDA.

Profile the current pipeline on a representative cropped building scan before selecting compute work. Candidate experiments include normal/neighbor calculations, point filtering and point-to-surface deviation batches. These are hypotheses, not integrated capabilities or proven bottlenecks. Compare complete job time, memory, data transfers and numerical results with the existing CPU path. Preserve scan/record identity, parameter provenance and export validation.

Adopt GPU computation where a compatible backend yields a meaningful end-to-end improvement without exceeding agreed numerical tolerances; retain the CPU implementation otherwise. E57 decoding, file I/O, serial/topological work and IFC writing do not become GPU implementations merely by enabling hardware rendering. Optional SpatialLM inference remains an M6 experiment with its own runtime, hardware and licence checks.

## Measurements and M3 boundary

Measure import-to-first-view time, camera-interaction frame times, input responsiveness, displayed point count, resident GPU memory and process RAM. Record resolution, graphics adapter, driver, renderer and detail settings. Compare hardware mode with the same preview in software mode, then assess maximum usable preview detail separately. An interactive target such as 30 frames/s is a prototype goal at recorded settings, not a promised result before hardware testing.

Use the pump's five scans and Station018's 4.07 million points as view/import cases. Station018's approximately 711 m extent also exercises local-origin precision and preview/detail selection. Its full extent must not be silently converted into one accepted architectural floor. Retain the empty-CRS and missing-pose warnings from [sample verification](M2_SUPPLIED_E57_VERIFICATION.md).

M3 is complete when the review workflow works, supported edits survive reopening, export reflects those edits, jobs remain responsive and failure-safe, and hardware/fallback viewport behaviour is verified with clearly identified test environments. Annotated real-building accuracy remains a field check. Quality reporting and clean Windows distribution/installer acceptance continue in M4; neither GPU rendering nor a valid IFC establishes survey acceptance.
