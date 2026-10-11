# Run 3: slab and ceiling safety

Candidate version: 0.3.0a20. This work continues on `run2/interactive-preview`,
which contains Runs 1, 2 and 3. No separate Run 3 branch is required.

## IFC cut policy

Horizontal occupancy gaps are retained as review candidates. They are never
sufficient on their own to remove slab material. The same validation function
controls IFC export, the native slab preview and stair clearance checks.
Legacy project gaps with no independent validation remain filled, including
legacy openings marked `reviewed`. Review status alone is not cut approval.

A gap is automatically validated when two distinct slab faces independently
contain matching hole polygons (intersection-over-union at least 0.8), with
support on both boundaries. Repeated small gaps of similar dimensions are
classified conservatively as possible light-fixture patterns and stay filled,
even when both faces contain the pattern. Single-face gaps stay filled.
The model also recognizes explicit vertical-reveal and confirmed-shaft
validation records; this change does not add a new shaft or reveal detector.

Stairwell cuts are recalculated from tread-by-tread headroom envelopes clipped
to the host slab, independently of occupancy holes. Automatic cuts require
independently fitted stair treads or accepted stair geometry. Contributing
landings must likewise have measured support or explicit acceptance. Rejected,
flagged or stale sources cannot establish automatic cut validation. Intersecting
a stair envelope does not validate the entire surrounding occupancy gap.

Users can approve a candidate with **Approve this opening as an IFC slab cut**
and **Apply correction**. This records explicit approval separately from review
status. Editing an opening, host or source geometry invalidates earlier approval
and automatic validation; the edited geometry must be checked again.

Uncertain candidates remain in the saved model and appear as thin purple review
outlines above the filled slab, including in top-down views. They are omitted
from IFC opening entities. Export diagnostics list validated cuts and excluded
review-only candidates. Exported stair clearance is checked against geometry
reopened from the actual IFC, rather than the original occupancy masks.

## Fragment consolidation

Coplanar roof/ceiling fragments can be joined across supported scan seams up to
the existing `slab_close_gap_m` limit (default 0.16 m). The bridge requires a
substantial adjacent boundary and a bounded inferred area. It preserves
concavity and distant components; it never substitutes a convex hull. Added
scan-seam area is recorded as inferred slab evidence. Wider or unsupported gaps
remain separate rather than being silently filled.

## Regression coverage and remaining acceptance

Generated regressions cover 33 repeated fixture gaps on one or both faces,
matching independent slab holes, single-face gaps, explicit approval and
revocation after edits, legacy holes that falsely hide stair clearance,
independent global stair detection and real IFC cut volumes, unconfirmed stair
proposals, and bounded seam consolidation. Native preview verification checks
filled slab caps, approved voids and visible review markers.

The customer E57/project with the reported 33 false holes is not available in
this workspace. Field acceptance remains pending: rerun detection in this
candidate, confirm zero fixture cuts, inspect the real staircase and required
clearance, and check that uncertain candidates stay out of exported IFC.
Generated regressions and Windows CI cannot establish that project-specific
acceptance result.
