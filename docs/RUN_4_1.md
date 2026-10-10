# Run 4.1: slab zones and supported slab geometry

Version 0.3.0a12 replaces automatic single-peak level pairing and convex slab
solids. It does not implement the later multi-slice wall or global stair work.

## Detection

The streaming histogram inspects every source height. Spatial representatives
around candidate peaks are classified using bounded local covariance/normal
queries. Horizontal support must have an upward normal component of at least
0.97, low curvature, and a bounded neighbourhood. Coplanar edge records near
horizontal support recover boundaries where mixed wall normals would otherwise
erase floor edges.

Surface evidence is rasterized separately, in 80 mm cells by default. Slab pairs
need 80 to 600 mm separation, at least 45% overlap relative to the smaller face,
and normals within 5 degrees. Building-scale support defaults to at least 20%
of the largest horizontal surface. A dynamic-programming sequence combines
coverage, paired-face support, thickness plausibility and vertical spacing.
Clear height must be at least 2 m; floor-to-floor spacing must not exceed 5.5 m.
These are tunable assumptions, not universal building rules.

Candidate metadata records both elevations, estimated thickness, face overlap,
component count, normals, score, acceptance/rejection reason and source working
rows. Cropped rows map back to immutable uncropped rows. Boundaries with only
one face keep an assumed 200 mm thickness. Disjoint XY faces may establish a
short boundary transition, but do not establish measured slab thickness.

Storeys run from the top of the lower selected zone to the underside of the
next one. The storey search envelope can remain convex for existing wall/space
processing, but is **never used as the automatically detected slab solid**.

## Geometry and holes

Occupancy row runs produce polygons without a convex-fill operation. Connected
components remain separate slabs. Concavity and interior rings survive. Pixel
overhang is trimmed to source extents; small-gap closing defaults to 160 mm.
Compatible paired-face footprints are united, with original occupancy retained
for area accounting. Supported original wall outlines can infer only narrow
strips within half the closing distance of horizontal evidence. Large interior
gaps are protected from that fill.

Enclosed gaps of at least 0.25 square metres become explicit polygonal
`SlabOpening` candidates, persisted and exported through `IfcRelVoidsElement`.
They are `observed_hole` when both faces corroborate the boundary, or
`partially_observed_hole` otherwise. Both are pending stair-system validation.
Smaller unsupported gaps filled in the slab are recorded and counted as inferred
area. Negative point evidence cannot distinguish a true hole from occlusion.

Each slab records net exported area, supported/inferred areas and percentages,
wall-outline inferred area, face elevations, raster scale and thickness
provenance. The desktop inspector and IFC property sets expose area percentages.
The serialized desktop preview uses a constrained triangulation of the current
slab minus nonrejected openings, with interior side faces. It rebuilds when
geometry is serialized after editing, so a purple inspection marker does not
conceal an uncut solid slab. These percentages describe the original detection, not accuracy probabilities or a live
recalculation after manual edits. Old projects lacking these fields still load.

Automatic Run 4.1 reconstruction does not enlarge observed holes with the older
per-storey stair detector. Global stair/headroom validation is reserved for Run
4.3. Explicit caller-supplied storeys keep their user-defined footprints and
legacy stair-void behaviour rather than silently rewriting manual geometry.

## Reproduce local scan checks

After `punctora-core import-e57 scan.e57 --output-dir imported`, run:

```sh
python scripts/verify_slab_zones.py imported/import-manifest.json --output-dir verification
python scripts/verify_slab_zones.py imported/import-manifest.json --output-dir full-verification --full-reconstruction
```

The script validates cache length, consumes all imported heights, records source
elevations and area support, saves candidates, and writes/validates an IFC. The
full mode also exercises walls and stairs. Source E57 files and derived customer
geometry must not be committed. Generated fixtures in `test_slab_zones.py` cover
slab pairs, rejected landings, concavity, holes, disconnected footprints,
persistence, crop evidence mapping and IFC void relationships.

## Remaining limits

The local full-cache trial on the supplied 39,068,825-point stairwell completed
in 309 seconds on the development container. It selected five zones and four
storeys, generated nine supported slab components and one enclosed-hole
candidate, and passed IFC schema/EXPRESS/tessellation checks. The remaining
stairwell gaps are open concave boundaries or disconnected components, not
automatically confirmed interior voids. Selected source elevations were
38.473; 41.122 to 41.312; 44.328 to 44.715; 47.676 to 48.047; and 51.251 metres.
Those elevations are results of the algorithm, not hardcoded inputs.

The initial slab-only trial took about 14 seconds. Whole-pipeline time includes
the existing wall/opening/stair processing which Run 4.2/4.3 will replace.
This is not a Windows hardware performance prediction or a visual acceptance
of every roof edge. CI exercises a generated hole-bearing native preview through
`scripts/SlabPreviewCheck`, in addition to the Python geometry tests.
The actual native preview check also passed on all nine scan-derived components
(1,154 void-cut cap triangles). Local regression checks passed 147 tests. Slab
supported areas ranged from 78.8% to 96.7%; the small 1.1-square-metre component
with 21.2% inferred area needs particular review. The top component had 95.4%
occupied support and 4.6% inferred area. None of these percentages certify that
an occluded roof portion has been recovered.

These tests are implementation and geometric-evidence checks, not independent
survey validation. Sparse/occluded faces, split-level buildings, inclined roofs,
transfer slabs and widely separated scan components can need explicit settings
or manual boundaries. Top slabs are not automatically classified as roofs.
Run 4.2 still needs to correct walls/windows/corners. Run 4.3 still needs global
stairs, landings and final stairwell headroom validation.
