# Punctora BIM Studio

**From point clouds to editable BIM.**

Punctora BIM Studio is a planned standalone desktop application for importing registered E57 point clouds, reconstructing architectural elements, reviewing the results and exporting IFC4 with quality reports.

## Current status

**M2 development implemented; M3 desktop review is next.** The developer core reads registered E57 scans in bounded-memory chunks, applies each scan pose once, filters invalid coordinates, creates a disk-backed local working cloud and writes validated IFC4 with a reversible mapping to source coordinates. Contour and CPU region-growing providers are compared on repeatable generated benchmarks. Detection uses capped voxel samples; wall faces are refitted to original records with traceable evidence files. Local XYZ input remains supported.

There is no desktop interface, AI integration or installer yet. Two supplied E57 examples, with 1.21 million and 4.07 million points, have passed full-record import-integrity and repeat-import checks. No annotated real building reconstruction has been accepted. Broader scanner compatibility, representative reconstruction performance and confirmed CRS/vertical datum remain field acceptance checks. See [supplied E57 verification](docs/M2_SUPPLIED_E57_VERIFICATION.md). Automatic door/window detection is not enabled; explicitly supplied openings are supported by the exporter.

The first usable milestone targets Windows x64 and one representative building floor. It must run locally without Revit, an AI model or an NVIDIA GPU.

## Run the experimental core

Use Python 3.11 or 3.12 in a virtual environment. The pinned IfcOpenShell 0.8.3 dependency does not support Python 3.13. From this repository:

```sh
python -m pip install -e ".[test]"
python -m punctora_core demo --two-storeys --output-dir outputs/demo
python -m punctora_core convert-e57 building.e57 --output-dir outputs/building
python -m punctora_core demo --settings docs/region-growing-settings.json --output-dir outputs/region-demo
python -m punctora_core.benchmark --cases clean rotated thin_partition --check --output-dir outputs/benchmark
python -m pytest -q
```

Use `import-e57` instead of `convert-e57` to create the working cloud and import manifest without reconstructing building elements.

The demo writes `model.ifc`, `elements.json`, `validation.json` and a generated `source.xyz`. To process already registered local XYZ coordinates with declared units and Z pointing up:

```sh
python -m punctora_core convert-xyz floor.xyz --units m --output-dir outputs/floor
```

Contours remain the default: region growing is a selectable geometric experiment, not an AI dependency. Level detection, convex floor envelopes, missing wall faces and slab thickness assumptions require review. Successful IFC validation establishes schema and tessellation checks, not scan accuracy. See [core usage and limitations](docs/CORE.md), [M2 fitting results](docs/M2_FITTING_VERIFICATION.md) and [M2 E57 verification](docs/M2_E57_VERIFICATION.md).

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
| [M3 implementation plan](docs/M3_IMPLEMENTATION_PLAN.md) | Desktop work sequence, automatic GPU viewport use and completion checks |
| [M2 E57 verification](docs/M2_E57_VERIFICATION.md) | Direct-import behaviour, automated evidence and remaining M2 work |
| [Supplied E57 verification](docs/M2_SUPPLIED_E57_VERIFICATION.md) | Full-record checks of the two supplied examples, resource measurements and coordinate warnings |
| [M2 fitting verification](docs/M2_FITTING_VERIFICATION.md) | Provider comparison, measured resource use and M3 handoff |
| [Project requirements](docs/PROJECT_REQUIREMENTS.md) | Units, coordinates, evidence and quality requirements |
| [Dependency inventory](docs/DEPENDENCIES.md) | Candidate components and licence evidence |
| [SpatialLM paper assessment](docs/research/SPATIALLM.md) | Versioned research findings, proposal precision, scan evidence and future AI experiment |
| [Licence policy](docs/LICENSE_POLICY.md) | Rules for importing code, packaging libraries and models |
| [Third-party notices](THIRD_PARTY_NOTICES.md) | Attribution status and retained licence references |
| [Attributions](ATTRIBUTIONS.md) | Creator credits and licence notices mapped to code, runtime, models and research |

## Licence

Original Punctora source and documentation are licensed under [Apache License 2.0](LICENSE). Adapted Cloud2BIM routines remain MIT. Third-party components retain their own licences. The dependency inventory distinguishes selected core dependencies from future candidates; no model weights are bundled here.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Do not commit building scans, project deliverables, credentials or model weights. Use small generated fixtures for public development examples.
