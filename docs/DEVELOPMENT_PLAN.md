# Development plan

The immediate goal is a runnable Windows application that accepts a registered E57 floor scan and produces reviewable IFC4 plus quality results. M0, the experimental M1 core and M2 development are implemented. M2 includes direct E57/coordinates, bounded detection, original-record wall fitting and generated provider/resource benchmarks. Real-file acceptance checks remain open and must not be confused with generated verification. M3 desktop implementation now provides the review/edit/save/export workflow, OpenGL/ANGLE rendering and fallback. Linux walkthroughs and project regressions are verified; physical Windows/AMD acceptance remains pending. See [M3 verification](M3_VERIFICATION.md). See [M2 fitting verification](M2_FITTING_VERIFICATION.md) and [M2 E57 verification](M2_E57_VERIFICATION.md).

| Milestone | Work | Acceptance evidence |
| --- | --- | --- |
| M0: Repository foundation | Preserve Apache 2.0; add notices, candidate inventory, architecture and requirements | Licence preserved, inventory readable, documentation links valid; no claim of a working converter |
| M1: Reconstruction and IFC core | Port selected Cloud2BIM code with attribution; fix repeated-import duplication, first-point loss, mixed-floor rooms, fixed thickness and IFC relationship/type defects | Small generated one-floor and two-floor examples; repeated import stable; valid IFC4 for supported entities; inferred parameters labelled |
| M2: development implemented; field verification pending | E57/coordinates, capped contour/region-growing proposals, original-record fitting, full wall source references and provider/resource comparison | 74 regression tests; generated geometry comparison and one-million-record stress run; full-record import integrity for two supplied E57 examples (1.21M/4.07M points). Independent scanner checks, annotated real reconstruction, building-scale diversity and project CRS/datum remain open |
| M3: Desktop review and export | Import, progress/cancellation, GPU cloud/model viewport with software fallback, supported parameter correction, project save/reopen and export | End-to-end fixture walkthrough; actual viewport GPU/backend reported; hardware/fallback checks; edits survive reopening; UI remains responsive; broken jobs do not destroy saved work |
| M4: Quality and packaging | Surface checks, deviation report, IFC schema/rule checks, runtime notices and Windows packaging | Reopen exported IFC in an independent viewer; distinguish schema errors from geometric errors; installer runs on a clean Windows environment without developer tools |
| M5: User scan trial | User imports an actual E57 floor and reviews output against reference information | Record detected/missed elements, deviations, assumptions, correction effort, runtime/memory and export issues; repair findings before widening scope |
| M6: Expanded architecture and optional AI | Improve openings/spaces; benchmark replaceable licensed proposal providers | Compare against the same baseline scans, including end-to-end accuracy and correction time; licence and hardware decisions recorded |

IFC validation starts in M1 and evolves throughout; M4 makes it user-facing and packages it. Quality metrics do not wait until after the first real scan trial. Additional formats and complex building systems follow only when justified by measured results.

The [M3 implementation plan](M3_IMPLEMENTATION_PLAN.md) records the desktop sequence and the user's automatic-GPU requirement. Viewport rendering and reconstruction computation are separate backends; the High Performance worker now coordinates multicore CPU processing and bounded optional GPU voxel arithmetic, while fitting, topology and IFC writing remain CPU work.

Accuracy run 1 is implemented in 0.3.0a4: conservative collinear wall consolidation, desktop multi-wall merge and wall split, hosted-opening reassignment, undo/save/reopen persistence, and validated IFC regression coverage. Real-scan threshold tuning remains part of the annotated field benchmark rather than a synthetic accuracy claim.

Version 0.3.0a8 strengthens the same run with order-independent corner clustering, angle-gated T-junction snapping, endpoint-level connectivity diagnostics and degenerate-wall rejection. It also introduces model-level stair-to-slab opening candidates, desktop review/edit persistence and IFC slab voids. Candidates are created only when the stair top intersects a different floor slab and the entire rectangular footprint lies within that slab. Unexplained vertical zones between storeys are reported while the slab retains an explicit assumed thickness; the software does not manufacture a full-height slab to conceal missing evidence.

The 0.3.0a6 High Performance pass replaces globally sampled level discovery with a full-cloud streaming Z histogram and spatially distributed level evidence. Candidate budgets can reach five million points, processing chunks are bounded dynamically, and independent storeys/wall regions use all logical processors except one by default. A 20 GB policy ceiling is reduced automatically to 60% of currently available physical memory after reserving the source cloud. Recorded model metadata includes effective budgets, stage timings, RSS/CPU/GPU telemetry, worker count and the level-detection method. Open3D CUDA or OpenCL is used only for bounded voxel indexing when available, with CPU fallback. The `--compare-budgets` diagnostic tests 250k, 500k, 1M, 2M and 5M until geometry stabilises; it does not certify survey accuracy.

## First usable release acceptance

- Import a supported registered E57 without altering it or duplicating cached points on rerun.
- Confirm units, missing coordinate metadata and any unsupported E57 features.
- Reconstruct storeys, walls and slabs where sufficient scan evidence exists.
- View the cloud and model together; correct supported geometry parameters and mark unsupported regions.
- Save/reopen the project, export IFC4 and show validation findings.
- Report point-to-surface deviations with units, included surfaces, sample counts, exclusions and unresolved areas. Occluded faces are not automatically model errors.
- Run on Windows x64 without Revit, CUDA or AI weights. Record actual tested hardware rather than claim universal performance.

## Small tests before the user trial

Tests target defects and coordinate/IFC correctness rather than documentation or UI cosmetics. Include a two-storey floor-isolation case, repeated import, transformed scans, known fitted dimensions and opening/space relationships when those classes are supported. Synthetic fixtures establish implementation behaviour; they do not establish performance on real surveys.

## Parallel investigations

Review model permissions and device compatibility while developing the core. Benchmark an independent AI experiment only when it can use the common proposal contract. Neither model availability nor licensing negotiations block M1-M5.

