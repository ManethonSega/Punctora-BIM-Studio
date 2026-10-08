# Punctora BIM Studio

**From point clouds to editable BIM.**

Punctora BIM Studio is a planned standalone desktop application for importing registered E57 point clouds, reconstructing architectural elements, reviewing the results and exporting IFC4 with quality reports.

## Current status

**Step 2 / M1: experimental reconstruction and IFC core.** A developer command-line tool reconstructs storeys, walls, candidate slabs and spaces from local XYZ coordinates, and writes validated IFC4. Selected Cloud2BIM geometry routines are adapted with attribution, while orchestration and IFC relationships are rebuilt.

There is no desktop interface, direct E57 file reader, georeferencing, AI integration or installer yet. No real building scan has been processed. Automatic door/window detection is not enabled; explicitly supplied openings are supported by the exporter.

The first usable milestone targets Windows x64 and one representative building floor. It must run locally without Revit, an AI model or an NVIDIA GPU.

## Run the experimental core

Use Python 3.11 to 3.13 in a virtual environment. From this repository:

```sh
python -m pip install -e ".[test]"
python -m punctora_core demo --two-storeys --output-dir outputs/demo
python -m pytest -q
```

The demo writes `model.ifc`, `elements.json`, `validation.json` and a generated `source.xyz`. To process already registered local XYZ coordinates with declared units and Z pointing up:

```sh
python -m punctora_core convert-xyz floor.xyz --units m --output-dir outputs/floor
```

This is a baseline contour engine for simple vertical-wall interiors. Level detection, convex floor envelopes, missing wall faces and slab thickness assumptions require review. Successful IFC validation establishes schema and tessellation checks, not scan accuracy. See [core usage and limitations](docs/CORE.md) and [M1 verification](docs/M1_VERIFICATION.md).

## First usable version

1. Import E57 scans and confirm units, coordinate reference information and scan poses.
2. Reconstruct storeys, walls and slabs from observed surfaces.
3. Review point-cloud and model overlays in 3D, correct supported parameters and flag unresolved geometry.
4. Export IFC4 with spatial relationships and explicit provenance for inferred properties.
5. Produce IFC validation results and measured surface-deviation statistics.

Doors, windows and spaces follow once the basic pipeline passes its checks. AI remains optional and must use the same geometry refinement and validation pipeline.

## Development documents

| Document | Purpose |
| --- | --- |
| [Development plan](docs/DEVELOPMENT_PLAN.md) | Milestones and acceptance criteria |
| [Architecture](docs/ARCHITECTURE.md) | Desktop, worker, geometry, quality and AI boundaries |
| [Project requirements](docs/PROJECT_REQUIREMENTS.md) | Units, coordinates, evidence and quality requirements |
| [Dependency inventory](docs/DEPENDENCIES.md) | Candidate components and licence evidence |
| [Licence policy](docs/LICENSE_POLICY.md) | Rules for importing code, packaging libraries and models |
| [Third-party notices](THIRD_PARTY_NOTICES.md) | Attribution status and retained licence references |

## Licence

Original Punctora source and documentation are licensed under [Apache License 2.0](LICENSE). Adapted Cloud2BIM routines remain MIT. Third-party components retain their own licences. The dependency inventory distinguishes selected core dependencies from future candidates; no native dependency binaries or model weights are bundled here.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Do not commit building scans, project deliverables, credentials or model weights. Use small generated fixtures for public development examples.
