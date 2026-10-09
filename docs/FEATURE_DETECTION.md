# Feature detection and topology limits

Punctora produces reviewable geometric candidates. A candidate, confidence score, successful IFC export or valid IFC schema does not establish survey accuracy.

## Walls and connectivity

Wall faces are proposed from contour or region-growing geometry, consolidated conservatively, fitted back to original source records and then passed through a topology stage.

The topology stage:

- clusters credible same-storey corner endpoints with an order-independent union-find pass;
- derives one shared corner from immutable pre-snap geometry;
- projects a dangling endpoint onto a host wall only when it lies within the host span, is within the T-junction distance tolerance and meets the minimum crossing angle;
- refuses to move both endpoints of one wall onto the same host;
- removes nonfinite or shorter-than-configured wall axes before polygonization;
- records every endpoint as a shared corner, T-junction, already connected geometry, unresolved small gap, or open/missing candidate.

The default corner tolerance is 0.30 m. The default T-junction tolerance is 0.20 m because detected partition axes can end at the observed inner face of a 0.30 m exterior wall. The 25 degree angle gate prevents nearby parallel walls from being pulled together. These thresholds require field tuning against annotated scans.

Open endpoints are not automatically defects. They may represent scan boundaries, incomplete rooms or genuinely missing geometry. The report therefore asks for point-cloud review rather than silently extending a wall.

## Wall openings

Doors and windows are proposed from bounded empty regions in a host-wall occupancy grid. The detector requires supported side/top edges, size limits and low interior occupancy. It detects visible voids only. Glazing, closed leaves, furniture occlusion and sparse returns can cause misses or false proposals. Accepted wall openings produce an `IfcOpeningElement` plus an `IfcDoor` or `IfcWindow` filling.

## Stairs and slab openings

Straight stair flights are proposed from repeated horizontal tread patches with consistent rise, going and width. Curved stairs, landings, railings, stringers and structural support are outside the current detector.

After slabs are assembled, a stair can produce a separate `SlabOpening` candidate only when:

1. its computed top reaches the vertical interval of a different `FLOOR` slab within 0.05 m;
2. its run has nonzero length; and
3. the complete run-width rectangle, including a 0.10 m review margin, lies inside the host slab footprint.

The candidate has its own stable ID, host slab, source stair, provenance, evidence, support score and review state. It appears as a purple inspection volume in the desktop, can be edited or rejected, survives project save/reopen, participates in point-budget convergence comparisons, and cuts the host slab during IFC export. Rejected candidates, or candidates linked to rejected stairs or slabs, are excluded from project export.

The current rectangle is a tread-envelope proposal, not a headroom or structural trimming calculation. If it extends beyond the slab footprint, Punctora records a skipped diagnostic instead of clipping it into another shape.

## Slabs and vertical gaps

A small observed gap between one storey's ceiling and the next storey's floor can establish an intermediate slab thickness. When the gap exceeds the configured maximum plausible thickness, Punctora keeps the normal assumed slab thickness and records the remaining interval as an unresolved vertical zone. It does not create an unusually thick slab merely to close the model.

## Review and export

Supported candidates can be marked `unreviewed`, `reviewed`, `flagged` or `rejected`. Geometry corrections are recorded as user supplied while original evidence remains attached to the source fit. Export warns when unreviewed or flagged elements remain. Whole-cloud deviation, annotated precision/recall and independent viewer acceptance remain separate quality work.
