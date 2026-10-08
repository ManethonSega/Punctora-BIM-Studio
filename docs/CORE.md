# Experimental core, M1

This milestone adapts Cloud2BIM's raster-contour and parallel-face approach into a callable, headless baseline. It accepts decoded point arrays or local XYZ text. It is not the standalone desktop application and does not decode E57 files.

## Installation and commands

Create and activate a virtual environment with Python 3.11 to 3.13, then install from the repository:

```sh
python -m pip install -e ".[test]"
python -m punctora_core demo --output-dir outputs/one-floor
python -m punctora_core demo --two-storeys --output-dir outputs/two-floors
python -m punctora_core convert-xyz floor.xyz --units m --output-dir outputs/floor
```

Use `--units mm` for millimetre coordinates. Inputs must already be registered, local Cartesian coordinates with Z pointing up. Global survey coordinates and scan poses need M2's coordinate-frame handling. Supported XYZ columns are XYZ, XYZI, XYZRGB and XYZRGBI, separated by whitespace, with an optional `X Y Z` header. RGB and intensity are preserved in the data layer but not used for recognition.

An optional JSON settings file is passed with `--settings settings.json`, for example:

```json
{
  "grid_size_m": 0.02,
  "exterior_wall_thickness_m": 0.3,
  "assumed_wall_thickness_m": 0.2,
  "assumed_slab_thickness_m": 0.2
}
```

The Python `reconstruct` function also accepts explicit `Storey` bounds and footprints, useful when density peaks do not provide credible levels. The CLI does not yet expose this option.

## Output and evidence

| File | Contents |
| --- | --- |
| `model.ifc` | IFC4 extruded walls, candidate slabs and inferred spaces; explicit doors/windows when supplied through the Python model |
| `elements.json` | Versioned element data in metres, parameter provenance, unreviewed state, settings, source fingerprint and warnings |
| `validation.json` | IFC schema/EXPRESS findings and geometry tessellation checks, with their limited scope |
| `source.xyz` | Generated scan fixture, written only by the demo command |

Rewriting XYZ replaces rather than appends. XYZ and IFC destination files are replaced atomically; invalid IFC candidates never replace an existing IFC. The output set as a whole is not yet a transactional project save.

Spaces use storey decomposition, physical elements use spatial containment, and openings void their host walls and reference their fillings. Door/window types use required IFC4 attributes. Stable product GUIDs derive from project name, element class and ID, so renaming a project changes identities.

Parameter provenance is `measured`, `inferred`, `user_supplied` or `unknown`. Measured means fitted or derived from the provided points, not independently verified. Materials and structural status remain unknown. Filling geometry is a simple envelope, not reconstructed sash or leaf construction.

## Baseline limits

- Z-density peaks propose levels; furniture or incomplete scans can produce false or missed candidates.
- Convex horizontal footprints can bridge courtyards, concave outlines, holes and disconnected scanned areas. Candidate slabs need review.
- Walls come from a section at 70 to 90 percent of clear height. Furniture, sparse scans, complex wall profiles and missing surfaces can affect detection.
- Parallel observed faces estimate thickness. A single face uses a configured assumption; a boundary face is an exterior candidate, not a confirmed facade classification.
- Slab gaps between detected levels provide candidate thicknesses, not proof of slab construction. Boundary thicknesses are assumed.
- Spaces are inferred from closed wall loops; profiles with holes are not supported.
- Automatic opening detection, roofs, stairs, columns and building services are not implemented.
- Wall section fit RMSE covers selected supporting points only. It is not a whole-cloud deviation, coverage or project-tolerance report.
- XYZ is loaded into memory. A raster allocation guard prevents oversized contour grids, but this is not yet an out-of-core building-scale pipeline.

No real survey accuracy, clean Windows installation or desktop usability claim is made by M1. E57 decoding, scan transforms, invalid-point handling, coordinate mapping and scalable working data follow in M2.
