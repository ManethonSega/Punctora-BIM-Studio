# Run 4: PunctoraSpecialistProvider runtime and desktop orchestration

**Current repair: 0.3.0a36.** [Inline specialist worker requests](RUN_4_REPAIR_A36.md) remove the transient `request.json` handoff that failed on the submitted RS 138 EG Kita crop. This builds on [A35 bounded proposal stitching and measured opening heights](RUN_4_REPAIR_A35.md) and [A34 standalone inference, early preflight, top status and returned-case topology diagnostics](RUN_4_REPAIR_A34.md). These supersede the optional-runtime delivery instructions below. No software installation is required by the portable Windows package; external model assets remain user-selected.

Previous repair: 0.3.0a33. See [the remaining stairwell profiles and diagnostic
repair](RUN_4_REPAIR_A33.md), retaining [the positive-wall and section-alignment
repair](RUN_4_REPAIR_A32.md) and [the CPU/runtime and 80% recognition RAM
policy](RUN_4_REPAIR_A31.md). The user extended Run 4
after both a29 results; [the eight-path a30 repair](RUN_4_REPAIR_A30.md) remains
the geometry baseline.
Provider artifacts remain review-only; a separate original-point validator now
adds unreviewed model candidates. The historical a28/a29 scope and tests below
are retained as an audit trail, not the current retest instructions.

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

The original pack-1 manifest SHA-256 was `8a66e03582328be3c5bbdf74a575fb3245824fb6f799a17f63a0024c648f92f0`. A31 uses provider 4.1 / pack contract 2 to bind the new runtime policy; its manifest and actual runtime plan are recorded in each result. All learned graph/companion hashes are unchanged. The ten graphs and four companions total 1,119,170,454 bytes and remain outside the repository.

## Runtime and evidence rules

- ONNX Runtime uses one isolated persistent interpreter per attempt with `CPUExecutionProvider`. A31 shares the explicit CPU budget across bounded independent image waves, retaining sequential graph execution and deterministic result order. Point inference receives its phase budget. Sessions use a RAM-bounded LRU cache, including reuse after preflight. Punctora never downloads a runtime or model.
- Missing runtime/assets may enter the declared classical fallback. Changed hashes, malformed graphs, tensors, indices or outputs fail visibly and never fall back.
- Recognition's selectable API RAM ceiling is 70–80%, default 80%, bounded by available RAM and total physical/container RAM; source/worker/descendant RSS is sampled together. Reconstruction sampling retains 70%. Explicit tile/view caps, cancellation, cleanup, atomic publication and content-addressed caches remain active.
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

The checked-in tests do not claim real-scan accuracy or final IFC improvement. The final local suite completed with **429 passing tests**. A separate content-bound smoke run used the supplied 1,119,170,454-byte pack through ONNX Runtime 1.23.2 on `CPUExecutionProvider`: A-J all reported active, branch I consumed its exact 40 inputs for 121 source/model-view points, 37 plan/section views completed, five TTA summaries were retained, and the acceptance counters remained zero for geometry changes, cuts and IFC objects. That generated fixture qualifies runtime wiring and evidence publication only; it is not a scan-quality result. Windows/.NET results are recorded by pull-request CI.

## Returned external checkpoint and a29 repair

The 2026-10-14 checkpoint did not produce a successful specialist result on any of the three scans:

| Scan | Requested mode | Observed result | Run 4 meaning |
| --- | --- | --- | --- |
| `RS 138 EG Kita.e57` | Punctora specialist | Failed at `infer_chunk`: original-point halo exceeded the 1,500,000-point cap | Dense interior input exposed a repairable exact-tiling defect. The earlier successful window/door observations came from classical mode and are not specialist evidence. |
| `RS 138 Treppenhaus Sued.e57` | Punctora specialist | Failed at `infer_chunk` with the same halo-cap message | The supplied crop contains 26,242,199 original points and reproduced the defect locally. |
| `RS 138 Fassade.e57` | Punctora specialist, both Auto and Exterior/partial | Failed at recognition admission under the old 70% calculation | Retained reconstruction RSS was incorrectly compared with a fraction of currently available RAM as though both shared the same origin. |

The cancellation/preservation check passed and does not need to be repeated for a29. The missing-ceiling observation belongs to the classical baseline; Run 6 will reassess ceiling evidence after a successful specialist checkpoint.

The a29 repair:

- filters spatial-index cells to the exact 3D halo before enforcing the cap;
- recursively partitions overflowing tiles in X, Y or Z without point decimation, while retaining bounded context for normals and recording every child core/halo;
- uses child-core voting at internal subdivision boundaries, preventing repeated context from multiplying votes;
- retains source evidence and releases the completed reconstruction index before recognition;
- defines the default job cap as baseline process RSS plus 70% of RAM available at recognition start, while an explicit user cap remains an absolute ceiling;
- persists admission diagnostics even when construction of the recognition control fails;
- reuses one isolated specialist worker and RAM-bounded ONNX sessions throughout the attempt, while preserving timeout, cancellation, malformed-output and process-tree cleanup rules.

The exact 26,242,199-point stair crop now partitions into 179 leaf tiles. The largest contains 1,496,840 context points, below the unchanged 1,500,000 cap; all source points are retained and the maximum subdivision depth is 11.

## Simplified a29 retest

The “A-J folder” simply means the existing model folder containing `model_A.onnx` through `model_J.onnx` and their required companion files. Do not create or rename another folder.

Use the same folder and unchanged thresholds, then run only these three checks:

1. `RS 138 EG Kita.e57` with **Punctora specialist**.
2. `RS 138 Fassade.e57` with **Punctora specialist** and **Exterior/partial scan**.
3. `RS 138 Treppenhaus Sued.e57` with **Punctora specialist**.

For each scan, first report only whether detection completed or failed. If it failed, attach the screenshot, per-job diagnostic JSON and `last-performance.json`. If it completed, confirm `PunctoraSpecialistProvider` requested, the displayed actual provider and A-J branch status, then attach one same-view cloud/overlay screenshot and list any obvious missing, extra, shifted, rotated, mirrored or wrongly scaled proposals by element class. Attach the saved `.punctora` project and assets when practical. No PDF is requested or produced.

Use this report form:

- **Run/build:** 0.3.0a29 / Run 4 repair
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
- **Cancellation result:** already passed on a28; repeat only if a new lifecycle problem appears
- **Attachments:** project/assets, diagnostics and paired screenshots
- **Result recommendation:** proceed, repair this run, redesign this run or revise a future run

The checkpoint selected **Repeat current run** because two repairable implementation assumptions failed: a fixed dense-tile halo and the RAM admission origin. It was not selected merely because external review was incomplete. After the a29 repair is published, Run 4 remains awaiting the three-result retest above.

## Handoff

After the checkpoint passes, freeze the provider/model-pack identity. Run 5 may consume D/J and E/B proposals for original-point wall/opening fitting; Run 6 owns A-led surfaces; Run 7 owns F/C/G beams and columns; Run 8 owns H-led stairs and ramps. None may treat Run 4 masks, boxes, logits or display ribbons as accepted dimensions.
