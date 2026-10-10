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

Openings use two independent geometric signals inside a bounded host-wall envelope:

- supported empty regions, for visibly open doors and windows;
- supported recessed return planes, for closed leaves or glazing measurably behind the surrounding wall face.

Both paths require a rectangular component, plausible dimensions and supported jamb/head edges. Evidence records occupancy, frame support, wall-face reference depth and recess contrast. Floor contact and height propose a door, a supported sill proposes a window, and ambiguous geometry remains `unknown`. An unknown candidate cuts only an `IfcOpeningElement`; it does not invent an `IfcDoor` or `IfcWindow` filling.

The default minimum recess is 0.03 m and minimum edge support is 0.65. Furniture outside the wall envelope is excluded, but wall-mounted objects, occlusion, reflective glazing and sparse returns can still cause false or missed candidates. These thresholds require annotated real-scan validation.

## Stairs and slab openings

In automatic Run 4.1 reconstruction, slab voids now come from enclosed horizontal
occupancy gaps and remain pending stair-system validation. The stair-derived
headroom procedure below remains available for explicit caller-supplied storeys;
it will be integrated with global stair systems in Run 4.3. See [Run 4.1](RUN_4_1.md).

Straight flights are proposed from repeated horizontal tread patches with consistent rise, going and width. Broader horizontal patches touching flight endpoints become landing candidates. Flights sharing a landing are grouped into one stable stair system with ordered flight indices. This supports straight, L-shaped and U-shaped assemblies made from straight runs. Curved and spiral flights, railings, stringers and structural support remain outside the detector.

After slabs are assembled, a stair system can produce one or more `SlabOpening` candidates when:

1. its computed top reaches the vertical interval of a different `FLOOR` slab within 0.05 m;
2. one or more nondegenerate flight or landing envelopes enter the configurable 2.0 m headroom zone below that slab; and
3. the resulting polygon intersects the host slab footprint.

The union of the relevant flight and landing envelopes receives a 0.10 m review margin and is clipped explicitly to the detected host footprint. The evidence records the source flights, source landings, headroom, margin and whether clipping occurred. A candidate has its own stable ID, host slab, stair-system identity, provenance, support score and review state. It appears as a polygonal purple inspection volume, survives save/reopen, participates in convergence comparisons and cuts the host slab during IFC export.

The envelope is a clearance proposal, not a structural trimming design. Reinforcement, edge framing, finishes and code compliance still require engineering review.

## Slabs and vertical gaps

A small observed gap between one storey's ceiling and the next storey's floor can establish an intermediate slab thickness. When the gap exceeds the configured maximum plausible thickness, Punctora keeps the normal assumed slab thickness and records the remaining interval as an unresolved vertical zone. It does not create an unusually thick slab merely to close the model.

## Review and export

Supported candidates can be marked `unreviewed`, `reviewed`, `flagged` or `rejected`. The desktop can add doors, windows, flights, landings and slab openings, delete feature candidates, reassign opening hosts and edit their supported parameters. Geometry corrections are recorded as user supplied while original evidence remains attached to the source fit. Export warns when unreviewed or flagged elements remain. Whole-cloud deviation, annotated precision/recall and independent viewer acceptance remain separate quality work.
