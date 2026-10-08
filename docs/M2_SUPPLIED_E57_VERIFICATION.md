# M2 supplied E57 sample verification

Checked 2026-10-08. Status: both supplied files pass direct-import integrity and repeat-import checks on Linux x86_64, Python 3.12.14, Punctora core 0.2.0a2 and pye57 0.4.19. This is additional M2 evidence, not real-survey or reconstructed-BIM acceptance. Source provenance, registration accuracy, ground truth and agreed model tolerances were not supplied.

## Inputs and measured import results

| Supplied example | Scans | Retained points | First measured import | Process peak at first import | Cache per generation | Source-aligned XYZ extent, m |
| --- | --- | --- | --- | --- | --- | --- |
| `pumpNoInvalidPoints.e57` | 5 | 1,213,990 | 0.628 s | 193.8 MiB | 81.0 MiB | 4.76 / 5.03 / 3.83 |
| `Station018.e57` | 1 | 4,067,815 | 2.175 s | 363.4 MiB | 271.6 MiB | 711.08 / 205.21 / 25.84 |

Machine-readable reports: [pump](benchmarks/m2-e57-pump.json) and [Station018](benchmarks/m2-e57-station018.json). Each contains the source SHA-256 and size for identifying the exact example. Both files retain all their coordinate records; no flagged-invalid or nonfinite coordinates were found. Both have RGB and intensity, with all retained values valid according to the available flags.

Measurements are one observed run per file in a fresh verification process, with numerical-library threads limited to one and a warmed filesystem cache from prior inspection/imports. Import time includes source hashing, native decoding, transformation, writing and validating the working cloud. The process peak includes the interpreter, imported libraries and resident mapped pages, not just decoder buffers. It is not a cold-start measurement, a hardware specification or a prediction for the owner's PC. The subsequent reference and repeat checks have a higher process peak, recorded separately in JSON. Cached arrays occupy more space than their compressed E57 source, and each repeat retains another generation.

## Checks performed

1. Import all records in 200,000-record decode chunks into immutable disk-backed cache arrays.
2. Separately read the file header and paged XML to obtain scan record counts and poses. Use SciPy's quaternion rotation to calculate source coordinates instead of the importer's pose helper. Empty E57 Float-node values in the XML are interpreted as zero, as confirmed by the native reader and generated zero-component fixtures.
3. Decode native coordinate/channel records in 65,536-record chunks and compare **every retained point**, RGB/intensity value, available validity flag, scan membership and original record index. Source-coordinate recovery uses the published working-to-source mapping. The maximum coordinate-component difference is below 1e-7 m for both files. This small arithmetic difference is a software consistency check, not achievable survey accuracy.
4. Repeat import in 75,000-record chunks while the first generation's arrays remain open. Compare all cache channels in bounded batches. All arrays and coordinate mappings match exactly; new generations are distinct and the first remains readable.
5. Compare source SHA-256 before and after. Both original files are unchanged.

The reference and importer share pye57/libE57Format for binary decoding. The XML pose parsing and rotation calculation are separate, but this is **not an independent E57 decoder, scanner calibration or registration check**. No independent viewer or vendor reference was used.

The verification utility also passed a small generated two-scan case with large coordinates, an invalid record, missing optional channels and zero quaternion components. Existing M2 regression results remain documented separately; no reconstruction-core behaviour was changed by this follow-up.

## Warnings and practical consequences

- Both files have a `coordinateMetadata` node whose string is empty. The importer treats this as absent. CRS, vertical datum and Z-up orientation remain unconfirmed; coordinate round trips do not prove georeferencing.
- Pump scan index 1 has no pose. Identity is the existing documented fallback and a warning is retained. Decoding succeeds, but correct registration of that scan has not been independently established.
- Both files carry `rowIndex` and `columnIndex`. These are deliberately ignored with warnings. XYZ, RGB, intensity, validity and source-record identity are retained. Organized image-grid reconstruction and embedded E57 images are outside the checked importer scope.
- Station018's source-aligned X extent is about 711 m. This exceeds the nominal span implied by SpatialLM's paper representation. It is evidence for explicit bounded crop/transform and stitching tests before AI integration, not evidence that any released checkpoint successfully handles this whole cloud. Cropping/stitching is future work.
- The samples are unannotated. Importing them does not establish wall, slab, opening or storey accuracy. No building reconstruction, IFC export or AI inference was performed on either supplied file during these checks.

## Reproduce locally

From the repository, with the existing core installed in Python 3.11/3.12:

```sh
python scripts/check_e57_import.py /path/to/pumpNoInvalidPoints.e57 --output-dir outputs/e57-check/pump
python scripts/check_e57_import.py /path/to/Station018.e57 --output-dir outputs/e57-check/station018
```

The utility verifies Cartesian examples, exits unsuccessfully on an assertion/error and writes `verification.json` only after checks succeed. Each file should be checked in a separate process. Set `OPENBLAS_NUM_THREADS=1` and `OMP_NUM_THREADS=1` before launch for the reported thread settings. Earlier cache generations are retained; generation lifecycle cleanup belongs to M3.

Only source fingerprints, bounded summary metadata, measured resources and independently written notes are recorded in this repository. The supplied PDF/E57 bytes, cloud coordinates, scanner identities, cache arrays and reconstruction outputs are not committed. The user's original attachments remain the source assets; reuse or redistribution terms for the example scans have not been established.

## What remains open

An annotated, representative building floor; confirmation of coordinates and scan registration; an independent E57/reference comparison; broader scanner extensions; measured reconstruction and correction effort; and real-survey acceptance against the supplied acquisition guidelines. These checks can proceed alongside M3 desktop development. See [M2 E57 verification](M2_E57_VERIFICATION.md), [M2 fitting verification](M2_FITTING_VERIFICATION.md) and [SpatialLM assessment](research/SPATIALLM.md).
