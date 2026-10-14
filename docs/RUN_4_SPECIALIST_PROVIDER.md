# Run 4: PunctoraSpecialistProvider runtime and desktop orchestration

Run 4 connects the supplied A-through-J ONNX model pack to **Detect elements** as a review-only proposal source. It does not accept, replace or resize building elements, create cuts, or write IFC objects. The deterministic reconstruction remains geometry authority until Runs 5 through 8 validate each physical element family against original points.

## Implemented boundary

`PunctoraSpecialistProvider` is distinct from the earlier experimental torch/checkpoint provider. Its content-bound manifest records every graph and companion SHA-256, task, tensor schema, local class contract, raster/point preprocessing, decoder and CPU runtime identity.

| Branch | Review-only output |
| --- | --- |
| A | Slab bands from physical vertical sections |
| B | Opening head/sill section queries; local classifier columns remain unresolved |
| C | Beam section queries |
| D | Wall plan foreground/subclass votes |
| E | Opening plan foreground/subclass votes |
| F | Beam plan masks |
| G | Column plan masks |
| H | Stair plan masks |
| I | Twelve-class point labels through the exact 40-input PTv3 graph contract |
| J | Query-aware oriented wall boxes from the declared BGR plan overlay |

The supplied pack resolves to manifest SHA-256 `8a66e03582328be3c5bbdf74a575fb3245824fb6f799a17f63a0024c648f92f0`. The ten graphs and four companions total 1,119,170,454 bytes. The model assets remain outside the repository.

## Runtime and evidence rules

- ONNX Runtime runs in an isolated interpreter with `CPUExecutionProvider`, sequential execution and two intra-op threads. Punctora never downloads a runtime or model.
- Missing runtime/assets may enter the declared classical fallback. Changed hashes, malformed graphs, tensors, indices or outputs fail visibly and never fall back.
- The 70% job memory ceiling, explicit tile/view caps, cancellation, child cleanup, atomic publication and content-addressed cache remain active.
- Canonical points stay float64. Scan IDs, original record IDs and working IDs remain unsigned integers. Model-only views use float32.
- Branch I validates all 40 inputs, four curve orders, native k3/k5 offset order, tail windows, pool clusters, sentinels, stable source ordering and the fixed 0.06 m grid before inference.
- Plan views use physical 10.24 m or 20.48 m fields, positive-Y row mapping, 0/30/60-degree views and true mirrors. Foreground consensus is separate from unresolved subtype voting.
- Section and plan artifacts keep reversible frames. Every displayed proposal ID maps through `support-index-v1.json` and `proposal-source-rows.npy` to rows in the immutable ProposalSet source arrays.
- Branch-A padding/cropping/Lanczos/window transforms and cross-window NMS are recorded. Branch-J uses the declared lossless BGR overlay, palette, alpha and Pillow bilinear resize; debug compression never becomes an inference input.
- Provider, model pack, runtime, active/missing/failed branches, loaded hashes, original/model-view populations and fallback reason are persisted. Transient local paths are excluded from published artifacts.

Specialist proposals remain translucent overlays in the current viewer. They are deliberately absent from editable model collections and from IFC export.

## Desktop modes

The desktop now offers:

1. **Classical** — current deterministic reconstruction only.
2. **Punctora specialist** — deterministic reconstruction plus A-J review overlays.
3. **Hybrid specialist + projected evidence** — specialist ProposalSet followed by the existing review-only hybrid fusion.

Choose the external model folder containing `model_A.onnx` through `model_J.onnx` and the four required `.onnx.data` companions. The UI and saved project show the requested provider, actual provider, active branches and missing/failed branches. A fallback is displayed as a fallback, never as a successful specialist run.

For development or the Run 4 checkpoint, create a Python 3.11/3.12 environment from `requirements-specialist-cpu.txt` and set `PUNCTORA_SPECIALIST_PYTHON` to its absolute interpreter path before launching the desktop. Packaging this optional environment into the final distribution remains Run 13 responsibility.

## Internal gate

The Run 4 tests cover:

- exact model/companion content binding and wrong-companion rejection;
- 1/31/127/128/129/255/256/257/513-voxel PTv3 stages and tail windows;
- native kernel column order, invalid indices and pre-allocation RAM rejection;
- source-key ordering before survey-scale centring;
- plan mirror and pixel/world round trips at large coordinates;
- branch-A section transforms and rectangular section restoration;
- A/C sigmoid, B row-softmax, mask foreground/subclass and J query-aware decoding;
- isolated worker invocation, truthful CPU provider state, source support, cache replay and zero geometry promotion;
- missing-runtime fallback, malformed-output no-fallback and cancellation cleanup;
- desktop-request fallback reporting and project rejection of unbound overlays.

The checked-in tests do not claim real-scan accuracy or final IFC improvement. The final local suite completed with **428 passing tests**. A separate content-bound smoke run used the supplied 1,119,170,454-byte pack through ONNX Runtime 1.23.2 on `CPUExecutionProvider`: A-J all reported active, branch I consumed its exact 40 inputs for 121 source/model-view points, 37 plan/section views completed, five TTA summaries were retained, and the acceptance counters remained zero for geometry changes, cuts and IFC objects. That generated fixture qualifies runtime wiring and evidence publication only; it is not a scan-quality result. Windows/.NET results are recorded by pull-request CI.

## External checkpoint — awaiting user execution

Use the same model pack and settings for all three cases. Save the project before each cancellation test.

1. Configure `PUNCTORA_SPECIALIST_PYTHON`, launch the candidate, import/open the scan and confirm Z-up.
2. Select **Punctora specialist**, select the A-J model folder, save the chosen crop, then run **Detect elements**.
3. Run one interior crop, one exterior/façade crop and one stair-related crop. Keep each crop small enough for the visible plan-tile limit; do not change thresholds between comparisons.
4. Confirm the UI says `PunctoraSpecialistProvider` was requested, shows the truthful actual provider and lists branches A-J as active. Record any missing/failed branch and the displayed reason.
5. Compare point cloud and proposal overlay from the same camera. Report false and missing wall, opening, slab, beam, column and stair regions separately. At this checkpoint judge proposal placement, mirroring, rotation, shift and scale—not final IFC geometry.
6. Start one additional specialist detection, cancel it, then reopen the previously saved project. Confirm the prior saved model is unchanged and the cancelled attempt did not become a published generation.
7. Attach the saved `.punctora` project with its assets folder, `last-performance.json`, the applicable per-job diagnostic JSON, and paired cloud/overlay screenshots. No PDF is requested or produced.

Use this report form:

- **Run/build:** 0.3.0a28 / Run 4
- **Computer and GPU:**
- **Scan and crop:** interior, exterior or stair; include approximate bounds
- **Requested provider / displayed actual provider:**
- **Active / missing / failed branches:**
- **What I expected:**
- **What happened:**
- **Where:** storey, elevation, façade/room or marked screenshot
- **Proposal class:** wall, opening, slab, beam, column or stair
- **Error type:** false, missing, mirrored, rotated, shifted or scaled
- **Frequency:** once, intermittent or every run
- **Cancellation result:** saved project preserved / problem observed
- **Attachments:** project/assets, diagnostics and paired screenshots
- **Result recommendation:** proceed, repair this run, redesign this run or revise a future run

Until that evidence is returned, the Run 4 disposition is **awaiting external checkpoint**. Missing external evidence does not select “Repeat current run.”

## Handoff

After the checkpoint passes, freeze the provider/model-pack identity. Run 5 may consume D/J and E/B proposals for original-point wall/opening fitting; Run 6 owns A-led surfaces; Run 7 owns F/C/G beams and columns; Run 8 owns H-led stairs and ramps. None may treat Run 4 masks, boxes, logits or display ribbons as accepted dimensions.
