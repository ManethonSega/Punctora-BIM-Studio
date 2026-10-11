# Run 4: glazed façade reconstruction and height legend

Candidate version: 0.3.0a21. This continues on `run2/interactive-preview`,
the cumulative candidate containing Runs 1 through 4. Main is unchanged.

## Dedicated frame geometry

The opening stage reuses the existing spatial index and original local points.
It searches independently supported rectangular bays on observed local depth
planes, including sparse frame planes behind or in front of a dominant glass
return plane. A small depth histogram is collected during the first raster
pass, rather than adding a cloud traversal. Up to three local planes are
examined, and their actual repeated point visits remain in diagnostics.
The complete cloud is not resampled or converted to f32 for reconstruction.

Repeated bays require supported vertical jambs, sill and head rails, consistent
height and spacing, and empty or consistently recessed interiors. Long façade
sequences do not inherit the ordinary opening width/height caps. The sequence
must contain at least two bays and span 4.5 m. Frame support is inspected up to
0.2 m past fitted host endpoints, because fitting can shorten a host to its
glass returns; output bay envelopes remain clipped to the finite host span.
Evidence distinguishes observed jamb positions from clipped opening bounds.

Floor-to-ceiling bays remain windows. Automatic ordinary doors require a
floor-connected portal without a supported sill, supported jambs/head, a
bounded width and separation between the head and storey ceiling. Low sill
and sufficient height alone cannot classify a door. Material and operability
are still inferred or unknown; these are geometric proposals requiring review.

## IFC policy

Normal openings and weaker repeated façade evidence export as `IfcWindow`.
At least four aligned bays, narrow supported intervening mullions and
continuous supported sill/head rails propose an `IfcCurtainWall` assembly.
The curtain parent has no competing solid body. Its `IfcPlate` panels and
`IfcMember` mullions are aggregated children, and a single zone void removes
the original opaque wall material between its bays. Perimeter wall material
outside the measured zone remains. The frame profile, 60 mm frame depth and
10 mm panel depth are explicitly inferred envelopes. Suspension, structural
role and glass composition are unverified and recorded as such in IFC.
Glazing panels and normal windows receive a shared translucent display style;
that presentation style does not assert a measured glass material.

Rejected bays are omitted. Missing, flagged, edited or rehosted bays, or a
changed host, disable the whole-zone cut and assembly. Remaining nonrejected
bays fall back to individual windows. Raw model geometry is also checked
against the saved detection snapshot, so a direct edit cannot reuse stale
assembly evidence. Slab-opening validation from Run 3 is unaffected.

## Fixed local height legend

The height view displays a vertical blue, cyan, yellow and red gradient,
labelled **Local height Z [m]**, with minimum, 33%, 66% and maximum values.
CPU and OpenGL colouring use the same fixed complete-cloud local Z bounds.
Import reuses the E57 importer's original f64 bounds; it does not perform a
new cloud scan to establish the legend. Cropping, sectioning, point density,
camera movement and reopening never renormalize these colours.

Legacy E57 projects reuse complete-cloud bounds from their import manifest.
Legacy generated projects without full bounds retain their initial preview
scale, reported explicitly as a legacy preview scale in diagnostics. The
legend is hidden when the cloud is hidden or a nonheight colour mode is used.

## Verification and pending field acceptance

Generated regressions cover empty and recessed glass bays, rotated façades,
dominant glass versus sparse frame planes, reconstruction without a supplied
wall, wide masonry piers, validated curtain decomposition and opaque-wall
volume, stale assembly fallback, unchanged f64 coordinates/source IDs,
indexed/full-cloud equivalence and unsampled height extremes. Existing normal
door/window and staircase regressions remain required. Native walkthroughs
check legend visibility, mode switching and stable scale during orbit,
cropping and reopening; CI retains a legend screenshot.

Neither the target façade image/scan nor the 210,167,583-point project nor
`RS 138 Treppenhaus Sued.e57` is available in this workspace. The available
Word survey guidelines contain no façade images. Generated fixtures and CI
cannot close those real-project exit requirements. Rerun both projects in this
candidate, inspect the façade and staircase IFC, check zero fixture slab cuts,
measure Intel UHD orbit FPS/restore delay, and measure complete reconstruction
including evidence export on the same computer. The under-20-minute gate and
30 FPS Intel UHD gate remain pending until those measurements pass.
