# M1 verification, 2026-10-08

Version: `0.1.0a1`. Tested locally on Linux x64 with Python 3.12.14 in a fresh virtual environment without system site packages. Dependencies were installed from `pyproject.toml`. No customer scans, pretrained models or research datasets were used.

## Result

**36 tests passed.** The two-storey developer demo reconstructed 2 storeys, 9 wall candidates, 3 candidate slabs and 3 inferred spaces. Its serialized IFC4 reopened successfully, passed schema/EXPRESS checks and tessellated its represented products without geometry errors.

The source wheel built successfully, installed into the fresh environment and ran the one-storey demo from outside the repository. `pip check` reported no broken requirements. This checks the Python package, not a standalone Windows installer.

| Regression or behaviour | Evidence |
| --- | --- |
| Repeated decoded E57-to-XYZ conversion | Same bytes and point count on rerun; replaces instead of appending. Checks decoded arrays, not reading an E57 file. |
| First-point loss in subsampling | First numeric point retained with no header and supported headers; malformed skipped rows rejected. |
| Cross-storey room leakage | Different floor plans remain separated; helper filters even an accumulated wall list by storey ID. |
| Hard-coded exterior thickness | Configured 0.42 m used; single-face thickness labelled inferred; material and load-bearing status unknown. |
| Rotation and coordinates | Floor rotated 27 degrees and translated in XY reconstructs without assuming axis alignment. |
| IFC space relationships | Spaces decompose their storey; introducing the upstream containment defect makes validation fail. |
| IFC window/door types and openings | Required type attributes exist; removing window partitioning fails validation; host void volume and filling placement checked. |
| Upper floor placement | Tessellated wall bounds remain 3.2 to 6.2 m, without doubling storey elevation. |
| File preservation | Failed XYZ writes and invalid IFC models preserve previous files; CLI rejects overlapping source/output paths. |
| Units and identities | CLI millimetres convert to metres; stable GUIDs distinguish element classes from spatial roots. |
| Oversized grids | Contour-grid limit rejects excessive raster allocation. |

## Reproduce

```sh
python -m pip install -e ".[test]"
python -m pytest -q
python -m punctora_core demo --two-storeys --output-dir outputs/demo
```

An automated workflow is added for Windows and Linux, Python 3.11, 3.12 and 3.13. Its presence is not a claim that all CI jobs have passed; inspect the actual workflow results.

## Evidence limits

The targeted data-handling and IFC defects have regression coverage, and the baseline processes generated XYZ examples end to end. Schema validation and geometry checks run on the serialized IFC before replacing the destination.

This does not establish performance on a real E57, survey accuracy, whole-cloud coverage/deviation, arbitrary building geometry or Windows desktop readiness. See [core limitations](CORE.md). M2 begins direct E57 decoding and coordinate handling.
