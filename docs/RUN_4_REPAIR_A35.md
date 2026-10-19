# Run 4 A35: bounded proposal stitching and measured opening heights

This continues the requested Run 4 repair on PR #8. A34 remains the verified
runtime prerequisite; no newer real-scan results were available for this pass.
These failures were reproduced against the current source with generated
original-point cases. They are not established causes of the returned EG Kita
or Treppenhaus discrepancies.

## Reproduced failures and repairs

1. **Multiway wall seams bypassed their aggregate area limit.** The old code
   checked each prior fragment against the incoming fragment, then merged all
   matches without rechecking their combined geometry. The reproduction's two
   pair envelopes are 0.26 m² each, below their 0.2695 m² allowance, while the
   three-way envelope is 0.43525 m² against a 0.419 m² allowance. Each accepted
   merge now checks the growing union against the same existing rule. Rejected
   joins leave their fragments and original references available separately.
2. **Shared level bounds could merge vertically separate opening fragments.**
   Stitching now also checks their original-point `observed_z_bounds_m`, using
   the existing 0.08 m vertical tolerance. Joined fragments retain the union of
   both their measured height intervals and their declared level envelopes.
   Mixed measured/unknown-height fragments remain separate, preserving both.
   Level bounds remain inferred/user-supplied bounds, not measured floors.
3. **Original-point fitting could undo the separation.** Semantic window/door
   refits now restrict their selected original points to the proposal's measured
   vertical interval. The existing 0.12 m source halo remains available to the
   independent frame test. A nearby upper window cannot supply height to the
   lower window merely because it lies inside that halo. Invalid/nonfinite
   measured bounds fail visibly instead of silently broadening the search.

Provider version **4.2** changes the content-bound descriptor and manifest
identity, preventing reuse of earlier stitched ProposalSets under this repair.
The A-J weights, branch set, physical fields, TTA views, recognition thresholds,
source f64 coordinates, scan/record IDs and RAM policy remain unchanged. No
provider accepts user geometry or approves a slab cut.

The geometry implementation retains Shapely 2.1.2's double-precision union and
oriented envelope, with no coordinate-grid snapping. An oriented envelope can
enclose area outside its input; the application must enforce its own area rule.
Sources: [union](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.union.html)
and [oriented envelope](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.minimum_rotated_rectangle.html).

## Verification scope

Regressions exercise multiway joins across rotations and million-metre
translations, all input permutations, preserved source-row references, valid
straight joins, disjoint/adjacent measured heights and declared level envelopes.
Hosted and hostless original-point window cases check both wide separations and
a 0.10 m separation inside the 0.12 m frame-search halo. The final test counts,
independent review, mutation evidence and CI/package results are recorded in
the PR conversation after execution.

Standalone delivery retains A34's embedded Python, pinned CPU ONNX Runtime,
app-local C++ DLLs and self-contained .NET. No software installation is required
on the destination PC. Existing model files remain explicitly selected data.
Packaging must pass the bundled worker and actual extracted-EXE walkthrough.

## Remaining responsibility checkpoint

Run 4 remains unaccepted. This pass establishes the reported generated seam and
height cases, not recovery of highlighted real glazing, larger floor/ceiling
extents, the earlier Treppenhaus contour, or an end-to-end runtime improvement.
XY component construction can still group vertically separated evidence before
stitching; preserving already separate proposals does not qualify that earlier
stage as a general 3D instance separator. This remains an explicit opening-owner
question rather than an unsupported claim of complete window recognition.

Continue with the same bounded EG Kita specialist crop after scan-free setup
passes, then the separate stairwell crop. Return truthful provider/branch status,
performance/job JSON and matching cloud/model views. No full working-assets
upload or complete Fassade run is required. Missing external evidence alone
does not set Repeat. The surface, opening, beam/column and stair owners in the
thirteen-run authority remain unchanged.
