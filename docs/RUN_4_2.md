# Run 4.2: supported walls, junctions and openings

Automatic contour reconstruction now samples the entire clear storey height.
Six to twelve nonoverlapping bands adapt to that height, excluding the slab
boundaries. Contour lines are proposals only. Plane clusters use a fixed clean
reference, angular agreement and signed perpendicular offset. Median directions
and per-band median offsets stabilize the final plane. The transverse gate is
at most 80% of minimum wall thickness, keeping opposite thin-wall faces distinct.
Bounded whole-storey normal-based patches add plane proposals where frames
fragment contours; they must pass the same independent band checks. A recessed
filling cannot pair as a wall's opposite face without broad vertical and
longitudinal overlap on both faces.

Plane-near point occupancy must repeat in at least two independent bands.
Median endpoints across contributing bands reject an extension observed only
near the ceiling. Small longitudinal sampling gaps, up to 80 mm by default,
can close only when their neighbouring cells have common repeated support.
A gap through every height band remains separate. Weakly supported bridges
wider than 3.2 m are rejected instead of producing an uncut oversized void.
Automatic consolidation
cannot bridge those gaps after detection. This is conservative geometric
support, not proof of wall material or a semantic AI classification.

Each wall retains band elevations, fitted extents, proposal point counts,
fit residuals, longitudinal occupancy runs and vertical continuity. Original
record fitting refines each observed band without replacing consensus wall
endpoints with the extrema from one band. Original record selectors and E57
source references remain available, including after cropping.

When available RAM justifies it, an exact in-memory storey working set avoids
rescanning unrelated storeys for every band. It keeps all relevant original
records and their immutable row, scan and E57 record identifiers. Allocation is
serialized and limited against current available RAM; low-memory cases retain
the mapped full-source selectors. This is not a larger sample or a reduction
in source evidence. Stage telemetry records whether the exact scope was used.

The corner graph uses common wall-axis intersections and solves connected
clusters together. Before changing an endpoint, it checks corresponding
observed-face intersections across overlapping bands. Multi-slice walls need
two independently supported bands within 50 mm of the face extents. T-junctions
use the same evidence gate. Unsupported proposals remain diagnostics rather
than manufactured connections. Degenerate walls are discarded. Endpoint
statuses are `supported_corner`, `supported_t_junction`, `unresolved_gap`,
`rejected_correction`, or `intentional_open_end`. The last status requires an
explicit user designation; missing returns alone cannot establish intent.
Manual merge/split remains an explicit user operation.

Opening rasters are anchored to observed face planes, with signed distance,
face occupancy, return occupancy, frame-edge support and empty continuity.
Closed leaves or glazing can be proposed from a coherent recessed return plane.
Jambs, heads and sills must bound the candidate. A supported vertical separating
strip splits a region; each resulting candidate must independently pass frame
checks. Oversized incomplete wall regions are rejected. Height suggests door
or window, while ambiguous cases retain `unknown` and filling always remains
unknown. Scores are geometric support, not calibrated accuracy probabilities.

Select a wall in the desktop inspector to choose a height band, isolate the
cloud there and inspect measured face extents. Select an opening to inspect
jamb positions, sill/head elevations, signed filling depth and edge support.
Existing preview wall solids and IFC voids use separate accepted openings.

Regression coverage includes ceiling-only extensions, through-height gaps,
bounded windows on continuous hosts, adjacent windows with a 100 mm separating
strip, recessed returns of either sign, supported/rejected corner corrections,
single-band rejection and evidence persistence. Existing coordinate, crop,
manual editing, slab and IFC tests remain required. Benchmark overlap unions
repeated height observations within one wall before counting duplicate walls.

Customer scan files and generated scan geometry are excluded from git. The
full-cache scan verification uses `scripts/verify_slab_zones.py` with
`--full-reconstruction`; its output preserves all element evidence and IFC
validation. Real-scan counts and unresolved acceptance results must be recorded
after that check completes. Run 4.3 global stair-system work remains separate.

`scripts/inspect_wall_rasters.py` can inspect one selected storey from a mapped
cache and an existing model. It writes local frame/depth inspection rasters and
candidate JSON. It uses a 250,000-point spatial working set, so it is a diagnostic
comparison, not full-source acceptance or a replacement for original-record fitting.
