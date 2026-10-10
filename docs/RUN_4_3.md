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
- Headroom is calculated per tread, including explicitly inferred interior
  treads, and combined with connected landing footprints. Every addition is
  clipped to its host slab and records source flights, step indices and landings.
- Observed slab holes are retained. Their overlap with a stair envelope and the
  additional cut area are recorded separately. Unsupported holes remain pending
  manual review rather than being declared stairwells.
- An independent per-tread/landing test checks physical and headroom residuals
  against the final slab solid. Nonzero residuals generate review warnings.
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
are reported separately; a calibrated whole-model unsupported percentage is
not available.

`scripts/render_stair_review.py` creates reproducible geometry review plates.
These are headless plan projections, not desktop screenshots or survey ground
truth. Actual desktop before/after visual acceptance remains a separate check.

Full-scan results are pending in this implementation checkpoint. Passing
generated tests must not be described as recognizing every stair in the scan.
The specific second-storey window acceptance item from Run 4.2 also remains open.
Run 5 stays blocked until the agreed visual and numerical completion gate passes.
