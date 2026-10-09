# Architecture

Status: M3 desktop implementation and Linux preview walkthroughs verified; Windows hardware acceptance pending.

## Components

| Component | Responsibility | Implementation |
| --- | --- | --- |
| Desktop | Project setup, jobs, 3D review, corrections and export | .NET 10.0.0 and Avalonia 12.1.3; batched OpenGL/ANGLE point/mesh viewport with software fallback |
| Import worker | Read E57 scans, poses and available metadata, reject invalid coordinates | Python and pye57 0.4.19; bounded-memory decoding implemented and checked with generated fixtures and two supplied examples |
| Cloud store | Preserve the source, index working points and serve reduced preview data | Disk-backed working arrays plus immutable project generations and bounded xyzrgb-f32-le display samples; no streaming LOD yet |
| Reconstruction | Detect floors and surfaces, fit walls/slabs and retain scan evidence | Contour baseline plus CPU region-growing experiment; adaptive point budgets, streaming full-cloud levels, bounded voxel proposals, batched SciPy neighbourhoods and original-record wall fitting implemented |
| Element model | Stable IDs, geometric parameters, host/storey relationships and provenance | Punctora-owned versioned JSON representation |
| IFC service | IFC4 geometry, decomposition, containment, openings and georeferencing | IfcOpenShell library; local placement plus E57-source `IfcMapConversion` implemented |
| Quality service | IFC rules, geometric checks and surface-deviation measurements | Deterministic calculations with explicit coverage and sampling |
| Optional proposal provider | Suggest classes and element geometry | Classical providers first; replaceable SpatialLM/Pointcept adapters later |

The Python worker is launched by the desktop app. The packaged product must include the permitted runtime and libraries so ordinary users do not install Python, .NET or Revit separately. NuGet dependencies are locked; Windows worker wheels and embedded Python archive have recorded hashes. Portable preview build tooling is implemented; final installer acceptance remains M4.

## GPU policy for M3

The user's clarified requirement on 2026-10-08 concerns accelerating **point-cloud-to-IFC conversion**, including multiple CPU cores and an available compatible GPU. The worker now resolves all logical CPU cores except one by default, parallelises independent storeys and wall regions, limits nested BLAS pools, and records stage telemetry. Bounded voxel indexing attempts Open3D CUDA or OpenCL double-precision arithmetic when available, then falls back to NumPy. Fitting, topology and IFC writing remain CPU algorithms; GPU use is not claimed for those stages.

The M3 rendering design also prefers an available compatible GPU for the 3D point-cloud/model viewport, separately from conversion acceleration. Support AMD, NVIDIA and Intel graphics through a vendor-neutral rendering API; CUDA is not a desktop requirement. Prefer a suitable hardware adapter and provide a bounded software preview when hardware initialization is unavailable or fails. Report the actual viewport adapter/backend and fallback state, separately from worker processing.

GPU-accelerated Avalonia controls alone do not establish a GPU 3D cloud renderer. The viewport prototype must use batched point/mesh buffers, GPU camera transformations and depth handling, bounded uploads and detail selection. Keep canonical fitting coordinates in double precision; local-origin reduced-precision preview buffers do not replace source evidence. Worker jobs, uploads and indexing must not block the UI.

The E57 decoder, contour/region-growing fitting and IFC exporter remain CPU implementations. Voxel arithmetic is profiled separately and uses bounded transfer chunks. A detected graphics GPU does not establish that a particular compute or AI backend is supported. The `--compare-budgets` diagnostic records geometry stability at 250k, 500k, 1M, 2M and 5M candidate budgets, but it is not a survey-accuracy certification.

See the [M3 implementation plan](M3_IMPLEMENTATION_PLAN.md) for sequence and acceptance checks.

## Data flow

E57 source -> validated scan coordinates -> working/preview cloud -> element proposals -> scan-based fitting -> review and corrections -> IFC4 -> validation and deviation report.

A failed validation leaves the findings visible and labels any exported diagnostic file accordingly. Successful file writing must never be presented as successful reconstruction or project acceptance.

## Worker contract

Use versioned JSON messages over standard input/output for commands, progress, warnings, results; cancellation acknowledgement comes from desktop termination/wait, followed by revision-aware recovery. Diagnostic logging uses standard error. Bulk point/mesh data is passed through explicit project-local file references, not embedded in JSON messages.

Each job has an ID, input fingerprints, parameters, engine versions and output paths. Writes use temporary files and atomic replacement. Re-running an import replaces its derived cache rather than appending duplicate points. Long work stays outside the UI thread. Cancellation and failure preserve the previous saved project. Cleanup removes unused owned generations after cancellation/reconstruction; process death releases the OS lock.

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

After face fitting, a conservative topology pass joins same-storey wall fragments only when their direction, lateral offset, height, thickness and projected gap satisfy configured limits. It runs before source-record evidence attachment and opening detection. Explicit desktop merges keep the first wall ID, retain source evidence, and project hosted openings into the combined wall frame. Explicit splits keep the original ID for the first segment, create a deterministic second ID, and reassign openings by local offset. A split through an opening is rejected. Both operations invalidate derived spaces until boundary regeneration is implemented.

Use explicit parameter states: `measured`, `inferred`, `user_supplied`, `unknown`. A fitted wall surface does not establish its hidden thickness, material or load-bearing status. Unknown values remain unknown unless an export representation requires an assumption; that assumption is shown and recorded. Do not assign an uncalibrated number as a probability of correctness.

## Research resources in the foundation

- SpatialLM informs a structured layout and proposal contract, not the authority for final dimensions. Independently author Punctora's representation; copying its implementation needs a separate licence review. The [versioned paper assessment](research/SPATIALLM.md) records 2.5 cm proposal quantization, inferred completion, explicit opening hosts and an M6 evaluation plan. M3 review should distinguish proposals from scan-supported geometry; no AI adapter is integrated yet.
- The ISPRS paper informs experiments with normal-based region growing and spatial relationships. Test the methods against a Cloud2BIM baseline before adoption; the paper is not a ready IFC engine.
- Pointcept may later provide point labels. Labels still require geometric fitting and IFC authoring.
- Keep the same downstream contract for classical and AI proposals so a later model integration does not replace import, review or IFC validation.

## Boundaries

Initial scope assumes already registered building scans. Registration optimisation, photogrammetry, roofs, stairs, MEP systems and city-scale processing are outside the first milestone. Model correction operates on derived elements and does not change the original scan.

Processing is local by default. Future remote inference requires an explicit user choice identifying the recipient and transmitted data. No automatic model downloads or scan uploads are part of this design.

## Desktop project lifecycle

`.punctora` schema 1 stores the project identity, revision, relative asset references, import manifest, coordinate confirmation, warnings and schema-2 element model. Each job stages an immutable generation and publishes it before atomically replacing the project JSON. The last saved revision is protected by an OS lock and optimistic revision checks. Draft corrections preserve original faces/evidence and record user provenance. Save-copy carries only referenced generations and retains element/IFC identity. Rejected geometry is excluded from reviewed export; derived spaces are withheld after geometry edits.

