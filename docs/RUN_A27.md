# a27: supported outlines, slab corners and additive models

Exterior walls can have different top and bottom heights along their length.
The original-record fitter retains bounded longitudinal/height support columns.
Exterior reconstruction derives a stepped wall outline from distributed support
rather than extruding a whole wall to a single chimney maximum or ground-trace
minimum. Preview and IFC use the same outline. Openings that cannot fit that
outline remain evidence-backed review candidates. Insufficient or disconnected
outline support is flagged rather than certified as a measured boundary.

Corner snapping rejects a correction that would collapse a supported wall.
It retains the original candidate and records the rejected snap.

Slab corner completion requires adjoining original wall planes, adjacent slab
support on both arms, and a bounded gap (0.48 m with default settings). Added
area is inferred completion. Real concavity and protected holes remain intact;
larger gaps remain review items. Polygon validity alone does not establish a
complete building footprint.

## Add to the current model

1. Save the exterior result and its assets.
2. Choose Interior and set any manual bounds needed for the scan.
3. Choose **Add to existing model**, save changed detection settings, then
   **Detect elements**.
4. Save and review the combined result before **Convert to IFC**.

**Replace current model** remains the default. Add retains prior evidence
generations, edits and review states. Matching or contained wall proposals,
equivalent slabs and openings, and repeated stair/landing geometry are
deduplicated. A conflicting opening is retained for review rather than forced
onto an incompatible preserved host. Ambiguous overlapping geometry is not
silently declared equivalent.

## Add another saved project

Use **Add saved project model**. Keep both projects with their companion assets.
For different E57s, confirm that they share source survey coordinates, or enter
an explicit placement as **X; Y; Z; yaw degrees**, mapping the incoming local
frame into the target local frame. Shared source coordinates are converted
between local origins in f64. Unknown CRS metadata is not a reason to assume
that independent scans are aligned. Scaling and tilting the Z-up frame are
rejected.

The merge copies complete evidence reference arrays into an atomic generation.
Every incoming element retains its source identity and alignment; duplicates
retain corroborating source evidence. The target point cloud remains the active
preview/fitting source. Adding another model does not register point clouds or
copy that project's complete raw cloud cache. IFC records per-element source
contexts as well as the target's global coordinate mapping.

## Verification and limits

The regression suite covers stepped exterior
outlines, preserved short walls, concave/void-safe corners, alignment, additive
reconstruction, copied evidence, cleanup, save/reopen and reopened IFC.
Native CI also exercises profile meshes, both additive worker paths and
coplanar transparency. A stencil ownership pass prevents different overlapping
tessellations from blending a model skin more than once per pixel.
Staged spatial-index and evidence arrays check available disk space and reserve
their storage where supported, reporting allocation failures before writable
mapping pages can terminate the worker. Failed reconstruction keeps the saved
model and its diagnostic report.

The supplied a26 facade run reports 16:19 including evidence export and 18.01
complete-source-equivalent visits on the user's Windows computer. These are
historical a26 measurements, not an a27 facade benchmark. That raw facade source
is unavailable here; its exact missing-wall and outline acceptance remains
pending a source-specific rerun. The original Kita source was recovered and
hash-verified for a separate a27 check. Source results and build links are
tracked in GitHub issue #1.
