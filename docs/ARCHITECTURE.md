# Architecture

Status: design, not implemented. Target: a Windows-first standalone desktop application.

## Components

| Component | Responsibility | Planned implementation |
| --- | --- | --- |
| Desktop | Project setup, jobs, 3D review, corrections and export | .NET 10 and Avalonia; renderer selection pending prototype |
| Import worker | Read E57 scans, poses and available metadata, reject invalid coordinates | Python; pye57 candidate; native reader and memory behaviour require testing |
| Cloud store | Preserve the source, index working points and serve reduced preview data | Disk-backed chunks and separate preview cache, implementation to benchmark |
| Reconstruction | Detect floors and surfaces, fit walls/slabs and retain scan evidence | Selected corrected Cloud2BIM algorithms; Open3D candidate |
| Element model | Stable IDs, geometric parameters, host/storey relationships and provenance | Punctora-owned versioned JSON representation |
| IFC service | IFC4 geometry, decomposition, containment, openings and georeferencing | IfcOpenShell library through Python worker |
| Quality service | IFC rules, geometric checks and surface-deviation measurements | Deterministic calculations with explicit coverage and sampling |
| Optional proposal provider | Suggest classes and element geometry | Classical providers first; replaceable SpatialLM/Pointcept adapters later |

The Python worker is launched by the desktop app. The packaged product must include the permitted runtime and libraries so ordinary users do not install Python, .NET or Revit separately. Exact runtime and package versions will be pinned when implementation is tested.

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

Use explicit parameter states: `measured`, `inferred`, `user_supplied`, `unknown`. A fitted wall surface does not establish its hidden thickness, material or load-bearing status. Unknown values remain unknown unless an export representation requires an assumption; that assumption is shown and recorded. Do not assign an uncalibrated number as a probability of correctness.

## Research resources in the foundation

- SpatialLM informs a structured layout and proposal contract, not the authority for final dimensions. Independently author Punctora's representation; copying its implementation needs a separate licence review.
- The ISPRS paper informs experiments with normal-based region growing and spatial relationships. Test the methods against a Cloud2BIM baseline before adoption; the paper is not a ready IFC engine.
- Pointcept may later provide point labels. Labels still require geometric fitting and IFC authoring.
- Keep the same downstream contract for classical and AI proposals so a later model integration does not replace import, review or IFC validation.

## Boundaries

Initial scope assumes already registered building scans. Registration optimisation, photogrammetry, roofs, stairs, MEP systems and city-scale processing are outside the first milestone. Model correction operates on derived elements and does not change the original scan.

Processing is local by default. Future remote inference requires an explicit user choice identifying the recipient and transmitted data. No automatic model downloads or scan uploads are part of this design.
