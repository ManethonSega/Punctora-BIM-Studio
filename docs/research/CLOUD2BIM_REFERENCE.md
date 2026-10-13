# Cloud2BIM consolidated technical reference

Reference version: **1.3**. Updated: **2026-10-13**. Project: **Punctora BIM Studio**.

This is the maintained reference for Cloud2BIM research, the supplied Cloud2BIM-AI package, the repeated deep passes and their implementation consequences. It consolidates the current conclusions; historical reports remain the audit trail. Update this file through normal Git commits as implementation or new assets change the evidence.

**Current direction:** use the earlier research results and the user's successful Cloud2BIM experience as the development premise. Integrate the specialist plan/section/refinement pipeline, preserve original point evidence, and improve the result through the user's subsequent testing. The recognition audit after version 1.0 adds nine findings and answers the open questions to their supported extent. Version 1.2 adds fifteen viewer/visual findings in the [viewer audit](CLOUD2BIM_VIEWER_AUDIT.md), including the previously omitted CAD camera module, IFC rendering recipes and Punctora display gaps. Version 1.3 adds CB-059/060: evaluate the documented ActiViz VTK integration for Avalonia 12 first, and distinguish the useful E57-to-XYZ working-data route from format-independent recognition and preserved source evidence. Run 4 remains the next reconstruction implementation, with the corrected kernel order and additional recall/repeatability fixtures below.

The [nine-run design](https://github.com/ManethonSega/Punctora-BIM-Studio/issues/1#issuecomment-6143707055) governs implementation order. Internal checks gate each engineering run. Independent real-scan annotations, visual review and designated-hardware qualification follow completion of all nine runs. Missing external checks never require repeating an engineering run.

## Contents

1. [Evidence, sources and superseded conclusions](#1-evidence-sources-and-superseded-conclusions)
2. [Assets, model roles and taxonomy](#2-assets-model-roles-and-taxonomy)
3. [Pipeline and Punctora integration state](#3-pipeline-and-punctora-integration-state)
4. [Image, decoder and coordinate contracts](#4-image-decoder-and-coordinate-contracts)
5. [PTv3 preprocessing, indices and fusion](#5-ptv3-preprocessing-indices-and-fusion)
6. [Walls and openings](#6-walls-and-openings)
7. [Floors, slabs, ceilings, corners and roofs](#7-floors-slabs-ceilings-corners-and-roofs)
8. [Stairs, ramps, columns, beams and descriptions](#8-stairs-ramps-columns-beams-and-descriptions)
9. [Memory, lifecycle and diagnostics](#9-memory-lifecycle-and-diagnostics)
10. [Controlled probe register](#10-controlled-probe-register)
11. [Implementation handoff and decision gates](#11-implementation-handoff-and-decision-gates)
12. [Open questions and update procedure](#12-open-questions-and-update-procedure)
13. [Fingerprint and inspection appendices](#13-fingerprint-and-inspection-appendices)
14. [Viewer architecture and visual-quality plan](CLOUD2BIM_VIEWER_AUDIT.md)

The companion [evidence register](cloud2bim-evidence-v1.json) retains derived asset signatures, CPU smoke results and generated probe summaries in machine-readable form. The [additional audit evidence](cloud2bim-open-ended-audit-v1.json) preserves version 1.1's native anchors, source recheck and eleven generated probe groups. The [viewer audit evidence](cloud2bim-viewer-audit-v1.json) adds version 1.2's rendering/camera observations and six generated probes. The [integration/XYZ follow-up](cloud2bim-viewer-integration-xyz-v1.json) records version 1.3's revised VTK route and traced E57-to-XYZ reconstruction handoff. These files contain no supplied weights, executable, scans or recovered full application source.

## 1. Evidence, sources and superseded conclusions

### Evidence labels

| Label | Meaning |
| --- | --- |
| **V** | Verified from graph structure, file identity or a controlled local runtime/geometry probe. The particular probe's scope applies. |
| **N** | Recovered from bounded inspection of compiled branches or direct native configuration assignments at the pinned executable. |
| **P** | Package/public documentation, embedded literal settings or reported upstream results. Not independently reproduced unless separately marked V. |
| **A** | Deliberate Punctora adaptation or implementation requirement. Distinct from native equivalence. |
| **Q** | Remaining focused question or deferred qualification. Does not create an external-check implementation gate. |

Successful graph loading, finite logits, class agreement, geometric completeness and accurate IFC reconstruction are different measurements. The probes below establish their stated contracts. They did not run the complete Windows application or establish complete native application parity.

### Source register

| ID | Source | Version or scope |
| --- | --- | --- |
| S1 | [Public Cloud2BIM research repository](https://github.com/VaclavNezerka/Cloud2BIM/tree/cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e) | Commit `cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e`; original research code and DL README. |
| S2 | [User's Cloud2BIM fork](https://github.com/ManethonSega/Cloud2BIM) | Earlier project context; do not treat an unpinned fork head as the supplied package. |
| S3 | [Supplied Cloud2BIM-AI folder](https://drive.google.com/drive/folders/1IdlqlQ6JE7rol2l119Iqk1ysWlitcNvV?usp=drive_link) | Packaged Windows application, ten graphs and four external weight files; fingerprints below. |
| S4 | [Pointcept](https://github.com/Pointcept/Pointcept/tree/1342eda30e96cbb5fadf5374ff8eb18f6de15c71) | Commit `1342eda30e96cbb5fadf5374ff8eb18f6de15c71`; serialization, structure, pooling and PTv3 math. |
| S5 | [Cloud2BIM paper](https://arxiv.org/html/2503.11498v1) | Older research pipeline; distinct from the supplied specialist package. |
| S6 | [ONNX Runtime providers](https://onnxruntime.ai/docs/execution-providers/index.html), [Rust ort](https://github.com/pykeio/ort) | Deployment references. This audit qualifies CPU execution only. |
| S7 | [Punctora Run 3 commit](https://github.com/ManethonSega/Punctora-BIM-Studio/tree/0b11e84be8cd656d007c64f238bfdcc8bfa59b92) | Integration state inspected during the audits; separate from `main`. |

Pointcept files used: [structure.py](https://github.com/Pointcept/Pointcept/blob/1342eda30e96cbb5fadf5374ff8eb18f6de15c71/pointcept/models/utils/structure.py), [serialization/default.py](https://github.com/Pointcept/Pointcept/blob/1342eda30e96cbb5fadf5374ff8eb18f6de15c71/pointcept/models/utils/serialization/default.py), [serialization/hilbert.py](https://github.com/Pointcept/Pointcept/blob/1342eda30e96cbb5fadf5374ff8eb18f6de15c71/pointcept/models/utils/serialization/hilbert.py), and [PTv3 base](https://github.com/Pointcept/Pointcept/blob/1342eda30e96cbb5fadf5374ff8eb18f6de15c71/pointcept/models/point_transformer_v3/point_transformer_v3m1_base.py).

### Audit trail

| Record | Contributions retained here |
| --- | --- |
| [Initial supplied-copy investigation](https://github.com/ManethonSega/Punctora-BIM-Studio/issues/1#issuecomment-6148793886) | Inventory, graph roles, hashes, CPU smoke, embedded surface/index methods and revised asset availability. |
| [Pipeline and multi-voxel pass](https://github.com/ManethonSega/Punctora-BIM-Studio/issues/1#issuecomment-6149622386) | Plan/section chain, specialist provenance clues, desktop integration gap, tail/normal/kernel sensitivities, render ablations and additional authoring helpers. |
| [Decoder and geometry pass](https://github.com/ManethonSega/Punctora-BIM-Studio/issues/1#issuecomment-6150181520) | Actual section decoder branches, sill classification, 88 geometry defaults, staged refitting, pixel conventions and surface partitions. |
| [ONNX-focused pass](https://github.com/ManethonSega/Punctora-BIM-Studio/issues/1#issuecomment-6150621195) | Odd/rectangular mask shapes, wrong companions, malformed-but-accepted indices, corner transforms, RPE scale and recursive operators. |
| [Final handoff pass](https://github.com/ManethonSega/Punctora-BIM-Studio/issues/1#issuecomment-6150920920) | Representative ordering, vote confidence, counters, caps, live sessions, slab reset, stair completion and thin surfaces. |
| [Additional open-ended audit evidence](cloud2bim-open-ended-audit-v1.json) | Corrected native kernel order, centring-order sensitivity, class/foreground votes, connected rescue, component restoration, renderer/storage fidelity, query identity and native stage ordering. |

### CB-001: current interpretation and corrections

| Earlier interpretation | Current conclusion |
| --- | --- |
| The first inventory stated 1,254,436,758 total model bytes. | Rehashing and summing the 14 files during consolidation gives **1,119,170,454 bytes**. Individual recorded sizes/hashes match; the earlier aggregate was incorrect. |
| Run 2 could not establish a supplied executable exact inference route. | S3 supplies usable ONNX assets, including I on CPU. Keep Run 2's completed boundary and add a distinct ONNX provider. |
| Every recognition model shares PTv3's synthetic provenance. | B/E legacy names indicate real/mixed-data specialist lineages. Aliases are provenance clues, not verified datasets. |
| B column 0 means door and column 1 means window. | The downstream native choice uses local sill height; the classifier column is not used for that choice. |
| Normal sign, representative choice or legal-shaped indices are harmless. | Controlled changes materially alter logits/labels. Pin and validate those contracts; stable ordering must precede centring as well as representative selection. |
| The earlier exploratory kernel-column order can become the native adapter template. | CB-035 resolves the native order: the last grid column varies fastest. Correct the earlier independent builder before integration; historical sensitivity results retain their original scope. |
| Shape-compatible external tensors can substitute for one another. | Exact bindings are required; a wrong companion can load and produce finite, incorrect output. |
| Every mask needs dimensions divisible by 32. | All five accepted the six tested odd/rectangular sizes with exact output dimensions. Preserve the trained physical scale. |
| Native confidence is model probability. | I's emitted confidence is overlap vote agreement. Store classifier margin and coverage separately. |
| Slab augmentation unconditionally carries old scene state. | The inspected entry resets `LAST_SLAB_ANALYSIS` to None. Preserve this in a job-local implementation. |
| More broad audit passes must precede implementation. | The current contracts support Run 4. Use focused investigation for concrete mismatches or changed assets. |

Earlier opening skepticism in the historical reports is superseded by the user's accepted development premise. Preserve the concrete technical findings and honest test scope without reopening that premise.

### CB-002: original research foundation

The public research pipeline supplies useful density/image/morphology reconstruction and IFC authoring foundations. Earlier review identified fixed wall thickness (450 mm), unsupported material/load-bearing defaults, IFC relationship/type defects, cross-floor room leakage and repeated conversion work. These are historical integration lessons, not assertions that every defect remains in current Punctora. Original-point fitting, floor isolation and independent IFC validation remain required.

The public DL README reports voxel OA 0.930/mIoU 0.749 and full-resolution OA 0.918/mIoU 0.736 for checkpoint `run_20260803_0021`. FlowController has zero support, so its mIoU averages 11 classes. Twelve synthetic buildings were divided by random tiles (76/17/25), rather than a demonstrated held-out-building split. Door precision is 0.650; a real-room illustration has no numerical ground truth. These are component results, separate from complete IFC geometry.

Its training account attributes improvement to repaired learning-rate scheduling and cosine decay; an inconsistent tile-relative height feature harmed a 14-channel experiment. Initial integration should use the supplied models and declared features. Additional feature channels or retraining require a separate experiment.

## 2. Assets, model roles and taxonomy

### CB-003: supplied package inventory [V/P]

The inspected root listing contained 85 direct items. The visible `src` folder contained an icon; first-party modules were compiled into a Windows x64 Nuitka executable. This is a packaged software reference, not a complete editable source checkout.

Ten `.onnx` files and four companion `.onnx.data` files total **1,119,170,454 bytes**, independently rehashed and summed during consolidation. The executable is **231,476,776 bytes**, modified **2026-09-09T19:01:56Z**, SHA-256 `81040406a1ef6bb0ed4b38ddb044fd3fd5712503ed50adf579d234580527aacb`.

Static parsing consumed all 38 selected first-party module tables, containing 10,470 primitive constants. A later bounded inspection checked particular compiled branches and direct configuration assignments. The executable was never launched or imported. Primitive tables/docstrings do not establish every runtime branch or end-to-end outcome.

### CB-004: graph roles and interfaces [V/P]

`B` in a shape means batch size; `H/W` are image dimensions; `N` is the initial voxel count. All model features/outputs are float32; I's 39 index inputs are int64.

| Model | Role | Input | Output | External companion |
| --- | --- | --- | --- | --- |
| A | Physical slab bands in vertical sections | `[1,3,560,560]` | `dets [1,300,4]`, `labels [1,300,1]` | None |
| B | Opening heights in vertical sections | `[1,3,560,560]` | `dets [1,300,4]`, `labels [1,300,2]` | None |
| C | Beam heights in vertical sections | `[1,3,560,560]` | `dets [1,300,4]`, `labels [1,300,1]` | None |
| D | Wall plan mask | `[B,1,H,W]` | `[B,3,H,W]` logits | `model_D.onnx.data` |
| E | Opening plan mask | `[B,1,H,W]` | `[B,3,H,W]` logits | None |
| F | Beam plan mask | `[B,1,H,W]` | `[B,2,H,W]` logits | `model_F.onnx.data` |
| G | Column plan mask | `[B,1,H,W]` | `[B,2,H,W]` logits | `model_G.onnx.data` |
| H | Stair plan candidate mask | `[B,1,H,W]` | `[B,2,H,W]` logits | `model_H.onnx.data` |
| I | Index-fed PTv3 semantic prior | `feat [N,3]` plus 39 index arrays | `seg_logits [N,12]` | None |
| J | RF-DETR oriented wall boxes on plan overlays | `[1,3,576,576]` | `dets [1,300,4]`, `labels [1,300,3]`, `angles [1,300,1]` | None |

The detector output named `labels` is a float classifier logit tensor, not an integer label array. D/E/F/G/H also emit raw logits. Graph metadata contains no class-name mapping. Detector-local IDs stay local until an explicit branch contract maps them.

Legacy aliases recovered from package settings:

| Graph | Legacy asset alias |
| --- | --- |
| A | `rfdetr_slabs_149epoch.pth` |
| B | `rfdetr_opening_height_real_mix_2026_03_23.pth` |
| C | `detr_beam_height_2026_03_08_130epoch.pth` |
| D | `walls_only_unet_2026_02_28_271epoch.pt` |
| E | `openings_unet_real_2026_03_19_2lvl.pt` |
| F | `Unet_beams_2026_03_22_lvl2_39epoch.pt` |
| G | `Unet_columns_2lvl_synth_2026_03_22_30epoch.pt` |
| H | `Unet_staircases_2026_03_12_140epoch.pt` |
| J | `libreyolo_obb_best.onnx` |

These are verified alias entries. They do not independently verify the training corpus or performance.

### CB-005: semantic mapping [P/A]

I uses the native 12-class semantic order. Punctora's proposal taxonomy is `punctora-building-v1`, with 17 classes. The verified Run 2 mapping is `[0,5,2,11,7,12,8,1,13,14,15,16]`.

| Native ID | Native class | Punctora proposal ID | Punctora name |
| --- | --- | ---: | --- |
| 0 | Wall | 0 | wall |
| 1 | Slab | 5 | slab |
| 2 | Window | 2 | window |
| 3 | Column | 11 | column |
| 4 | Roof | 7 | roof |
| 5 | Beam | 12 | beam |
| 6 | Stair | 8 | stair |
| 7 | Door | 1 | door |
| 8 | FurnishingElement | 13 | furnishing |
| 9 | FlowController | 14 | flow_controller |
| 10 | FlowTerminal | 15 | flow_terminal |
| 11 | EnergyConversionDevice | 16 | energy_conversion_device |

Punctora-only IDs are opening 3, floor 4, ceiling 6, landing 9 and ramp 10. I cannot directly distinguish floor/ceiling faces, tread/landing or ramp/roof. A proposal class does not establish accepted schema/IFC support for that element.

### CB-006: exact asset binding [V/A]

Stripped graph structures match for A/C, D/E and F/G/H. Their learned weights differ. A/B and A/C share 336 named tensors with zero byte-identical tensors; D/E share 94 with zero identical. F/G/H share 101, but only seven small fixed tensors (56 bytes) match. Do not share learned encoders or substitute branches on this basis.

Bind **task + graph hash + every companion hash + external tensor layout + class contract + renderer/preprocessing/decoder versions** before session creation. Compatible wrong companions can pass checking and inference. Validate asset availability distinctly from identity failure: missing assets can select a declared fallback; incorrect hashes or malformed bindings are visible integrity failures. Artifact caches and live sessions use the same content-bound identity.

## 3. Pipeline and Punctora integration state

### CB-007: coordinated production chain [P/N]

| Stage | Reference method | Punctora consequence |
| --- | --- | --- |
| 1 | Vertical overview section | Separate renderer with explicit base, padding and pixel/world transform. |
| 2 | A physical bands, optionally I semantic augmentation | Propose surface bands; retain measured/manual/inferred distinctions. |
| 3 | Horizontal surfaces and storey masks | Keep local connected patches before global sequencing. |
| 4 | Slabs and height groups | Do not make complete pairs a prerequisite for exterior work. |
| 5 | Upper/lower/middle plan slices | Fingerprint elevation band, physical window and image recipe. |
| 6 | D/J walls; F/C beams; G columns; H stairs | Task-specific proposals followed by original-point geometry. |
| 7 | E plan candidates then B opening sections | Joint host/opening fitting; score alone cannot authorize a cut. |
| 8 | Local point surface checks and IFC assembly | One accepted geometry/profile path for preview, persistence and IFC. |

The primary transferable improvement is this coordinated plan/section/refinement chain. PTv3 is an optional contextual prior. Loading I alone does not reproduce the application's reconstruction.

### CB-008: implementation state at the inspected Run 3 commit [V]

| Component | Implemented capability | Remaining work |
| --- | --- | --- |
| Run 1, [PR #3](https://github.com/ManethonSega/Punctora-BIM-Studio/pull/3) | Frozen output facts, independent evaluation contracts, source identities, deterministic metrics and generated fixtures. | Final independent real-scan qualification after Run 9. |
| Run 2, [PR #4](https://github.com/ManethonSega/Punctora-BIM-Studio/pull/4) | ProposalSet v1, isolated torch/Pointcept experiment, classical provider, original uint64 IDs, bounded tiling, raw-logit fusion, atomic caches, fallback and cancellation. | Separate I ONNX index-fed adapter and specialist branches. The torch worker cannot consume I directly. |
| Run 3, [PR #5](https://github.com/ManethonSega/Punctora-BIM-Studio/pull/5) | f64 both-wall-view projections, exact point/pixel maps, optional isolated vision protocol, complete-link fusion and review-only ElementGraph. | Native plan/section renderers, accepted hosts/profiles/cuts and production orchestration. |
| Desktop detection | `worker.py` dispatches to `projects.reconstruct_project`, which uses classical `reconstruct` or budget comparison. | Explicit optional specialist selection through the worker and project path in Run 4. |

Runs 1/2/3 reported 333/370/403 passing local tests, respectively; Run 2/3 CI passed on the recorded Linux/Windows matrix. Those counts record implementation checks. They do not establish improved complete-building recognition.

Run 3's lower-left wall-face occupancy/depth/count/RGB NPZ inputs are different from D/J horizontal plans and A/B/C vertical sections. Preserve their frames and do not substitute one representation for another. Thin or incomplete column components can retain `geometry: null`; do not invent volume to satisfy a schema.

The classical production path remains the default until final qualification supports promotion. New experimental mode must report the requested and actual providers, active/disabled branches and fallback reasons.

## 4. Image, decoder and coordinate contracts

### CB-009: branch-specific preprocessing [P/N/V]

| Branch | Reference recipe | Important constraint |
| --- | --- | --- |
| A/B/C generic sections | OpenCV linear resize to 560 square; image values scaled to 0..1; graph starts Cast then projection/Conv. | No ImageNet input normalization in this branch. Restore using actual original raster width and height. |
| D/E/F/G plan masks | Grayscale, mean 0.5/std 0.5; native 1024-pixel windows resized to 512. | Model pixels per metre, polarity, slice elevation and reversal matter. |
| H stair mask | Grayscale, same normalization; native 2048-pixel window resized to 512. | Distinct physical field of view; do not reuse F/G's window merely because the graph matches. |
| J oriented wall plan | BGR NumPy without channel swap; PIL bilinear squash to 576; /255; ImageNet means `[.485,.456,.406]`, stds `[.229,.224,.225]`. | Native padded square tiles make resizing isotropic. No letterbox substitution or generic YOLO decoder. |

Plan prediction uses six views: rotations 0/30/60 degrees and their mirrored counterparts, with at least four votes per class. H uses the middle slice; the other plan specialists use the upper slice. The legacy upper slice begins around floor +1.5 m, which can omit low/sparse walls. Optional I wall rescue must examine broader storey evidence instead of simply repeating that slice.

A's section treatment includes fixed ten-pixel white padding at top/bottom, five-percent cropping on left/right, width resize to 1024 with Lanczos, nine-pixel gray lines at four-percent left/right positions, vertical windows up to 1024 and cross-window NMS at 0.3. Padding is ten centimetres only at 0.01 m/pixel. These renderer operations remain separate from the generic 560 detector resize.

### CB-010: A/B/C score and box decoding [N/V]

All section boxes are normalized `(cx,cy,w,h)`. Restore `(x1,y1,x2,y2)` using original width/height independently, then clip to native pixel-index bounds `[0,W-1]` and `[0,H-1]`. Keep the native index-bound contract distinct from Punctora half-open boxes.

| Branch | Native score/class behavior |
| --- | --- |
| A/C, one classifier column | Sigmoid; generic wrapper emits detector-local class ID 1. |
| B, two classifier columns | Stable row softmax, maximum score and argmax classifier column. |
| J | Separate sigmoid/query-class decoder described below. |

For B, the winning softmax is at least 0.5. At a 0.4 threshold, all 300 queries survive, including in the tested white section. This native score cannot establish a physical opening. Preserve raw logits and native decoding; any alternate sigmoid/calibration must have a distinct decoder identity and be tested separately.

The native opening height function selects the highest-confidence box. Downstream extraction assigns **door when local lower height <0.15 m above the floor; window otherwise**. It does not use B's winning column for that choice. The additional audit confirms that E's nonzero classes are consumed together as opening-plan candidates. Low windows, uneven floors, absent sill returns and semantic disagreement need explicit handling. A manual base constrains interpretation; it does not become a measured floor.

B's section includes 0.15 m context above/below. Invert height using the actual section transform, remove the extension and only then add world base. The illustrative inversion is `local_height = (H-y)*pixel_size - 0.15`. Store actual rendered dimensions and every preceding crop/resize offset.

### CB-011: J decoding and oriented geometry [P/V]

J applies sigmoid to 300 queries by three columns, flattens query/class scores, selects the top 300 and applies score >0.25 in the documented candidate path. It does **not** apply NMS there; the configured IoU argument is unused in that path. Native class columns remain branch-local.

Angles are `tanh(...) * pi/2`, in radians, as independently verified in the graph. Allow ordinary float32 boundary rounding. Keep winding, centre/width/height convention, padding and valid tile bounds explicit.

For rectangular crop adapters, inverse-map all four corners through the complete affine. Anisotropic inverse resize changes angle and orthogonality. In a 35-degree, 1024x640 fixture, the restored long-axis angle was 23.64 degrees; keeping 35 degrees gave maximum corner error 38.67 pixels. The native square/padded path avoids this particular anisotropy. Original f64 points still determine the accepted wall.

### CB-012: dynamic mask shape and deployment [V]

All D/E/F/G/H accepted `32x32`, `33x33`, `64x96`, `65x97`, `127x161` and `128x192` with finite exact-H/W outputs. All five batch-two 64x96 cases matched separate CPU calls exactly. No multiple-of-32 gate is needed for these tested cases.

Their internal decoder uses nearest-neighbor resize, asymmetric coordinates and floor rounding. Validate output shape and preserve those graph operations in deployment. Dynamic shapes do not authorize silent changes to the established physical window/model scale.

### CB-013: explicit coordinates and original evidence [N/V/A]

| Representation | Convention to retain |
| --- | --- |
| Native horizontal point raster | Floor quantization; row `H-1-y_index`. |
| Native opening contour inverse | `H-row`, differing by one pixel from the raster cell's lower edge. |
| Semantic image mapping | Separate rounded/H-y convention; do not inherit another raster formula. |
| Surface-analysis grid | Positive-Y world rows and cell centres; no plan-image Y flip. |
| Run 3 wall-face projection | Lower-left origin, half-open boxes, mirrored opposite view and exact original-row associations. |
| Geometry authority | f64 local/world coordinates and original scan/record identities. |

Every frame stores origin/basis, effective pixel size, row direction, centre/edge convention, rotation/flip/expanded offsets, crop/tile/padding offsets, resize sizes, section extension/base, valid bounds and reverse source mapping. A point-to-centre tolerance is half a pixel; contour vertices and detector boundaries use their declared conventions.

Subtract a local f64 origin before float32 model/OpenCV fitting and restore in f64. The survey-size fixture near 7,000,000/5,000,000 m lost up to 0.07 m with direct float32 conversion; local-origin conversion had zero error in that fixture. Original E57 coordinates and uint64 record IDs never become raster centres or float32 evidence. Keep IDs above 2^53 as integers throughout.

## 5. PTv3 preprocessing, indices and fusion

### CB-014: I is an index-fed graph [V/P]

I uses ordinary ONNX operations, opset 18, with no custom domains found recursively. It has 2,449 top-level nodes and **2,485 including eight If branch graphs**. A backend checklist must include nested Identity/Squeeze/Constant/Reshape and reduction behavior, including ScatterElements. spconv is not required to execute this exported graph through CPU ORT.

The features are **three normal channels**, not XYZ/RGB/intensity. The stem weight shape is `[125,3,32]`. Encoder block counts are `[2,2,2,6,2]`, decoder `[2,2,2,2]`; attention patch cap is 128.

### CB-015: preprocessing and representative selection [P/N/V/A]

Native documented settings are XY tiles 8 m, overlap 2 m, grid 0.06 m, maximum 1.5 million voxels per tile; Open3D hybrid normals use radius five grid cells (0.30 m) and at most 30 neighbors, without an orientation step. Arbitrary eigenvector sign is part of that recipe.

Run 2's independent PCA recipe uses a canonical-positive sign, original-neighbor halo and its own sampling/frame rules. Do not inherit it silently under a native-equivalence claim. Keep normal estimator, neighborhood population, sign rule, coordinate frame, representative selection and inverse mapping in the ONNX provider fingerprint.

The public DL account also identifies degenerate normals when scans are reduced to around 0.5 m spacing, beyond the 0.30 m neighborhood radius. Record insufficient neighborhood support and abstain/fall back explicitly rather than assign reliable semantics to a degenerate feature view.

The inspected native engine uses `np.unique` first-sample indices for representative coordinates/features and retains the inverse back to original tile rows. Different row order can therefore choose different normal features in the same voxel. For Punctora, select representatives by stable integer scan/record keys; version this as an independent adaptation. Averaged normals are another separate experiment. The representative never replaces original geometry/evidence.

The export's documented canonical grids are nonnegative, with stable sorting/head selection and order shuffling disabled. This differs from unmodified native/public Pointcept behavior. Package-reported canonical mIoU is about 0.7384 versus 0.7484; reported maximum logit difference around 1.4e-5/argmax agreement 1 refers to a patched deterministic reference, not the unmodified stochastic path. Those parity/evaluation claims were not independently reproduced.

### CB-016: complete 40-input index contract [V/P/A]

`Ns` is the population at stage s. `Ks=min(128,Ns)` for nonempty stages. There is one float32 `feat [N0,3]` plus these 39 int64 arrays:

| Stage | Grid/kernel arrays | Attention arrays | Pooling | Index input count |
| --- | --- | --- | --- | ---: |
| 0 | `s0_gc [N0,3]`, `s0_k3 [N0,27]`, `s0_k5 [N0,125]` | `s0_o0/o1_win [ceil(N0/K0),K0]`, corresponding `_inv [N0]` | `p0_cluster [N0]` | 8 |
| 1 | `s1_gc [N1,3]`, `s1_k3 [N1,27]` | `s1_o0/o1_win`, corresponding `_inv` | `p1_cluster [N1]` | 7 |
| 2 | `s2_gc [N2,3]`, `s2_k3 [N2,27]` | `s2_o0/o1_win`, corresponding `_inv` | `p2_cluster [N2]` | 7 |
| 3 | `s3_gc [N3,3]`, `s3_k3 [N3,27]` | `s3_o0/o1/o2/o3_win`, corresponding `_inv` | `p3_cluster [N3]` | 11 |
| 4 | `s4_gc [N4,3]`, `s4_k3 [N4,27]` | `s4_o0/o1_win`, corresponding `_inv` | None | 6 |

The companion evidence register records the exact 40 graph input names. Validate semantics before inference:

1. Finite contiguous float32 features with exactly three columns; unique nonnegative int64 voxel coordinates aligned with retained source mappings.
2. Four curve orders: Morton, transposed Morton, Hilbert, transposed Hilbert. Use pinned stable sorting and exact order scheduling. Exploratory depth is `max(1,(max_grid+1).bit_length())`, bounded to 16.
3. k3/k5 maps have 27/125 columns and values only in `[0,Ns]`; Ns is the missing-neighbor sentinel. Verify centre/self and each requested spatial offset. **Use CB-035's recovered native column order**, with grid column 0 slowest and column 2 fastest. The earlier independent probe's opposite order is retained only as a historical experiment, not the adapter template. Complete native-helper execution parity remains separate.
4. Window padding repeats real rows from the preceding window for a tail, rather than wrapping arbitrarily or fabricating zeros. A flattened window and its inverse must restore every original stage row exactly.
5. Pooling follows the pinned stride-two/code-right-shift-by-three convention when depth permits, stable cluster heads and matching parent coordinates/IDs.
6. Finite `[N0,12]` output is restored through voxel inverse and original source keys. Empty views yield valid empty artifacts without inference.

Runtime legality is insufficient: negative Gather indices and shifted in-range inverse arrays can produce finite, wrongly assigned logits. These preflight rules are required, including across Python/Rust.

### CB-017: learned physical scale [V/A]

I's 12 inspected RPE clips saturate at +/-15 grid bins. At 0.06 m and stride-two stages, per-axis half-spans are **0.90, 1.80, 3.60, 7.20 and 14.40 m**. They are saturation distances, not hard attention cutoffs.

Changing the voxel grid changes spatial encoding, convolution and normal-neighborhood meaning. Keep the initial grid fixed. Use deterministic subdivision and declared model-view sampling for memory control; never silently coarsen the grid or weaken original evidence. A changed grid has a different provider identity and testing scope.

### CB-018: tile fusion and native confidence [N/V/A]

Native I takes each tile's hard voxel argmax, restores tile point rows, adds per-class votes and chooses argmax (ties favor lower native ID). It emits `floor(255 * winning_votes / total_votes)` as uint8 agreement. Uncovered rows are label -1/agreement 0.

| Votes | Native agreement | Meaning at threshold 160 |
| --- | ---: | --- |
| One tile | 255 | Passes even with a tiny classifier margin. |
| One vote each for two classes | 127 | Fails; explicit tie rule applies. |
| Two agreeing of three | 170 | Passes. |
| Three agreeing of five | 153 | Fails. |
| No votes | 0 | Unknown, not background. |

Store raw logits/score margin, agreement, contributing tile count and coverage independently. Agreement 255 means unanimous available votes, not engineering certainty. Run 2's raw-logit fusion is distinct; an ONNX fusion alternative needs its own identity.

Use wide vote counters. Native uint8 wraps 256 same-class votes to zero; this was not a default-overlap failure, but would matter for increased overlap or accumulation. Do not combine separate generations' votes without a declared policy.

## 6. Walls and openings

### CB-019: supported wall reconstruction [P/N/A]

Use D wall masks, optional I wall rescue, the plan overlay and overlapping J OBB tiles for candidate generation. Fuse cross-tile proposals with centre weighting. Then apply the recovered sequence:

1. Merge cross-tile candidates.
2. Refit local longitudinal extents with **zero growth**.
3. Reconcile repeated/twin-face observations.
4. Remove or realign junction artifacts only when independent support permits.
5. Propose axis-family/run regularization and local junction closing.
6. Refit **width only**, preserving repaired endpoints.
7. Trim unsupported free-end stubs and review short dead ends.

A full length refit after junction closing would undo repaired endpoints. Original-point terminal/plane evidence still governs every extension and trim. Separate corridor walls, real short/diagonal walls and supported opening intervals must survive. Transitive union-find grouping alone cannot establish one physical wall; retain complete-link/evidence checks.

### CB-020: recovered wall controls [N]

The investigation recovered 88 literal defaults across nine configuration types, plus four OBB metadata defaults, checked against direct native dictionary assignments. Selected implementation-relevant values follow. Pixel values must be converted with the **effective** raster scale; 0.01 m/pixel is only the illustrative native scale. Constructor defaults can be overridden by application settings.

| Type | Recovered controls |
| --- | --- |
| Merge | Angle 12 degrees; IoU 0.25; same-class true; collinear stitching false; gap 40 px; perpendicular fraction 0.6/minimum 6 px. |
| Dedup | Angle 10 degrees; overlap fraction 0.45; twin-gap fraction 0.75/minimum 2 px; maximum wall width 100 px; face-pair true. |
| Shake | +/-6 degrees, step 0.1; default translations zero; along step 1 px/perpendicular 0.5 px; length/thickness scales `[1]`; two rounds; padding 10 px; metric **precision**, beta 0.5; minimum score 0. Application settings enable perpendicular shift up to 4 px. |
| Snap | Extra band 3 px; presence 0.20; minimum 30 pixels; pad 16 px; maximum growth fraction 0.1; minimum length 6 px. |
| Refit | Extra band 3 px; presence 0.30; minimum 30 pixels; **growth zero**; minimum length 6 px; cross-ribbon percentiles 2/98; width 5..100 px; perpendicular search 6 px. |
| Junction | Collinear angle 6 degrees; perpendicular fraction 0.6/minimum 6 px; gap 35 px/support 0.25; snap reach/lateral 45/30 px; corner reach 50 px/minimum angle 30 degrees; axis joins true; stitch/snap IoU drop 0.01/0.05. |
| Axis graph | Family tolerance 7 degrees; minimum weight 2; line offset fraction 0.7/minimum 7 px; run gap 60 px/support 0.25; junction reach/lateral 55/35 px; coverage guard 0.85; axis joins true; run/extension IoU drop 0.03/0.05. |
| Junction artifact | Maximum length 125 px; alignment 8 degrees; significant-family fraction 0.15; minimum covered/network covered 0.45/0.15; zone fraction 1.1; ribbon presence 0.5/free length 12 px; drop IoU 0.005; attachment 12 px; realign true/drop 0.05. |
| Stub trim | Maximum stub 60 px; keep overlap 2 px; minimum trim 6 px; continuing mask 0.75; minimum angle 25 degrees; third-wall tolerance 12 px; maximum short wall 120 px; attachment 12 px; axis joins true; trim IoU drop 0.005. |

OBB metadata defaults are confidence 1, local class 0, weight 1 and merged-count 1; these are defaults, not measurements.

Mask-IoU guards use the same cropped domain before/after, unchanged neighbors on both sides and neutral junction territory when applicable. Add original-point scores outside neutral territory. Dominant axes and positive mask scores do not authorize deleting independently supported geometry.

### CB-021: joint opening and preview rules [N/A]

E provides plan candidates; B provides section heights. Reference plan controls include minimum contour 10 px and long side 0.4 m, with wall intersection/axis projection. Punctora combines this with original jamb/head/sill, recessed filling, visible-gap and occlusion evidence.

Fit hosts and openings together. Reconcile the reported wall overlaps without losing opening support. Cross-host duplicate removal considers geometry, host and exact evidence, not only overlapping boxes. A closed filling is different from a certified void. Ambiguous provider scores/classes remain reviewable.

Clamp opening boundaries to finite accepted host profiles and vertical bounds. Suppress microscopic/zero-area subtraction fragments, remove numerical spikes and reject self-intersections before preview/export. Preserve real narrow supported features and meaningful holes. Preview, saved geometry and IFC must use the same validated profile/cut path. No cut is accepted merely because E/B/I or a projected void exists.

## 7. Floors, slabs, ceilings, corners and roofs

### CB-022: independent measured patches and local bands [P/A]

The package's global A overview can propose physical slab/floor pairs. Punctora must also start from independent connected horizontal/sloped patches, including partial/exterior scans. Manual level bounds pass through the desktop worker, constrain search and remain distinct from measured floors. Preserve detected-level diagnostics even when reconstruction fails.

Useful recovered/documented settings include:

| Method | Reference settings | Interpretation |
| --- | --- | --- |
| Semantic 2.5D bands | Cell 0.25 m; height gap 0.25 m/merge 0.15 m; minimum patch 2 m2/300 points/coverage 0.10; new full-level coverage 0.35. | Connected local evidence is distinct from a complete level. |
| Global/local sequence | Global surrounding bands at least 2 m; local range 1..6 m; reject mid-floor candidate above 0.5 coverage; section confirmation enabled. | The legacy +1.5 m plan slice explains the global-band restriction; local steps need not create global storeys. |
| Measured ceiling map | Cell 0.5 m; 98th height percentile; same-band +/-0.15 m stitching; local offset up to 1 m. | Recover connected corners/wings and separate local elevation changes. |
| Local two-face zones | Cell 0.25 m; floor/ceiling percentiles 2/98; discard thickness below 60 mm; deviation at least 30 mm over 3 m2; at most three zones. | Treat thresholds as candidate controls, then validate face/elevation evidence. |
| Local A confirmation | Strip 0.8 m; height window +/-1.8 m; exclude parent band +/-0.15 m; point-density snapping. | Avoid rediscovering the parent slab as a new local plate. |
| Tiled surface growth | 8 m tiles; up to 40 A tests/six regions; minimum region 12 m2; default thickness 0.2 m; candidate shifts 0.06..0.24 m. | Test X strips then Y where needed. Default thickness remains inferred. |

These are method references, not new Punctora thresholds accepted by this documentation change. Keep local footprints/elevations and diagnostic reasons, rather than force all surfaces into one global histogram or slab sequence.

### CB-023: measured faces, corner completion and boundaries [P/A]

Measure both faces where possible; the reference searches 0.05..0.55 m below a top face. A dense single face with returns below can indicate underside and require inferred upward thickness; returns only above can indicate top. Missing role/thickness stays explicit.

The boundary design combines measured surface continuity, neighboring surface edges and adjoining measured wall planes. Wall-envelope completion is a justified/inferred boundary operation; it does not make occluded area measured. Native envelope methods use wall rectangle unions and rounded gap closing, with containment-based adoption. Preserve concavities, all supported connected components and holes. Do not blindly use hole fill, largest contour, bounding box or convex hull fallback.

Snap a boundary to a wall face only when the boundary is compatible/parallel and on the appropriate interior side. Unwalled boundaries stay measured. Cantilever growth needs compact area/depth support. Ground-level trimming must distinguish terrain from overhead structure. Retain a structural parent slab when a local suspended ceiling lacks evidence for a structural replacement.

Coverage states remain measured, justified completion, inferred, unsupported and unknown. Persist actual class polygons, interior rings and evidence, not just percentages/bounds. A reported high coverage percentage cannot certify missing corners or unsupported area.

### CB-024: common-polygon partitions and thin regions [V/A]

Resolve local replacement regions into a final disjoint partition once. A replacement plate and its corresponding cut consume the **same validated polygon**. Require no positive-area overlap, no missing/added supported plan area and preserved holes. Validate elevation assignment as well as plan area.

Skip empty/degenerate fragments before overlay. Numerical cleanup cannot decide that a narrow measured strip is noise: the 1 m by 10 m fixture disappears under +/-0.75 m buffering despite 10 m2 of support. Use face/height/continuation evidence before absorbing a remainder into its neighbor. Keep real corners, shafts and strips, or explain their unresolved state.

Record per-stage before/after contours, elevation, source support and create/change/keep/reject reasons. Native slab decision logging is a useful reference, with stages for bands, hull, fitting, semantic augmentation, tiling and zones. Punctora should bind those decisions to the job and original IDs. This makes later screenshot/IFC differences traceable to a specific stage.

### CB-025: roof authoring resources and semantic output [P/A/Q]

The supplied authoring layer adds pyramid, shed, hipped, gable and flat/parapet roof helpers, including buffered footprints and oriented footprints, plus curved-wall representations. Their existence establishes authoring resources, not automatic detection of every form.

Fit original roof planes and supported eaves/ridges/valleys before assembly. A selected roof style or footprint cannot authorize hidden geometry. Distinguish roof from ceiling/floor using orientation, relationships, height/visibility and semantic proposals.

Run 5 introduces explicit Roof/Ceiling records and schema 3 with deterministic schema-2 migration. Use IfcRoof assemblies with supported parts; use appropriate ceiling covering/surface representations. Unknown solid thickness is not silently measured. Automatic use of all native roof helpers or a dedicated native ceiling-covering pipeline remains unestablished.

## 8. Stairs, ramps, columns, beams and descriptions

### CB-026: stair candidates and geometric completeness [P/N/A]

H proposes plan crops. The reference geometric chain uses 0.02 m voxelization/normals, horizontal filtering around 0.05, anisotropic Z-scaled DBSCAN, oriented patches, coplanar merging and a rise/run lattice.

Reference controls include riser 0.10..0.30 m, going 0.15..0.50 m, tolerances 0.03/0.05 m, area ratio 1.5 and at least three grouped treads. The recovered flight-center search default is 2.5 m. These create candidates; they do not prove connections.

Native positive-gap completion computes `int(gap/riser + 0.5)`, increases count/run extent, and proposes a landing from flight geometry and wall subtraction. A 0.11 m gap with 0.18 m rise adds one inferred step and extends 0.07 m beyond that target. Keep generated treads/landings explicitly inferred.

Accept flight connections only with endpoint, landing, elevation, direction, width and clearance evidence. Nearby independent flights stay separate. Revalidate associated slab voids after edits. Retain observed/inferred tread indices and endpoint states. Run 6 scope remains straight/L/U; curved/spiral/elliptic authoring helpers do not establish their recognition.

### CB-027: ramps, columns and beams [P/A/Q]

No dedicated ramp model/class or automated first-party ramp/IfcRamp branch was established. A ramp needs continuous sloped strip geometry, width, traversable endpoints and relationships; slope alone can be roof or terrain. This remains explicit Punctora geometry work in Run 6.

G proposes circular/rectangular column footprints; F/C propose beam plans/heights. Fit original points and observed faces, keeping unresolved extents and thickness. Native default column height 3 m and beam height 0.35 m are inferred fallbacks, never measured dimensions. A thin planar/line column proposal may retain no parametric geometry. Recognizing a beam class does not create Beam schema/editor/IFC support without explicit implementation.

### CB-028: grounded descriptions and status [A]

There is no language-captioning graph among A-J. Run 8 descriptions use accepted geometry, evidence states and ElementGraph relationships. Each claim retains source/evidence IDs, wording state and provider/version. Descriptions do not feed geometry or cuts. Do not infer material, load-bearing status, complete height, ramp/landing role or calibrated certainty from a model label.

The supplied IFC authoring constants also contain stock concrete/load-bearing wall names. Those are authoring defaults, not evidence that a model recognized a material or structural role. Do not inherit them as grounded descriptions.

Show experimental/fallback state, unknown coverage, weak classifier margins and inferred additions accurately. The planned top status/progress banner makes save/revert/failure and detection stages noticeable. Retain the user's palette: `#1C8DFF`, `#21E6E8`/`#18D7F1`, `#FF922E`, `#081327`/`#1A2436`, `#EDF2F7`; gentle change pulse with reduced-motion handling.

## 9. Memory, lifecycle and diagnostics

### CB-029: bounded model views and truthful fallback [P/N/A]

The native package documents three-decimal XYZ rounding, mandatory model-view dilution (default 20/minimum spacing 0.025 m), a 25-million-point cap and possible resource-driven thinning/subsampling. These are not Punctora's original import/evidence policy. Preserve f64 originals and exact scan/record IDs; every model-only subset retains a reverse mapping and declared population.

At 1.5 million voxels, stage-0 k5/k3 int64 maps alone occupy **1,824,000,000 bytes**, excluding later stages, features, votes and activations. A voxel cap is not RAM admission. Keep the 70%-of-available-at-job-start ceiling, stricter user cap, complete parent/child accounting, bounded allocations, cancellation and diagnostics.

The inspected native cap branch raises MemoryError before constructing indices and the engine returns `(None,None)`. It does not automatically coarsen that grid or publish earlier votes as a complete result. Punctora prefers deterministic subdivision at the pinned scale or an explicit unavailable branch. Deliberately retained partial output must have partial status/coverage and an atomic artifact identity.

The newer engine can use I if available, otherwise a torch subprocess, otherwise no semantic prior. Older out-of-process documentation is not a complete description of that newer route. The GUI's documented minimal-envelope IFC fallback can produce a successful output when main dependencies/models are unavailable. Always report actual path and reason; success is not proof that the requested learned branches ran.

### CB-030: live sessions, slab state and atomic generations [N/A]

Native session caching compares the model path with `_SESSION_PATH`. Punctora's selectable assets require task/content/runtime/preprocessing/decoder identity. Replacing a file at the same path invalidates the live session and artifact cache. Store hashes actually loaded, so later filesystem changes do not rewrite an old session's reported identity.

The inspected slab augmentation resets `LAST_SLAB_ANALYSIS` at entry. Use job-local state and clear it on failure/cancellation. Keep stage decision logs diagnostic rather than a second geometry authority.

Bad hashes, wrong frames, broken source inverses and malformed outputs are visible internal failures. Missing assets or unavailable devices may select declared classical/CPU fallback. Publish only validated complete generations; cancel and discard staging data. Preserve recovery, worker heartbeat and saved-work consistency.

Quality is the priority. Counter correctness and reduced repeated visits remain useful, but no speed benchmark is a current quality gate.

## 10. Controlled probe register

All results here use generated tensors/geometry and CPU ONNX Runtime, unless stated otherwise. They are not independent real-building annotations or a run of the Windows application. Exact numerical records are in [cloud2bim-evidence-v1.json](cloud2bim-evidence-v1.json).

| Probe | Result | Contract supported |
| --- | --- | --- |
| Ten graph smoke checks | All passed ONNX checker, CPU loading, finite outputs and bit-identical repeated calls. I initially used one voxel. | Asset execution feasibility and tensor signature. |
| Multi-voxel I | 1,31,127,128,129,255,256,257,513,2048 voxels; all five stages, finite/repeat-equal, row-aligned permutation equality and integer-origin-shift index equality. | Independent builder's stage/window/pool/row consistency. |
| Hilbert math | Scalar oracle, unique codes and adjacent traversal passed full cubes at depths 1/2/3. | Serialization math, not complete compiled-helper equivalence. |
| 513-voxel tail change | Agreement 99.22%; max logit delta 1.842. | Tail convention matters even when agreement appears high. |
| 513-voxel normal sign flip | Agreement 58.87%; max delta 16.302. | Sign recipe must be explicit. |
| 513-voxel kernel-axis reversal | Agreement 68.42%; max delta 8.418. | Kernel offset order is part of the model interface. |
| D normalization ablation | Configured generated room produced 6,000 nonzero pixels; omitted normalization produced zero, despite 97.71% global agreement. | Foreground/component measurements are needed. |
| D polarity reversal | 19,519 nonzero pixels; 92.26% global agreement. | Polarity is part of the renderer contract. |
| J channel ablation | Generated overlay: two decoded candidates under documented BGR recipe, eleven after swapping channels. | Channel/interpolation fidelity; neither fixture result proves accuracy. |
| B white/gap sections | Each retained 300 softmax queries >=0.4 versus one query under independent sigmoid. | Reproduce native decode, validate geometry separately. |
| Low B logits `[-8,-7]` | Winning softmax 0.731059 versus sigmoid 0.000911. | Score kinds cannot be conflated. |
| Box/section transforms | Independent W/H clipping; local `[0,2.1]` m restored to world `[123.4,125.5]` m; centre error 0.001 m; native inverse offset 0.01 m. | Declared pixel/base transforms. |
| Surface partition | Retained 4 m2 hole; zero overlap and zero missing/added plan area. | Common-polygon partition validity. |
| Survey coordinates | Direct float32 error up to 0.07 m; local-origin restoration zero in the fixture. | Origin-free float32 computation with f64 geometry. |
| Mask dynamic shape | 30 finite exact-size cases across five models; five batch-two comparisons max delta zero. | Tested odd/rectangular and batch behavior. |
| F graph with G companion | Checker passed/finite; max delta from F 19.9547; 54/6144 pixels changed to class 1; global agreement 99.12%, nonzero IoU zero. | Hash/layout/task binding before inference. |
| I negative kernel centre (-2) | Runtime accepted/finite; class agreement 3.10%, max delta 12.6578. | Reject semantically invalid negative indices. |
| I rolled in-range inverse | Runtime accepted/finite; agreement 48.06%, max delta 12.9458. | Validate exact restoration, not range alone. |
| I out-of-range index/feature width | Runtime rejected index beyond sentinel and four-channel features. | Runtime catches some defects, not all. |
| Rectangular OBB inverse | 35-degree fixture restored to 23.64 degrees; adjacent edge cosine -0.4165; naive corner error 38.67 px. | Transform corners or preserve square tiles. |
| Representative pair swap | 258 samples/129 voxels; all coordinates/indices unchanged, all feature rows changed; label agreement 41.86%, max delta 8.1470. | Stable representative rule before inference. |
| Stable source-key representative | Same features/indices after reordered rows; uint64 records above 2^53 preserved. | Punctora-owned repeatability adaptation. |
| Vote arithmetic/counter | Agreements 255/127/170/153; no votes -> -1/0; uint8 count wraps at 256, uint32 retains 256. | Separate agreement/coverage and wide counters. |
| Thin surface buffer | 1x10 m strip lost all 10 m2 under +/-0.75 m buffering. | Elevation/evidence-aware cleanup. |
| Stair completion arithmetic | 0.11 m gap/0.18 m rise adds one step and 0.07 m overshoot. | Completion is inferred and endpoint-gated. |

The generated voxel layouts came from a 16x16x8 lattice, seed 7055, positions multiplied by three and unit feature selection by coordinate-sum modulo three. Permutation seed was the population. The D fixture was a white 512x512 room outline with eight-pixel walls and partitions. These test interfaces, not class correctness. The 2048-voxel stage populations were `[2048,2048,864,108,18]`.

Analysis runtime: Python 3.12.14, NumPy 2.5.4, ONNX 1.20.1, ORT 1.23.2, CPUExecutionProvider, sequential execution, two intra-op threads; Pillow 12.0.0 for image probes. This is not a qualification of the shipped Windows/AMD runtime. Open3D/native full-scan preprocessing parity was not executed here.

## 11. Implementation handoff and decision gates

### CB-031: remaining run design

| Run | Apply these findings | Required internal checks |
| --- | --- | --- |
| 4: walls/openings and desktop integration | Distinct optional ONNX provider; task manifests; D/J and E/B priority; optional I; plan/section renderers; original-point joint fit; zero-growth, junction, width-only and guarded trim sequence. | Desktop selected/actual mode; wrong companion and semantic-index rejection; negative no-cut sections; low windows/uneven floors; terminal support; short/diagonal walls; corridor/twin distinction; opening preservation; square/full-corner transforms; f64/IDs/cancel/cache. |
| 5: surfaces and roofs | A/optional I; local connected bands/corners; measured/justified/inferred states; common-polygon partitions; elevation-aware thin regions; job-local state; schema 3 roof/ceiling support. | L-corners, disconnected wings, holes/atria/shafts, one-sided faces, suspended ceiling/structural parent, split levels, unwalled surfaces, survey coordinates, valid profiles, zero unsafe cuts, save/reopen/IFC. |
| 6: stairs and ramps | H/optional I candidates; original treads/landings/endpoints; explicit inferred completion; continuous-slope ramp method. | No-stair/nearby independent flights; partial treads; rise/run and endpoint residual; observed/inferred labels; landing associations, clearance and cut revalidation; straight/L/U and ramp distinction. |
| 7: add to existing model | Align independently reconstructed interior/exterior generations; preserve every source/frame/provider/model namespace; union corroborating evidence and remove true duplicates. | Known transform round trips, invalid alignment, stable existing IDs, conflicting hosts, partial-overlap fitting, no proposal promotion, atomic save/reopen/cancel and schema handling. |
| 8: grounded descriptions and top status | DescriptorSet from accepted facts/relations/states; truthful score/agreement/coverage; experimental/fallback diagnostics and visible progress/status palette. | Unsupported-claim rejection, missing role/material/height, weak margins/uncovered points, inferred steps/thickness, status transitions and reduced motion. |
| 9: selective Rust and final qualification | Profile verified Python path; one measured kernel at a time; optional ort deployment after CPU parity; complete recursive operator/index/session/source contracts. | Typed f64/int64/uint64 boundary; memory/cancel/determinism; exact source restoration; Python/native labels/scores/geometry/evidence parity; final complete matrix and deferred external quality checks. |

**Version 1.1 handoff:** Run 4 additionally requires native-ordered kernel maps, source-key ordering before centring, foreground/subclass TTA separation, attached semantic-rescue candidates, point-gated restored tails, exact overlay/storage recipes and query-aware deduplication. Runs 4/5/6 must tile before model-scale coarsening and keep inference buffers independent of debug JPEG output. Runs 5/6 must revalidate stairs/opening associations after late surface changes. Run 8 inherits the corresponding uncertainty and stock-name restrictions; Run 9 uses tolerance-based CPU/backend parity with the corrected inputs.

**Version 1.2 viewer handoff:** [CB-044 through CB-058](CLOUD2BIM_VIEWER_AUDIT.md) expand Run 8 to include pleasant cloud/IFC presentation, actual IFC meshing, camera/depth repairs, local cloud detail, architectural shading/outlines, linked comparison and the prior top status/progress requirement. Runs 4-7 expose geometry/evidence identities and shared alignment frames; Run 9 retains selective Rust acceleration and subsequent external qualification. Version 1.3 revises backend order: evaluate the documented ActiViz VTK control for Avalonia 12 first, retaining the existing renderer as fallback. Rendering remains a replaceable Avalonia component. This audit does not implement those changes.

Runs 1-3 remain implemented with revised future scope. The supplied graphs resolve earlier missing-asset assumptions without replacing those completed contracts. Preserve ProposalSet v1, review-only ElementGraph and later DescriptorSet separately from accepted geometry.

### CB-032: Rust scope

Rust can improve bounded spatial queries, normals, occupancy/voxel construction, stable Morton/Hilbert serialization, exact kernel/window/pool indices, clustering/RANSAC or polygon/collision checks. Selection comes from Punctora measurements and parity, not upstream benchmark reputation.

Use a versioned PyO3/maturin array boundary with explicit transforms/IDs and cancellation. Compare SpatialRust/ThreeCrate/focused crates such as Kiddo/Parry where applicable. The supplied ONNX graphs already exist; re-export is not a prerequisite. Rust `ort` is an optional runtime boundary after direct Python ORT parity. A Candle/Burn model rewrite is not part of this plan.

Keep the working original-record E57 importer unless a separate parity suite verifies scan grouping, metadata, pose, records and coordinates. Derived caches require reverse source identity. Independent IFC tools can check exported geometry/relationships; they do not recognize building elements. Consult [dependency inventory](../DEPENDENCIES.md) for the broader resource register.

### CB-033: disposition for each run

1. **Proceed:** internal acceptance criteria passed; continue. External qualification remains after Run 9.
2. **Proceed with revised future scope:** internal criteria passed, but evidence changes later design; record the affected runs and apply the revision before them.
3. **Repeat current run:** repairable internal defect remains, such as failing source mapping, malformed artifacts, unsafe cuts or broken cancellation/cache/worker behavior. Never choose this for missing external annotations, reviews, reference assets or hardware checks.
4. **Redesign current run:** internal evidence disproves an underlying assumption; replace that design and verify it internally.
5. **Redesign/update future run:** additional action whenever findings affect later work; record evidence, dependency effects, revised internal tests and final qualification targets.

Items 1-4 are mutually exclusive dispositions; item 5 is an additional action. Reports separate implemented/tested capability, unresolved internal defects and deferred qualification. Final qualification compares classical, selected learned/hybrid, native-kernel and qualified ONNX modes for element quality, source retention, repeatability, evidence, cuts/duplicates, project composition, UI, reopened IFC and memory.

## 12. Open questions and update procedure

### CB-034: focused questions

| Question | Answer from the additional audit | Remaining scope |
| --- | --- | --- |
| Exact native helper/renderer equivalence beyond recovered branches | **Partly resolved.** Kernel offset order is now recovered; explicit mask palette/alpha, per-class TTA, rescue/restoration gates, memory/JPEG raster choices and native centring are clarified in CB-035 through CB-040. | Complete helper/renderer execution parity still requires a matching native reference execution or supplied tensors. Independently declared implementation can proceed. |
| Specialist native class-column meanings not established by graph metadata | **Operational use resolved for the inspected paths.** D's native wall gate accepts configured foreground classes, including 1/2; E's 1/2 are both opening candidates; J preserves local IDs but accepted OBBs enter wall construction. B's sill rule remains downstream. | Exact training names for D/E subtypes and J columns are still absent. Do not invent door/window/background mappings or use local IDs as IFC class authority. |
| Export/checkpoint lineage and full patched-reference parity | **Available lineage rechecked.** Both public repository and user's fork still resolve to the pinned commit. The run_20260803_0021 LFS pointer and embedded I lineage agree with the recorded provenance claim. No export/helper harness or reference arrays appeared in the refreshed listings. | The 554659890-byte checkpoint was not downloaded/loaded; no tensor-by-tensor checkpoint-to-I chain or native-reference parity is claimed. |
| Model-view sampling/normal recipe on real sparse/occluded scans | **Input recipe clarified; real-scan question remains open.** Native float32 centring precedes voxelization and can depend on input order. Normals remain tile-local Open3D radius 0.30 m/max 30 without orientation. Generated radius-count fixtures expose unsupported sparse neighborhoods. | Open3D/native real-scan normal equivalence and actual class errors are not established by generated unit features or neighbor counts. Qualify after Run 9. |
| Automatic native roof/ceiling/curved helper use | **Inspected main route resolved.** The recovered entry pipeline authors slabs/local slabs, walls, beams, columns and detected stair assemblies. It does not directly invoke the roof/curved-wall authoring helpers. Curved/spiral/elliptic stair builders consume explicit configuration in a separate manager helper. | This bounded route inspection is not an assertion that no other dynamic/manual path exists. Automatic sloped roof and ceiling-role reconstruction remains Punctora work. |
| Full building outcomes and target backend/hardware parity | **CPU settings partially checked.** Corrected generated I inputs retain identical labels across the tested ORT optimization/thread settings, with small logit differences. | Complete building outcomes, Windows/AMD providers, real-scan geometry, Open3D preprocessing and hardware qualification remain after the nine implementations. No external-check Repeat gate. |

The public README's referenced `DL_module/segmentation_report.tex` was unavailable at the pinned commit. The original checkpoint/export harness/reference tensors were not supplied as an editable complete reference during these audits. Missing external material does not negate the executable ONNX assets or stop implementation.

Version 1.1 incorporates the user's additional open-ended audit request. Its new findings change concrete implementation contracts. Further source work should answer a named mismatch, geometry rule or changed asset; unresolved external qualification does not hold implementation in a research loop.

### CB-035: native kernel column order, correction to the exploratory template [N/V]

The compiled `_offsets` constructs `meshgrid(..., indexing='ij')`, flattens its first/second/third arrays in that order, and the compiled kernel mapper adds the same ordered triplet to the grid row. **Grid column 0 varies slowest, column 2 fastest.** For side k and half-width h, the column number is `(d0+h)*k*k + (d1+h)*k + (d2+h)`.

Examples: k3 column 1 is `[-1,-1,0]`; k5 column 1 is `[-2,-2,-1]`. Centre/self remains column 13/62. This describes actual grid-column order, avoiding ambiguous x/z naming.

The old independent builder varied grid column 0 fastest. Its generated CPU execution and permutation checks were valid for its own inputs, but did not establish native input equivalence. Preserve those records and correct the template before integration. A new dense 125-voxel oracle matches the corrected builder exactly; the old maps differ in 1,846 k3 and 7,600 k5 entries. The 513-voxel inference comparison changes 31.58% of labels, max logit delta 8.4182. This is a contract correction, not real-scan accuracy or a Run 1-3 reset.

Native anchors: `_offsets` `0x14acb7320`, ordered flatten/stack `0x14acb7b16` through `0x14acb7c70`, kernel offset array construction `0x14acb9330` through `0x14acb93af`. The native helper itself was not executed.

### CB-036: stable ordering must precede centring [N/V/A]

The inspected I engine casts its model view to contiguous float32 before tile extraction, subtracts separate X/Y float32 means and Z minimum, then floors by the 0.06 m grid. Stable representatives alone do not stabilize an earlier order-dependent reduction.

A generated 128-sample permutation changes eight voxel-coordinate rows through tiny mean differences. Original-row label agreement is 87.5%, max logit delta 0.9711. Sorting exact source keys **before centring** makes all inputs identical in the two orders. Retain both the reduction/order recipe and representative rule in the provider fingerprint. Deterministic f64 local-frame/reduction choices are explicit Punctora adaptations.

Input must already be an appropriate local frame before float32 conversion. Passing the generated survey-coordinate fixture directly to float32 loses up to 0.24 m; subtracting the f64 origin first avoids that loss in the fixture. This does not prove that the native importer supplies unsafe global coordinates; it establishes the adapter's precondition.

Native anchors: float32 model-view cast `0x14acb01b8`; X/Y means `0x14acb1852`/`0x14acb1950`; quantization `0x14acb1bc9`.

### CB-037: class consensus can lose unanimous foreground [N/V/A]

The native D wall gate accepts `wall_classes`, default `[1,2,3,4,5,6]`; with D's three channels, 1/2 are both foreground. E similarly combines nonzero classes for opening-plan contours. Their training subtype names remain unresolved, but this downstream consumption is concrete.

The native six-view TTA requires four votes for the **same class**, then initializes failures to zero. On a 100-pixel fixture with three class-1 and three class-2 votes everywhere, it outputs zero foreground pixels despite six foreground votes at every pixel. Keep class/subclass disagreement separate from background evidence.

Run 4 can test an explicitly versioned foreground-consensus proposal alongside the faithful native decode. Preserve subtype uncertainty, original view votes and the J renderer's class colors; do not silently replace the native rule or promote the alternative into measured geometry. Add both a 3/3 foreground fixture and genuine background-disagreement negatives.

Anchors: class gate `0x14adf4422` through `0x14adf4476`; TTA four-vote comparison `0x14ac3ea70`; E foreground conversion near `0x14ab3aedf`.

### CB-038: attached semantic rescue can be rejected as one component [N/V/A]

The native rescue gate retains whole connected components only when their area is at least 0.15 m2 and at most 30% lies within 0.30 m of existing U-Net walls. This deliberately limits semantic thickening, but component connectedness can couple a new branch to a known wall.

In the generated fixture, a 9,000-pixel connected component has 62.22% near existing walls and is rejected. Its uncovered residual is 3,400 pixels, **0.34 m2**, large enough for a separate candidate. This is a rule probe, not an observed failure in the user's building.

Test residual/branch candidate decomposition after measuring proximity, then fit the candidate and junction against original points. Protect openings and separate corridor walls. Do not simply disable the overlap guard or extend existing walls from semantics alone. Anchor: `_rescue_only_new_segments` `0x14adf2720`, overlap decision around `0x14adf3a23` through `0x14adf3aec`.

### CB-039: component restoration is not terminal support [N/V/A]

The verticality filter restores a whole component when its supported fraction reaches 0.85. A generated component with 90% support restores an unsupported 20-pixel tail (0.20 m at the tested scale), totaling 400 pixels. Later mask-only refitting can inherit this restored extent; the final native outcome was not executed here.

Record which pixels were original support, dilated support, semantic protection or component restoration. Run 4's final endpoint fit must use original terminal/continuation evidence independently of the restored mask. Add a well-supported long wall with an unsupported tail and a separate truly supported short continuation. Anchor: component restoration `0x14ade80c5` through `0x14ade8121`.

### CB-040: model scale, overlay and debug storage are detection inputs [N/V/A]

The native horizontal raster cap is 64 million pixels/16,000 per side and can increase pixel size. A 200x200 m footprint requested at 0.01 m/pixel becomes 0.025 m/pixel under that area cap. A 1024-pixel plan window then covers 25.6 m instead of 10.24 m; H's 2048 window covers 51.2 m instead of 20.48 m. Correct metric conversion does not restore the model's original physical field of view. Tile original points before rasterizing, at a declared fixed model scale.

Native raster dot radius is two pixels. A generated 0.03 m gap becomes connected after that dilation at 0.01 m/pixel. Preserve raw occupancy/visibility separately from dilated model images; never certify openings or thickness from the dilation alone.

The J overlay uses alpha 0.5 and BGR palette class 1 `[0,0,255]`, class 2 `[0,255,0]`. Keep these colors rather than repaint every accepted foreground class red. On white background the illustrated blended values are `[127,127,255]` and `[127,255,127]`. The training subtype names remain unknown.

The optional native disk raster is JPEG quality 95, whereas the memory path uses the original image buffer. In the generated 512x512 room fixture, JPEG changes 2,828 input pixels and 74 D class pixels, max logit delta 0.9212. This is storage sensitivity, not class accuracy. Debug export must not change inference buffers. Persist lossless model inputs or fingerprint an explicit compression recipe.

Anchors: horizontal raster/module defaults `0x14ac2fd10`/`0x14ac30920`; overlay alpha assignment `0x14adffc75` through `0x14adffc8a`; blending `0x14adfbb36`; JPEG settings in the pinned horizontal-section constants.

### CB-041: preserve detector query identity [V/A]

J's flat query/class top selection can retain several class hypotheses from one query's box. A constructed one-query `[3,2,1]` logit fixture retains three local class hypotheses above 0.25. They are not three independent wall observations.

Keep query ID, tile ID and raw class-score vector. Fuse duplicate geometry with explicit competing class hypotheses and source evidence; do not increase support counts or confidence by treating those hypotheses as independent detections. Native class names remain unresolved; do not drop a column as background without evidence.

### CB-042: inspected native orchestration and late geometry dependencies [N/A]

Bounded inspection of `Cloud2BIMApp._run_bim_pipeline` confirms the following late sequence: wall/beam/column extraction, wall-based slab fitting, stair extraction, openings, semantic local slabs, tiled slab refinement, local thickness reconstruction, ground-slab trim, then IFC local slabs/walls/beams/columns/stairs.

The inspected route does not directly call roof or curved-wall authoring helpers. Its semantic roof handling helps slab/surface levels; it does not establish automatic sloped IfcRoof generation. Separate curved/spiral/elliptic stair builders consume explicit configuration in `ifc_manager.create_ifc_stair`. This is bounded route evidence, not a complete assertion about every possible manual/dynamic application path.

Stairs/openings are detected before some later surface operations. Punctora must invalidate and revalidate associations, endpoints, clearance and cuts whenever those final surface operations change relevant geometry. Checking only after user edits is insufficient. Add a late raised/lowered slab patch affecting an already-proposed stair endpoint and headroom region.

Anchors: entry method `0x140559720`; stair extraction `0x14055ef6b`; openings `0x14055f8a6`; local patches `0x14055fbeb`; tiled refinement `0x14055ff52`; thickness `0x140560343`; ground trim `0x1405606a5`; IFC authoring `0x140561207` through `0x1405615fe`.

### CB-043: expanded CPU check and remaining qualification [V/Q]

Corrected generated I inputs were tested with one thread/optimizations disabled and four threads/optimizations enabled against two-thread CPU inference. All labels matched; maximum logit differences were about 9.54e-6 and 5.72e-6. Backend parity should therefore declare score tolerances rather than demand cross-setting bit equality everywhere.

The generated 81-point plane at 0.06 m spacing had 26..77 neighbors within 0.30 m (before a maximum-30 estimator cap). At 0.5 m spacing, every point had only itself. Normal validity requires neighborhood count and geometric conditioning, not only a finite/unit output vector. Those counts do not execute Open3D or establish real-scan normal parity.

CPUExecutionProvider was the only provider used. No Windows/AMD inference, complete Windows application run or independent real-building accuracy was established. Those questions remain explicitly deferred; they do not require repeating completed implementation runs.

The eleven probe groups and source/native anchors are preserved in [cloud2bim-open-ended-audit-v1.json](cloud2bim-open-ended-audit-v1.json). Original probe-summary SHA-256: `6033300935c599be118312acd42f4a06511cd29e4f29b3569d3c41375a7c2518`.

### Updating this reference

Stable finding IDs `CB-001` through `CB-060` identify current conclusions. CB-044 through CB-060 are maintained in the linked [viewer audit](CLOUD2BIM_VIEWER_AUDIT.md). Keep IDs stable when revising; add new IDs for new findings. For each update:

1. Record date, source URL/path, exact revision/asset hashes, evidence label and test scope.
2. Update the affected finding's current conclusion; mark any superseded interpretation explicitly and retain its historical source.
3. State the resulting implementation change, affected runs, internal fixtures and remaining qualification.
4. Update model manifests/provider/render/decoder/taxonomy versions when contracts change. Invalidate both artifacts and live sessions where required.
5. Add derived probe results to the evidence register with original summary hashes; preserve old results with their identities rather than overwrite them as if equivalent.
6. Add a revision-log row and link the documentation commit/PR from issue #1. The nine-run plan remains the implementation authority.

Keep supplied executable/model assets, customer scans and complete recovered third-party source outside the repository. New entries describe observations, contracts and Punctora decisions.

### Revision log

| Version | Date | Change |
| --- | --- | --- |
| 1.3 | 2026-10-13 | Added CB-059/060: direct ActiViz/Avalonia 12 integration revises Run 8 backend ordering; traced E57-to-XYZ through reconstruction, its rounding/channels and evidence limits. Retained f64 source cache, optional interchange and internal parity requirements. Documentation/evidence only. |
| 1.2 | 2026-10-13 | Added CB-044 through CB-058, a focused viewer/visual audit and six generated probes. Recovered the omitted CAD camera module, exact IFC/cloud display recipes, current projection/depth and global-preview limits, and an expanded Run 8 visual-quality handoff. Documentation/evidence only. |
| 1.1 | 2026-10-13 | Added the requested open-ended audit, CB-035 through CB-043, eleven probe groups and explicit answers to all six open questions. Corrected the exploratory kernel-order template and added centring, foreground/connectedness, storage/scale, query-identity and late-dependency handoffs. Preserved historical results and deferred qualification. Documentation/evidence only. |
| 1.0 | 2026-10-13 | Consolidated the five supplied-copy reports, earlier research lessons, verified contracts/probes, current Run 1-3 state and Run 4-9 handoff. Established stable finding IDs and a machine-readable evidence register. Corrected the earlier aggregate model-byte total from independently rehashed files. Documentation only. |

## 13. Fingerprint and inspection appendices

### Exact supplied asset identities

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| model_A.onnx | 107758217 | `6de5aadeee16c9967649296992742da2e34e667fb09bc5a1edac06501d7d440d` |
| model_B.onnx | 107760273 | `b1672b3665374fa57be2d328806d08bf4404e554c8e46939d4880fda68aaf375` |
| model_C.onnx | 107758217 | `deb2d2cec23de1a1ce3c365912c0d1970315302a56c70a39e4e3a6666b7e717d` |
| model_D.onnx | 49604 | `c8fb784866896b91bf22d9ca7cb440651bb32add4f7ae254cd7d250ff67fad14` |
| model_D.onnx.data | 97675200 | `4758d242e870f7f6196094a5d4bc2df4ed1a533da8d5a83988dc15d61f3a5746` |
| model_E.onnx | 97720380 | `5e24a06ba2450a2548561465585d99916e1225fd33d0f8c81c735bb862719fc5` |
| model_F.onnx | 343093 | `9cfb5da2185c118dc247f88a3b3492d94be50e1c0267ed23384a497297d86dcb` |
| model_F.onnx.data | 97714176 | `66b3be136f23da2b1625f2d1885865bc7218a987a24c560c8c8c73582f792399` |
| model_G.onnx | 343093 | `4f4a7c2fee3b2b5d8b32fb72644f27c4dfe8f9a7c8e65b2289081596e31e158c` |
| model_G.onnx.data | 97714176 | `a813fa61316d56ef17f6867853c4e3cc2aff03d6ea5538fdc37371627af0bb25` |
| model_H.onnx | 343093 | `780623abd4b788e6fd141ed149f7670b35273ed3474d05b0ec782f54551d2a1f` |
| model_H.onnx.data | 97714176 | `5bdd8e9cd6ce885a4540670a727b509b2ff63e8f8402150c0ada7651acff91ed` |
| model_I.onnx | 185122504 | `775ca536bfd691979c6a45fae388f161b3f80ba332c6bb308257b937fd08f680` |
| model_J.onnx | 121154252 | `0bea57f4ecb412fbc46e96ca6fb57c4241bcfee5797ddf12897327cf081f5f1d` |

The original public `best.pth` was identified as a Git LFS object, size 554659890, SHA-256 `de85b9c5dec3d2a14e175493acc177aff72417379c623e7aa2a6673225cceff8`; it was not downloaded. This identity is not a claim that it is interchangeable with I.

### Original derived-summary fingerprints

These hashes identify the audit's original JSON summaries. Selected/full derived results are incorporated in the companion evidence register; the register has its own file identity.

| Original summary | SHA-256 |
| --- | --- |
| deep_index_results.json | `7d38fd1519b75e1f3fbf84241ec3c847a8d5b3f9e28533f6539b4c0d21af16fe` |
| deep_2d_results.json | `ac87150e2cbe7864c8c4c701569050a3b69f99d33a069a6c503c95001dfc0623` |
| contract_probe_results.json | `9ac0e572d8ff628a6fae805307701e963d61a6a7560d775daaf12ee1cc9f407e` |
| native_defaults.json | `74768f897ef9456069d0feb83adf2e56a8a570f58862b272f7786eeea9539780` |
| onnx_deep_structure_results.json | `de6f05aabe8efb683ea92acf2be5f7a9c1b1ff34a9728c20b173d14194f3b7d2` |
| onnx_spatial_probe_results.json | `05978d229dbd62deca214df07b78a01a939cf450e030825ce5da821e9514fafd` |
| onnx_binding_index_results.json | `de7c4ebb207717e89554ebf226086f9785cfe0b28239855bc5eb32aac357e738` |
| handoff_probe_results.json | `218be577673a2e7cb4249402f0f536d3def2ce57d079143af619e2c4844228a7` |

### Native inspection anchors

Addresses apply only to the pinned executable/image base. They are evidence anchors, not portable interfaces or complete recovered functions.

| Finding | Native virtual address |
| --- | --- |
| Generic detector predict | `0x14ac97240` |
| B multi-channel decoder | `0x14ac9c9d5` |
| Local-sill door/window assignment | `0x14ab3f900` |
| Horizontal point raster | `0x14ac30920` |
| Opening inverse transform | `0x14ab39010` |
| I engine | `0x14acaf670` |
| First representative selection | `0x14acb1d22` through `0x14acb2093` |
| Oversized tile MemoryError | `0x14acb31a9` |
| Path-based session reuse | `0x14acade50` |
| Slab-analysis reset | `0x14acd9209` |
| Flight adjustment | `0x14ab4db60` |

Nuitka's public [constant helpers](https://github.com/Nuitka/Nuitka/blob/develop/nuitka/build/static_src/HelpersConstantsBlob.c) and [constant specification](https://github.com/Nuitka/Nuitka/blob/develop/nuitka/build/include/nuitka/constants_blob_spec.h) informed primitive decoding. Those moving links are explanatory references; the executable hash and original audit summary identities pin the actual investigated evidence.
