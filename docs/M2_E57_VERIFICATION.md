# M2 direct E57 import verification

Status: implemented and checked with generated fixtures on 2026-10-08. This completes the direct-import and coordinate-handling part of M2. It does not complete the surface-detection benchmark or establish performance on a real survey.

## Implemented behaviour

- Reads Cartesian and spherical E57 scan records through pye57 0.4.19.
- Decodes a configurable number of records at a time instead of loading a complete scan through `read_scan`.
- Applies each E57 quaternion/translation pose exactly once.
- Excludes coordinates marked invalid and rejects nonfinite coordinates.
- Preserves scan membership and original record indices, double intensity, full-range RGB and available channel-validity flags in flat disk-backed arrays.
- Retains sensor/acquisition metadata and warns about absent poses and ignored point fields; rejects malformed pose quaternions.
- Publishes complete immutable cache generations, allowing repeat import while earlier memory-mapped arrays remain open on Windows; failed decoding leaves earlier generations intact.
- Creates a compact local metre frame while retaining exact source-to-working and working-to-source 4x4 transforms.
- Records the source SHA-256, byte size, scan headers, fields, poses, invalid counts, bounds and cache schema in `import-manifest.json`.
- Retains E57 `coordinateMetadata` without claiming that it proves a CRS or vertical datum.
- Writes an IFC4 `IfcMapConversion` from working coordinates back to the E57 source frame and a site property set describing the mapping.

## Automated evidence

The generated E57 checks cover two scan positions, a 90-degree scan rotation, flagged invalid records, actual spherical E57 files, missing optional channels/poses, double intensity, RGB values above 255, channel-validity flags, source coordinates around 4,000,000 m / 5,000,000 m, repeat imports with live readers, simulated decode failure, rejected bad poses, all-invalid scans, import-only CLI use and end-to-end IFC validation. Recovered source coordinates and IFC map-conversion offsets are compared with known values.

Run:

```sh
python -m pip install -e ".[test]"
python -m pytest -q
```

Current result: 51 tests pass on the local Python 3.12 environment. GitHub Actions provides the authoritative Windows/Linux and Python 3.11/3.12 matrix result for the published commit.

## Remaining M2 work

- Benchmark the current contour baseline against normal-based region-growing on the same generated and real scan subsets.
- Measure peak memory and runtime on a representative building E57. Cache creation is chunked, but current reconstruction still processes the combined working point array.
- Test vendor-specific E57 extensions and channels from real scanners; generated validity-field tests do not establish vendor compatibility.
- Confirm CRS and vertical datum with the user or project documentation before treating source coordinates as georeferenced map coordinates.
