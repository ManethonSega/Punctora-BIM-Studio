# Contributing

The current milestone is repository foundation. Follow the acceptance criteria in [the development plan](docs/DEVELOPMENT_PLAN.md).

- Keep contributions focused on the current milestone and explain the resulting behaviour and verification.
- Add upstream dependencies to the inventory before incorporating them, and pin versions when used.
- Preserve attribution on adapted code and record the upstream revision and modifications.
- Keep scans, customer documents, generated IFC deliverables, credentials and model weights outside Git. Use generated fixtures for reproducible public examples.
- Do not infer building materials, load-bearing status, concealed dimensions or a CRS as verified facts.
- Use targeted tests for geometry, transformations, floor isolation, persistence and IFC relationships.
- Document limitations accurately. A generated file or attractive preview is not evidence of accurate BIM reconstruction.

The planned source layout is described in the architecture; executable project scaffolding follows in the next milestone.
