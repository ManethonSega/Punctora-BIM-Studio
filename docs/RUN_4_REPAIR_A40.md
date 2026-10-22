# Run 4 A40: idempotent stair-opening revalidation

## Returned A39 failure

The user confirmed that the archive name and initial report were mistaken. The test and all returned evidence belong to `RS 138 Treppenhaus Sued.e57`, matching the immutable import manifest: SHA-256 `758bffcc05e5704fd678220786f84c5ba4e38e6f110dfc356f2f40fd3f9745fb`, 745,524,224 bytes. The project contains four storeys, six stair flights, seven landings and twelve slab openings.

The 39,068,825-point A39 attempt passed runtime/model preflight and completed base reconstruction. Recognition failed after 3,027.77 seconds in `original_point_geometry_fusion`, at the final `BuildingModel.validate()` call, with `Element IDs must be nonempty and unique`. Peak combined recognition RSS was 5,643,714,560 bytes, below the 38,192,775,987-byte cap. The saved model was preserved.

The failure was not ONNX inference, RAM admission, atomic diagnostic publication or an empty identifier. Specialist fusion added a supported horizontal surface, then revalidated dependent stair clearances. That path deterministically regenerated the stair-opening candidates for every existing slab and appended them to the twelve existing openings. Eleven regenerated candidates reused eleven existing IDs, so the global identity validator correctly rejected publication.

## Repair

- Stair-opening reconciliation is idempotent by deterministic element ID.
- A regenerated candidate with the same host and footprint reuses the existing object instead of appending a duplicate.
- Existing review state and explicit IFC-cut approval are preserved.
- The reused candidate is excluded from its own observed-hole comparison, so it is not misreported as independent observed evidence.
- A reused ID with a changed host or footprint fails closed with a specific identity-geometry error instead of silently overwriting reviewed geometry.
- Existing duplicate IDs remain an explicit error rather than being silently deleted.

The attached project model provides a direct replay without rerunning inference: twelve existing slab openings plus eleven deterministically regenerated candidates reconcile to twelve unique openings, and the model validates. No recognition threshold, ONNX asset, coordinate mapping, source identity, stair fit, opening boundary or IFC eligibility rule changes in A40. Desktop/core version is `0.3.0a40`.

## Internal evidence and remaining checkpoint

The RED regression reproduced the caller-visible failure by reconciling the same derived stair opening twice. Before the repair it returned two elements with the same ID. After the repair it returns one element, preserves review/approval state and passes full model validation. The returned-project replay records `before=12`, `regenerated_candidates=11`, `after=12`, `unique_ids=12`.

Local verification: `556 passed` in the complete Python suite; source compilation and `git diff --check` also pass.

External quality acceptance remains pending. Retest the same `RS 138 Treppenhaus Sued.e57` project with A40, then report whether publication completes and whether stair, wall, opening and slab geometry remain aligned with the cloud.
