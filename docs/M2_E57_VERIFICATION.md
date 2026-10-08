# M2 direct E57 import verification

Status: implemented and checked with generated fixtures and two supplied E57 examples on 2026-10-08. Direct import, coordinate handling and the generated surface-method benchmark are implemented. See [M2 fitting verification](M2_FITTING_VERIFICATION.md) and [supplied E57 import verification](M2_SUPPLIED_E57_VERIFICATION.md). The sample checks establish import integrity for those files, not reconstruction accuracy or general scanner compatibility.

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

Current result: 74 tests pass on the local Python 3.12 environment, including complete wall source references after scan poses and invalid-record filtering. GitHub Actions provides the authoritative Windows/Linux and Python 3.11/3.12 matrix result for the published commit.

## Remaining M2 work

The supplied examples add full-record and repeat-import evidence for five-scan and single-scan Cartesian files, including RGB/intensity and a missing pose. They contain 1,213,990 and 4,067,815 retained points. Coordinate metadata is empty in both, and row/column fields are deliberately ignored with warnings. The reference decoder is shared with the importer, so independent scanner/reference acceptance is still required.

- Repeat the implemented contour/fixed-region/adaptive-region comparison on annotated real scan subsets.
- Measure peak memory and runtime on a representative building E57. Generated size measurements exist, but repeated synthetic records do not establish building-scale geometric diversity. Detection samples and original-record fitting temporaries are bounded; mapped pages, XYZ loading and output size still contribute memory/storage costs.
- Extend compatibility checks beyond the two supplied examples to known scanner/exporter variants and vendor extensions, using an independent reference. The sample checks and generated validity-field tests do not establish universal vendor compatibility.
- Confirm CRS and vertical datum with the user or project documentation before treating source coordinates as georeferenced map coordinates.

These field checks remain visible while M3 desktop development proceeds. They are required before real-survey acceptance, not a reason to claim generated results are real-survey validation.
