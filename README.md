# Punctora BIM Studio

**From point clouds to editable BIM.**

Punctora BIM Studio is a planned standalone desktop application for importing registered E57 point clouds, reconstructing architectural elements, reviewing the results and exporting IFC4 with quality reports.

## Current status

Repository foundation only. There is no runnable application, E57 importer, reconstruction engine, AI integration or installer yet. No building scan has been processed by this project.

The first usable milestone targets Windows x64 and one representative building floor. It must run locally without Revit, an AI model or an NVIDIA GPU.

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

Original Punctora source and documentation are licensed under [Apache License 2.0](LICENSE). Third-party components retain their own licences. The dependency inventory lists candidates, not installed or redistributed software.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Do not commit building scans, project deliverables, credentials or model weights. Use small generated fixtures for public development examples.
