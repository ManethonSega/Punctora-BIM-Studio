# Opening and stair candidates

Reconstruction now proposes empty rectangular door/window gaps and straight stair flights. Both appear in the element list and cloud/model overlay, support reviewed/flagged/rejected states and save in schema-2 projects. Older schema-2 projects load with an empty stairs list.

## Openings

The detector projects bounded source-cloud chunks into each reconstructed wall's local horizontal/vertical frame. A 50 mm (or larger configured grid) occupancy raster closes small sampling gaps. Candidates need a mostly rectangular empty region, supported jambs and lintel, and a supported sill for windows. Floor-touching gaps at least 1.7 m high become door proposals; elevated gaps become window proposals. Wall ends and ceiling-touching empty regions are excluded.

Edit kind (door/window), offset from the wall start, sill, width and height. The preview cuts accepted candidate geometry out of the wall and shows a simple coloured filling envelope. IFC exports IfcOpeningElement with IfcRelVoidsElement and an IfcDoor/IfcWindow filling, including type and IfcRelFillsElement. Rejected openings do not cut exported walls. Rejecting a host wall also excludes its openings.

Missing scan returns can still imitate an opening. Closed doors, reflective glazing, cluttered gaps, arches and gaps outside the size limits can be missed. Confirm candidates against the original scan. No frame, leaf or sash construction is inferred.

## Stairs

A bounded per-storey voxel sample supports local normal estimation. Horizontal patches with plausible tread dimensions are chained by ascending height, direction, width, going and rise. A flight needs at least four supported treads with consistent spacing. Rotated straight flights are supported; one candidate represents one flight.

Edit endpoints, base, width, rise, going, tread count and assumed tread thickness. Endpoint edits recompute going; going/count edits recompute the end along the existing direction. The model requires run = going × tread count. Original detection evidence remains unchanged after edits.

IFC exports an IfcStair aggregate containing an IfcStairFlight with tread envelope solids and measured/inferred provenance. The envelope does not represent a continuous structural stair body. Landings, railings, winders, curved stairs and hidden support structure are not inferred. Existing convex slab candidates may span a stairwell; this feature does not repair slab voids. Review slabs separately.

## Review and processing

The geometric support score is not a calibrated probability. Both detectors run on CPU and use existing NumPy, SciPy and OpenCV dependencies. No Constriq weights or binaries are bundled. Set `detect_openings_enabled` or `detect_stairs_enabled` to `false` in core reconstruction settings to disable an optional stage. Larger stair sampling voxels may lose treads. Opening checks stream source records per wall, so runtime scales with wall and source-point counts.

Synthetic regressions cover supported openings, solid/sparse-wall negatives, rotated flights, flat-floor/vertical-wall negatives, schema round trip, editing, rejection and IFC EXPRESS/tessellation validation. They do not establish real-building recall, precision or dimensional accuracy.
