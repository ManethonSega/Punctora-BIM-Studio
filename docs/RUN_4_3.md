# Run 4.3: global stairs and stairwell verification

Version 0.3.0a14 implements building-wide straight-flight detection after slab
zones have been established. It uses geometric evidence, not scan-specific
elevations, storey counts or expected flight counts. Curved and spiral stairs,
railings and structural design remain outside scope.

## Implementation

- One spatially sampled building-wide pass estimates horizontal and vertical
  patches. Source working-row examples are retained for treads and landings.
  Local horizontal-density peaks separate tread faces even when noisy returns
  occupy the bins between them; consecutive occupied bins are not merged.
- Discrete rise/going fits require at least four observed treads, allow at most
  two missing interior treads between observations, and limit missing evidence
  to 40 percent of a flight. One missing terminal tread can be added only when
  an observed landing independently supports the next rise and tread footprint.
  A fitted sequence alone never justifies endpoint extrapolation.
- Vertical riser returns are recorded independently. They increase inspectable
  evidence but are not mandatory for scans that observe only tread surfaces.
- Changes in direction form separate flights. Only observed landing connectivity
  groups them into straight, L-shaped, U-shaped or multi-turn assemblies.
- Landings follow supported component outlines. The upper face is measured;
  thickness and the resulting lower face remain assumptions.
  Floor-integrated landings are semantic areas carried by the existing floor
  solid, avoiding a duplicate solid and an unjustified hole under the landing.
  Observed upper slab-face polygons also supply landing anchors at floor
  transitions. Landing regions are clipped to the observed entry/exit area;
  an entire floor is not turned into a landing or stairwell cut.
- Flights carry storey and nearest supported slab-zone associations. Unmatched
  endpoints retain null associations and a measured distance for review.
  Bounding storey slab-zone indices are recorded separately, so an intermediate
  landing does not masquerade as an unmatched building-level association.
- Headroom is calculated per tread, including explicitly inferred interior
  treads, and combined with connected landing footprints. Every addition is
  clipped to its host slab and records source flights, step indices and landings.
- Observed slab holes are retained. Their overlap with a stair envelope and the
  additional cut area are recorded separately. Unsupported holes remain pending
  manual review rather than being declared stairwells.
- An independent per-tread/landing test checks physical and headroom residuals
  against the final slab solid. Nonzero residuals generate review warnings.
  IFC export repeats the test on the actual dimensions and current voids after
  edits. Editing an integrated landing invalidates its old floor integration.
  Export verification uses cap polygons from reopened IFC slab meshes rather
  than assuming that a requested Boolean void was successfully cut.
- IFC exports each connected system as an IfcStair, its IfcStairFlight members,
  landing slabs and explicit slab voids. Geometric evidence, missing treads,
  source storeys and review states remain inspectable in IFC property sets.
  Flights and landings reference their own storeys while remaining members of
  the connected stair assembly.
- The desktop inspector exposes tread indices, inferred steps, riser support,
  slab associations, connected flights and opening boundary justification.

## Regression and acceptance

Generated tests cover rotated flights, missing interior treads, cross-storey
flights, L/U landing connectivity, separation without a landing, observed partial
holes, independent collision failures, persistence, IFC validation and reopening.
Existing slab, window, corner, coordinate and crop regressions remain in CI.

The supplied E57 remains the local field regression, not a CI input. The report
script records counts, evidence, residuals, stage timings, sampled peak RSS and
manual-review warnings. Slab inferred-area percentages and missing-tread indices
are reported separately, alongside landing raster support and inferred-tread
percentages; a calibrated whole-model unsupported percentage is
not available.

`scripts/render_stair_review.py` creates reproducible geometry review plates.
These are headless plan projections, not desktop screenshots or survey ground
truth. Actual desktop before/after visual acceptance remains a separate check.

## Supplied E57 result

The unchanged 745,524,224-byte E57 contains 39,068,825 source points. The final
local full-pipeline trial completed in 190.89 seconds, with sampled peak RSS
2.42 GiB. Level/slab-zone detection took 4.63 seconds, global stair processing
23.45 seconds and model stairwell verification 0.06 seconds. These are informal
local trial timings, not a controlled hardware comparison or Windows estimate.

| Result | Previous 0.3.0a13 trial | Run 4.3 trial |
| --- | ---: | ---: |
| Slab zones / storeys | 5 / 4 | 5 / 4 |
| Slab components | 8 | 8 |
| Walls / wall-opening proposals | 30 / 17 | 30 / 17 |
| Straight flight proposals | 4 | 6 |
| Connected stair assemblies | 4 | 1 |
| Landing areas | 3 | 7 |
| Slab-opening objects | 1 observed | 1 observed plus 10 justified envelope pieces |
| IFC validation and reopening | Pass | Pass |

The seven landing areas comprise three intermediate landing solids and four
floor-integrated areas. IFC contains one IfcStair, six IfcStairFlight members,
seven landing entities and explicit slab openings. Floor-integrated entities
carry semantic/evidence information while their solid is the existing floor.

All eight slab components pass physical-intersection and configured 2 m
headroom checks for the proposed stair system. The reopened IFC slab cap meshes
also pass the independent test, with residual area below 1e-6 square metres.
IFC schema/EXPRESS validation and tessellation report no errors. The final IFC
contains 28 opening entities including the 17 wall-opening proposals.

The local regression checks pass 171 tests (170 in the full-suite run plus the
added noisy-height field regression). The previous detector fails that added
fixture; the corrected detector passes. Generated tests establish algorithm
behavior and persistence, not independent survey accuracy. Before/after headless
geometry review plates were rendered and inspected. Actual desktop screenshot
comparison and independently annotated confirmation of every supported tread
remain visual acceptance items.

The specific second-storey window acceptance item from Run 4.2 remains open.
Run 4.3's numeric stair/void checks pass, but Run 5 stays blocked until the agreed
visual and numerical completion gate passes. Missing-tread envelopes, landing
thicknesses, uncertain opening classifications and unsupported wall corners
remain review proposals. No scan-specific elevations or counts are hard-coded.

## Preview correction in 0.3.0a15

The first Windows field test exposed a native preview failure on clipped stairwell
opening polygons. Sub-float-width edges in otherwise valid contours collapsed
when the desktop converted XY coordinates to floats before ear clipping. The
saved reconstruction existed, but the UI retained its previous revision, causing
the next detection attempt to fail with a revision conflict.

Landing and slab-opening previews now use constrained triangulation of their
original double-precision polygons, just as void-cut slabs already do. Meshes are
regenerated on edits and when opening older projects, without changing the saved
revision. Concave boundaries are preserved. A model display failure falls back
to the cloud while retaining the saved model and adopting its revision.

Regression coverage includes the actual scan's local opening and landing
contours, polygon area checks, legacy-project mesh refresh, and a desktop
walkthrough that injects a display failure after an atomic save then retries.
The full-scan model is also passed through the native scene loader. These checks
address display and retry reliability; field acceptance of reconstruction
accuracy remains pending.
