# Quality Run 2: isolated recognition proposals

Stacked on quality Run 1, not on the older main branch. This is distinct from
the earlier desktop preview work also numbered Run 2.

## Implementation scope

The lifecycle is `prepare -> infer_chunk -> combine_tiles -> validate ->
write_proposal_set`. It produces an immutable, review-only ProposalSet, never
an accepted element, saved project mutation or IFC. Existing production
reconstruction and desktop detection remain classical and unchanged.

| Boundary | Implemented behavior |
| --- | --- |
| Source geometry | Original registered f64 coordinates, never preview data |
| Identity | Exact uint64 scan, original record and working-row arrays, including IDs above 2^53; reject global duplicates |
| Tiles | Stable XY lattice, immutable-ID context order, overlap plus original normal halo, exact application crop mask |
| Fusion | Majority vote count; tie uses lowest taxonomy index; winner retains maximum native score, not a calibrated probability |
| Cache | Actual input-array, provider, model, runtime, preprocessing, implementation, mapping, crop and tile-setting digests |
| Publication | Validate every array and manifest, then rename private staging atomically; never overwrite a malformed generation |
| Cancellation | Stop owned model process tree, close maps and delete only owned incomplete staging; saved models untouched |
| RAM | At most 70% available-at-start admission ceiling, stricter explicit cap, bounded index/fusion and sampled combined parent/child RSS |
| Diagnostics | Five-second checks/heartbeat and terminal state, callback outside cache staging |
| Evaluation | ID-only sample selection after inference, fingerprinted schema-1 labels-only sidecar, empty elements |

RSS sampling is not an OS hard allocation guarantee. A transient native
allocation can precede the next sample; an over-cap job fails visibly. Large
tiles are rejected, never silently decimated. Tile/index point limits are
explicit. The complete cloud is needed for normal context outside a crop.
The caller owns any source files and must never pass preview or already
decimated coordinates while claiming the complete-original scope.

Proposal taxonomy preserves Run 1's twelve classes plus beam, furnishing,
flow_controller, flow_terminal and energy_conversion_device. These additional
native labels remain visible but cannot fabricate unsupported geometry.
Unknown labels are -1. Every instance is `proposed` with explicit source-array
support scope; downstream acceptance must independently recompute support.

## Classical adapter

The baseline wraps the existing reconstruction unchanged and forces CPU only
for this comparison adapter. It retains observed faces, proposed geometry,
host IDs and measured/inferred provenance. Original points near observed wall
faces or horizontal surfaces can receive binary-support labels. Inferred
axes, voids, doors and windows do not magically become point-label truth.
This sparse baseline is not a learned semantic segmentation score.
Geometry-instance scores remain explicitly unavailable rather than borrowing
point-support scores as model confidence. Observed faces remain in proposals
for downstream evidence revalidation.

## Cloud2BIM experiment and findings

Reviewed upstream references:

- [Cloud2BIM DL material at cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e](https://github.com/VaclavNezerka/Cloud2BIM/tree/cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e/DL_module)
- [Pointcept model builder at 1342eda30e96cbb5fadf5374ff8eb18f6de15c71](https://github.com/Pointcept/Pointcept/blob/1342eda30e96cbb5fadf5374ff8eb18f6de15c71/pointcept/models/builder.py)
- [Pointcept DefaultSegmentorV2](https://github.com/Pointcept/Pointcept/blob/1342eda30e96cbb5fadf5374ff8eb18f6de15c71/pointcept/models/default.py)

The published Cloud2BIM directory contains documentation, synthetic results,
logs and Git LFS checkpoint pointers, but no runnable inference or exact model
configuration. The referenced checkpoint is 554,659,890 bytes with SHA-256
`de85b9c5dec3d2a14e175493acc177aff72417379c623e7aa2a6673225cceff8`.
It was not downloaded. Published synthetic scores are not Punctora accuracy.

The adapter therefore requires an **explicit local isolated Python**, exact
JSON model configuration, tensor-only checkpoint and runtime attestation,
all fingerprinted. No package install, model download or guessed config is
automatic. Only the child imports torch/Pointcept/model operators. The worker
verifies Python/package versions and installed Pointcept Python source-tree
digest against the attestation; the supplied commit remains a declared
provenance reference, not proof of an independently audited binary build.
Native extension package versions are recorded, not binary reproducible-build
certification. Strict `weights_only=True` loading rejects executable pickles.

The experiment uses original-neighbour PCA normals, radius 0.30 m, maximum
30 neighbours, normal-only input and a 0.06 m representative/inverse grid.
Canonical normal signs are an explicit reproducibility choice differing from
upstream's unoriented normals. Degenerate neighbourhoods remain unknown.
Exact training/inference parity is **not established**. No probabilities are
invented from raw logits. Strict deterministic operators may reject an
unsupported runtime rather than silently run nondeterministic kernels.

Missing local assets or an unsupported explicit device/operator can use the
classical CPU fallback with requested/used provider and reason recorded.
Digest mismatch, malformed logits, broken configuration and other internal
failures do not silently fall back. CPU transport is tested; full PTv3 CPU
operator support is not claimed. CUDA requires the isolated compatible stack.
There is no AMD/OpenCL inference support claim.

## Local API and commands

`run_recognition(cloud, identity, provider, cache_directory, ...)` accepts a
complete original CloudData with original IDs. E57 import already supplies
scan and source-record arrays; a missing working array uses exact source row
positions, never replacement E57 IDs. `identity` uses the same source SHA,
metre-frame mapping and crop as Run 1.

CLI input is a local schema-1 JSON manifest with keys `schema_version`,
`identity`, `source_scope: complete_original_registered_cloud` and `arrays`.
Arrays `points`, `scan_ids`, `record_ids`, `working_rows` are read-only .npy
files contained beneath the manifest directory. Each descriptor has `path`,
`dtype`, `shape` and `sha256` of the entire .npy file. Points are `<f8` N x 3;
IDs are `<u8` N. Use imported originals, not a preview export. The typed CLI
manifest is an optional developer interface, not a new desktop workflow.

```sh
python -m punctora_core recognition-propose quality-local/input.json --cache-dir quality-local/proposals --diagnostics outputs/recognition-status.json
python -m punctora_core recognition-propose quality-local/input.json --cache-dir quality-local/proposals --provider cloud2bim_experimental --assets quality-local/assets.json
python -m punctora_core recognition-export-samples quality-local/proposals/CONTENT_KEY quality-local/sample-keys.json --output quality-local/semantic-prediction.json
PYTHONPATH=src python scripts/verify_recognition_provider.py --output-dir outputs/recognition-generated
```

Optional `--tiles`, `--settings` and `--ram-gb` explicitly configure the
experiment. Diagnostics cannot overwrite input arrays/assets or live inside
the immutable cache. Semantic export cannot overwrite its key input or any
proposal artifact.

`assets.json` keys match Cloud2BIMAssets: absolute `python`, `checkpoint`,
`model_config`, `runtime_manifest`; SHA-256 fields for the three data assets;
`device` (`cpu` or `cuda:0`), and optional `timeout_seconds`. Runtime JSON
schema 1 declares `python_version`, `pointcept_commit`,
`pointcept_python_tree_sha256` and exact `packages` versions including numpy,
scipy, torch, spconv, torch-scatter and torch-cluster. The Python tree digest
hashes sorted .py relative POSIX paths followed by their file bytes, matching
the worker. Model JSON declares schema 1, exact `PREPROCESSING` from the
owned preprocessing module and the actual Pointcept `model` dictionary with
12 classes and three-channel backbone input. Missing configuration is not
permission to substitute a generic pretrained model.

Sample selection is a JSON list containing only `source_sha256`, `scan_index`
and `source_record_index`. Truth labels are rejected. Call this exporter after
recognition, then evaluate the separately fingerprinted sidecar with Run 1.
Outside-crop, unknown, unsupported and missing source IDs have explicit counts.
They do not manufacture predictions or pass an evaluation gate.

## Gate and forward implications

Internal tests cover contracts, corruption, original IDs, cache invalidation,
normal context, overlap order independence, classical host/provenance,
isolation, missing assets, fallback, cancellation, RAM admission and sidecars.
The generated smoke also runs the actual classical detector and cache replay.

**Implementation disposition: Proceed with revised future scope**, once these
internal checks pass. No repeat is required for absent external annotations,
visual review, designated hardware or externally supplied model weights.
Those qualify the completed nine-run system after Run 9, not each engineering
iteration. No improved real-building recognition or release acceptance is
claimed by this implementation.

Future scope must not assume Cloud2BIM publishes an executable exact runtime.
Before any learned-provider promotion, provide a pinned configuration and
runtime, check preprocessing/checkpoint parity and measure real-scan class
errors. Geometry runs remain able to use the production classical evidence
without waiting for that external qualification. Later hybrid selection must
handle unknown/unsupported native classes and native score scales explicitly.
Run 3's hybrid instance reconstruction and Run 4's evidence-backed geometry
should not treat this experimental grid as final IFC geometry. Run 8's semantic
caption/review integrations must preserve the experimental status and avoid
certainty or probabilities not supported by validation.
