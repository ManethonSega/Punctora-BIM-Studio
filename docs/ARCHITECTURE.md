# Architecture

Status: M2 import and reconstruction core implemented; desktop remains a design target.

## Components

| Component | Responsibility | Planned implementation |
| --- | --- | --- |
| Desktop | Project setup, jobs, 3D review, corrections and export | .NET 10 and Avalonia; dedicated GPU point/mesh viewport required when available, renderer selection pending prototype |
| Import worker | Read E57 scans, poses and available metadata, reject invalid coordinates | Python and pye57 0.4.19; bounded-memory decoding implemented and checked with generated fixtures and two supplied examples |
| Cloud store | Preserve the source, index working points and serve reduced preview data | Disk-backed working arrays implemented; preview/index formats remain for M3 benchmarking |
| Reconstruction | Detect floors and surfaces, fit walls/slabs and retain scan evidence | Contour baseline plus CPU region-growing experiment; capped voxel proposals, batched SciPy neighbourhoods and original-record wall fitting implemented |
| Element model | Stable IDs, geometric parameters, host/storey relationships and provenance | Punctora-owned versioned JSON representation |
| IFC service | IFC4 geometry, decomposition, containment, openings and georeferencing | IfcOpenShell library; local placement plus E57-source `IfcMapConversion` implemented |
| Quality service | IFC rules, geometric checks and surface-deviation measurements | Deterministic calculations with explicit coverage and sampling |
| Optional proposal provider | Suggest classes and element geometry | Classical providers first; replaceable SpatialLM/Pointcept adapters later |

The Python worker is launched by the desktop app. The packaged product must include the permitted runtime and libraries so ordinary users do not install Python, .NET or Revit separately. Exact runtime and package versions will be pinned when implementation is tested.

## GPU policy for M3

The user's clarified requirement on 2026-10-08 concerns accelerating **point-cloud-to-IFC conversion**, including multiple CPU cores and an available compatible GPU. Profile stages and add bounded parallel computation where measured beneficial; preserve a correct CPU fallback. Region-growing neighbour queries currently use one worker; storey and wall orchestration is sequential. NumPy/OpenCV may already parallelize some native operations, which is not a coordinated whole-pipeline multicore implementation. GPU computation is not implemented.

The M3 rendering design also prefers an available compatible GPU for the 3D point-cloud/model viewport, separately from conversion acceleration. Support AMD, NVIDIA and Intel graphics through a vendor-neutral rendering API; CUDA is not a desktop requirement. Prefer a suitable hardware adapter and provide a bounded software preview when hardware initialization is unavailable or fails. Report the actual viewport adapter/backend and fallback state, separately from worker processing.

GPU-accelerated Avalonia controls alone do not establish a GPU 3D cloud renderer. The viewport prototype must use batched point/mesh buffers, GPU camera transformations and depth handling, bounded uploads and detail selection. Keep canonical fitting coordinates in double precision; local-origin reduced-precision preview buffers do not replace source evidence. Worker jobs, uploads and indexing must not block the UI.

The existing E57 decoder, contour/region-growing reconstruction and IFC exporter remain CPU implementations. Profile reconstruction and deviation workloads separately, and adopt a compute backend only after end-to-end timing, memory and numerical-equivalence checks including transfer costs. A detected graphics GPU does not establish that a particular compute or AI backend is supported. No GPU speedup or target-card compatibility has been measured yet.

See the [M3 implementation plan](M3_IMPLEMENTATION_PLAN.md) for sequence and acceptance checks.

## Data flow

E57 source -> validated scan coordinates -> working/preview cloud -> element proposals -> scan-based fitting -> review and corrections -> IFC4 -> validation and deviation report.

A failed validation leaves the findings visible and labels any exported diagnostic file accordingly. Successful file writing must never be presented as successful reconstruction or project acceptance.

## Worker contract

Use versioned JSON messages over standard input/output for commands, progress, warnings, cancellation acknowledgement and results. Diagnostic logging uses standard error. Bulk point/mesh data is passed through explicit project-local file references, not embedded in JSON messages.

Each job has an ID, input fingerprints, parameters, engine versions and output paths. Writes use temporary files and atomic replacement. Re-running an import replaces its derived cache rather than appending duplicate points. Long work stays outside the UI thread. Cancellation and failure preserve the previous saved project and clean incomplete outputs.

## Coordinate contract

- Canonical processing geometry uses metres and double precision in a local project frame, with Z up.
- Preserve original scan pose matrices, source units, coordinate metadata and the reversible mapping to the local frame. Distinguish scan poses from building orientation and map coordinates.
- Apply each scan pose exactly once. Axis alignment for an algorithm is another recorded transform, not an overwrite of source coordinates.
- Coordinate reference systems, vertical datums and project origin are confirmed by the user or supporting metadata. An E57 extension or coordinate magnitude is not sufficient proof of a CRS.
- Preview rendering may use reduced precision near the local origin; original survey coordinates remain recoverable.
- IFC export records local placement and supported map conversion with their units. Unsupported transformations must be reported rather than silently approximated.

## Internal element contract

An element carries its stable ID, class, storey ID, geometry parameters, source scan/point references, detection method, parameter provenance, user review state and measured quality results. Openings carry a host-wall ID. Spaces have spatial decomposition relationships distinct from physical-element containment.

Element JSON schema 2 records wall observed faces, deterministic evidence selectors, per-scan counts and bounded record examples. CLI exports full N x 3 int64 wall references (working-cloud row, scan index, original scan record) and region-patch representative IDs to generation-specific NPY files. Paths are relative to the output/project directory. An identifier absent from the source is -1, never a fabricated scan record. Surface proposals remain separate from IFC elements. Slab footprints and unseen thicknesses remain inferred; wall reference files do not validate those properties.

Use explicit parameter states: `measured`, `inferred`, `user_supplied`, `unknown`. A fitted wall surface does not establish its hidden thickness, material or load-bearing status. Unknown values remain unknown unless an export representation requires an assumption; that assumption is shown and recorded. Do not assign an uncalibrated number as a probability of correctness.

## Research resources in the foundation

- SpatialLM informs a structured layout and proposal contract, not the authority for final dimensions. Independently author Punctora's representation; copying its implementation needs a separate licence review. The [versioned paper assessment](research/SPATIALLM.md) records 2.5 cm proposal quantization, inferred completion, explicit opening hosts and an M6 evaluation plan. M3 review should distinguish proposals from scan-supported geometry; no AI adapter is integrated yet.
- The ISPRS paper informs experiments with normal-based region growing and spatial relationships. Test the methods against a Cloud2BIM baseline before adoption; the paper is not a ready IFC engine.
- Pointcept may later provide point labels. Labels still require geometric fitting and IFC authoring.
- Keep the same downstream contract for classical and AI proposals so a later model integration does not replace import, review or IFC validation.

## Boundaries

Initial scope assumes already registered building scans. Registration optimisation, photogrammetry, roofs, stairs, MEP systems and city-scale processing are outside the first milestone. Model correction operates on derived elements and does not change the original scan.

Processing is local by default. Future remote inference requires an explicit user choice identifying the recipient and transmitted data. No automatic model downloads or scan uploads are part of this design.
