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

## Supplied stairwell trial

The final local full-cache trial inspected all 39,068,825 source heights and
completed in 252.8 seconds in the development container. It retained five slab
zones and four storeys, eight slab components and one observed slab hole. It
proposed 31 walls, 16 wall openings and four flights. IFC4 schema/EXPRESS checks
reported no findings, and all 76 products tessellated without geometry errors.
The exact working sets retained 6,586,741; 11,443,912; 9,148,867; and 7,671,820
original points for the four clear storey intervals. No RGB, coordinates or
project source records were modified.

The topology report contains 24 supported corner endpoints, four supported
T-junction endpoints, 30 unresolved endpoints and four rejected corrections.
Accepted corner clusters share an identical axis point, below the 50 mm
endpoint-gap target. This does not measure survey accuracy or prove that every
unresolved endpoint should close.

Two separate 550 mm wide window candidates occur on `storey-4-wall-3`, with
offsets 0.15 and 0.95 m, sill 1.50 m and height 1.20 m. The continuous host and
independent frame checks preserve their separation. The specific pair the user
described on the second storey is **not independently confirmed**: second-storey
results include one door proposal and three ambiguous openings on separate
hosts. These are not relabelled to manufacture acceptance.

| Acceptance item | Result |
| --- | --- |
| Multiple slices and inspectable source extents | Implemented and tested |
| Shorten unsupported ceiling-only extension | Generated regression passes; specific reported scan wall not independently annotated |
| Evidenced corners within 50 mm | Supported clusters close; unsupported proposals remain diagnostics |
| Two separate windows on a continuous host | Present on the upper storey; requested second-storey pair remains open |
| Jamb, sill, head and signed-depth readings | Inspector and persisted evidence implemented |
| Coordinates, crop identity, persistence and IFC | Regression checks pass; full-cache IFC valid |

Run 4.2 implementation is available, but its scan acceptance is partial.
Opening types are geometric proposals and can still misclassify glazing or
occlusions. The requested second-storey host/window association needs continued
correction or an independently identified reference, before claiming that this
scan satisfies every Run 4.2 criterion. The four detected flights are existing
per-storey proposals, not completion of Run 4.3 global stair reconstruction.
