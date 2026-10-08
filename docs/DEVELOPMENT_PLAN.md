# Development plan

The immediate goal is a runnable Windows application that accepts a registered E57 floor scan and produces reviewable IFC4 plus quality results. M0, the experimental M1 core and M2 development are implemented. M2 includes direct E57/coordinates, bounded detection, original-record wall fitting and generated provider/resource benchmarks. Real-file acceptance checks remain open and must not be confused with generated verification. M3 desktop development can start using the versioned core. See [M2 fitting verification](M2_FITTING_VERIFICATION.md) and [M2 E57 verification](M2_E57_VERIFICATION.md).

| Milestone | Work | Acceptance evidence |
| --- | --- | --- |
| M0: Repository foundation | Preserve Apache 2.0; add notices, candidate inventory, architecture and requirements | Licence preserved, inventory readable, documentation links valid; no claim of a working converter |
| M1: Reconstruction and IFC core | Port selected Cloud2BIM code with attribution; fix repeated-import duplication, first-point loss, mixed-floor rooms, fixed thickness and IFC relationship/type defects | Small generated one-floor and two-floor examples; repeated import stable; valid IFC4 for supported entities; inferred parameters labelled |
| M2: development implemented; field verification pending | E57/coordinates, capped contour/region-growing proposals, original-record fitting, full wall source references and provider/resource comparison | 74 regression tests; generated geometry comparison and one-million-record stress run. Real scanner files, building-scale diversity and project CRS/datum still need verification |
| M3: Desktop review and export | Import, progress/cancellation, point/model overlay, supported parameter correction, project save/reopen and export | End-to-end fixture walkthrough; edits survive reopening; UI remains responsive; broken jobs do not destroy saved work |
| M4: Quality and packaging | Surface checks, deviation report, IFC schema/rule checks, runtime notices and Windows packaging | Reopen exported IFC in an independent viewer; distinguish schema errors from geometric errors; installer runs on a clean Windows environment without developer tools |
| M5: User scan trial | User imports an actual E57 floor and reviews output against reference information | Record detected/missed elements, deviations, assumptions, correction effort, runtime/memory and export issues; repair findings before widening scope |
| M6: Expanded architecture and optional AI | Improve openings/spaces; benchmark replaceable licensed proposal providers | Compare against the same baseline scans, including end-to-end accuracy and correction time; licence and hardware decisions recorded |

IFC validation starts in M1 and evolves throughout; M4 makes it user-facing and packages it. Quality metrics do not wait until after the first real scan trial. Additional formats and complex building systems follow only when justified by measured results.

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
