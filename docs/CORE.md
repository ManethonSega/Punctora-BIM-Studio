# Experimental core, M2 E57 import

The core combines the M1 Cloud2BIM-derived reconstruction baseline with direct E57 import and coordinate handling. It is still a developer command-line tool rather than the standalone desktop application.

## Installation and commands

Create and activate a virtual environment with Python 3.11 or 3.12, then install from the repository. IfcOpenShell 0.8.3 requires Python below 3.13:

```sh
python -m pip install -e ".[test]"
python -m punctora_core demo --output-dir outputs/one-floor
python -m punctora_core demo --two-storeys --output-dir outputs/two-floors
python -m punctora_core convert-xyz floor.xyz --units m --output-dir outputs/floor
python -m punctora_core convert-e57 building.e57 --output-dir outputs/building
python -m punctora_core import-e57 survey.e57 --output-dir outputs/import
```

E57 coordinates are metres by specification. The importer supports registered Cartesian or spherical scans, applies each scan pose once, removes coordinate-invalid/nonfinite records, and preserves scan membership, original record indices, colour, intensity and available validity flags in a project-local binary cache. It shifts the cloud into a double-precision local frame and records both 4x4 transforms needed to recover source coordinates. E57 `coordinateMetadata` is retained but marked unverified; its presence does not prove the CRS or vertical datum. Missing poses are reported and use identity transforms. Malformed quaternion poses are rejected.

`import-e57` creates the cloud and manifest independently of the reconstruction baseline, including scans that cannot yet produce building elements. Available sensor and acquisition metadata is retained; unsupported point fields are named in warnings.

Use `--chunk-points` to limit decoded E57 records held at once. The default is 1,000,000. This bounds decoder and cache-write memory, though reconstruction still materialises selected working arrays and is not yet a complete out-of-core pipeline.

For XYZ, use `--units mm` for millimetre coordinates. XYZ inputs must already be registered, local Cartesian coordinates with Z pointing up. Supported columns are XYZ, XYZI, XYZRGB and XYZRGBI, separated by whitespace, with an optional `X Y Z` header. RGB and intensity are preserved in the data layer but not used for recognition.

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
| `import-manifest.json` | E57 source SHA-256, scan poses and fields, invalid counts, bounds, cache layout and reversible coordinate transforms |
| `working-cache/` | Disk-backed points, scan indices, optional channels and validity masks for E57 imports |
| `source.xyz` | Generated scan fixture, written only by the demo command |

Rewriting XYZ replaces rather than appends. XYZ and IFC destination files are replaced atomically; invalid IFC candidates never replace an existing IFC. The output set as a whole is not yet a transactional project save.

E57 cache arrays are published as complete immutable generations. Repeated imports yield the same active point count, and a previous open cache remains readable on Windows. Failed decoding cleans its incomplete staging files. Prior complete cache generations are retained for existing readers; project cache cleanup will accompany M3 save/reopen support.

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
- XYZ is loaded into memory. E57 decoding and cache creation are chunked, while current reconstruction still operates on the combined working points. A raster allocation guard prevents oversized contour grids.

No real survey accuracy, clean Windows installation or desktop usability claim is made. Generated E57 checks establish implementation behaviour only. A representative real E57 trial follows after the remaining M2 fitting benchmark and M3 review interface.
