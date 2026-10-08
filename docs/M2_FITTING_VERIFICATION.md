# M2 fitting verification and M3 handoff

Status: M2 development and generated verification implemented in 0.2.0a2 on 2026-10-08. M3 desktop development can begin. Real survey acceptance remains outstanding; this is not a claim that all scanner files or building shapes are supported.

## Implemented

- Selectable `contour` baseline and CPU `region_growing` provider, with fixed or bounded adaptive normal-angle settings. No GPU, model weights, cloud service or colour channel is required.
- Chunked voxel sampling for horizontal-level detection and each storey/section. Detection is capped at 50,000 representative points by default, and original-record processing uses 100,000-record chunks. If the budget is exceeded, voxel size is enlarged and reported instead of silently truncating the scene.
- Batched nearest-neighbour normal estimation, local plane hypotheses for sparse/mixed neighbourhoods, spatial growth with a fitted-plane distance gate, surface patches and vertical-face proposals. A separate smaller normal radius prevents thin opposite faces being blended indiscriminately.
- Finite wall-face refitting against original records using bounded residual histograms, median/MAD trimming and covariance accumulation. Floor/ceiling strips and junction outliers do not establish the fitted wall plane. Both observed partition faces can supply thickness; a single face still needs an explicit assumption.
- Element JSON schema 2: observed wall faces, detection method, review state, recomputable evidence selectors, per-scan counts, bounded record examples, and full working-row/scan/original-record reference arrays in immutable NPY generations. Region-patch membership is also stored outside JSON in CLI output.
- IFC observed-face RMSE, evidence count and detection method, with an explicit evidence scope. Heights extrapolated from detected storey bounds are inferred. Materials and structural status remain unknown.
- An isolated-process benchmark runner for generated fixtures, repeated-record size experiments and an actual E57 when one is available. Real E57 mode records import/reconstruction runtime and source fingerprint, but has no reference accuracy claim.

## Verification

74 regression tests pass locally on Python 3.12.14. Checks include rotated/two-storey/noisy/sparse/thin-partition reference geometry, close parallel and disconnected patches, chunk-independent sampling, original-row retention, complete source evidence after E57 poses and invalid-record filtering, IFC validation, and unchanged source bytes. The perfect generated 120 mm partition is recovered within 0.001 mm by both providers after robust original-record refitting. This verifies a numerical implementation case, not achievable survey accuracy.

The package builds successfully and all retained licence texts are byte-identical in its wheel. SciPy 1.17.0 is pinned, with its installed Linux distribution and bundled component notices retained. The installed wheel is smoke-tested separately from the source checkout. GitHub Actions checks Windows/Linux on Python 3.11/3.12 and uploads generated benchmark reports.

## Reproducible benchmark

```sh
python -m punctora_core.benchmark --output-dir outputs/benchmark
python -m punctora_core.benchmark --cases clean rotated thin_partition --check --output-dir outputs/benchmark-core
python -m punctora_core.benchmark --cases clean --check --repeated-points 1000000 --output-dir outputs/benchmark-size
python -m punctora_core.benchmark --e57 building.e57 --output-dir outputs/benchmark-real
```

Generated cases share unchanged inputs and independently authored reference faces across providers. Random seed: 20261008. Reference matching uses 30 mm plane distance, 3 degrees of direction and at least 95% finite reference-length coverage. These are benchmark matching settings, not the supplied point-cloud guidelines' survey tolerance or a model acceptance contract. Reports include unmatched faces, duplicate overlap, footprint area error, storey count and measured partition thickness.

Each provider runs in a fresh subprocess, with numerical-library threads limited to one. Peak memory covers the whole worker, including libraries, input construction/import and mapped pages, rather than only the reconstruction function. Elapsed reconstruction time excludes import/input generation. Results are measurements on the development container, not predictions for the owner's PC. Repeated generated records exercise processing size without adding scanner or building diversity.

Measured on Linux x86_64, Python 3.12.14, one numerical-library thread per worker. Machine-readable results: [generated cases](benchmarks/m2-generated.json) and [one-million-record experiment](benchmarks/m2-million.json).

| Case | Contour time / MiB | Fixed-region time / MiB | Adaptive-region time / MiB | Reference faces detected (contour; fixed; adaptive) |
| --- | --- | --- | --- | --- |
| clean | 0.115 s / 92.6 | 0.726 s / 95.2 | 0.835 s / 94.9 | 6/6; 6/6; 6/6 |
| rotated | 0.164 s / 91.2 | 0.994 s / 95.2 | 1.036 s / 94.6 | 6/6; 6/6; 6/6 |
| noisy | 0.133 s / 92.7 | 1.445 s / 99.5 | 1.658 s / 98.9 | 6/6; 6/6; 6/6 |
| sparse | 0.068 s / 91.0 | 0.744 s / 95.7 | 0.737 s / 96.6 | 6/6; 6/6; 6/6 |
| low_clutter | 0.122 s / 95.4 | 0.713 s / 95.4 | 0.664 s / 94.2 | 6/6; 6/6; 6/6 |
| thin_partition | 0.108 s / 90.4 | 0.760 s / 95.1 | 0.769 s / 95.7 | 6/6; 6/6; 6/6 |
| two_storeys | 0.247 s / 96.5 | 1.549 s / 99.8 | 1.471 s / 99.7 | 10/10; 10/10; 10/10 |
| concave | 0.081 s / 93.3 | 1.234 s / 99.2 | 1.279 s / 99.0 | 6/6; 6/6; 6/6 |
| void | 0.112 s / 94.6 | 1.688 s / 101.9 | 1.780 s / 102.9 | 8/8; 8/8; 8/8 |
| wall_gap | 0.120 s / 92.7 | 0.723 s / 94.6 | 0.737 s / 95.6 | 5/6; 5/6; 5/6 |

All 30 geometry runs completed; no unmatched proposed faces or duplicate overlap were recorded under the documented matching rules. Concave/void footprint errors and incomplete wall coverage remain diagnostic failures, not accepted output.

| One-million repeated generated records | Reconstruction time | Worker peak MiB | Detection points |
| --- | --- | --- | --- |
| contour | 1.478 s | 125.9 | 7254 |
| region_fixed | 2.597 s | 128.3 | 20280 |
| region_adaptive | 2.505 s | 129.8 | 20280 |

## Decision and limits

Keep contours as the default for the initial desktop. On these generated vertical-wall interiors, region growing has comparable reference detection and better extent coverage in some cases, but costs more CPU time. Fixed region growing remains selectable for comparisons; adaptive tuning is an experiment, not a calibrated probability of correctness. Real annotated scans are needed before recommending a different default.

Concave and void benchmarks deliberately expose the existing convex slab-envelope limitation: 3 m² and 4 m² of footprint area error respectively. The wall-gap case evaluates incomplete surface coverage and does not implement an opening. Neither a good wall fit nor valid IFC makes those slab/opening cases accepted geometry. Unsupported regions must remain visible during review.

Detection/refitting temporaries are bounded by configured budgets, but this is not an unlimited out-of-core building engine. Original-record fitting revisits the working cloud for each face; source-page residency, element count, evidence files and XYZ loading still cost memory, time and storage. Coarser voxels can remove fine features and levels. Spatial tiling is a future response to measured real-file limits, not a tested capability here.

## Research used

Cloud2BIM's attributed contour/parallel-face helpers remain the baseline. Florent Poux and Alex Key's [LLM-Supervised Point Cloud Processing](https://doi.org/10.5194/isprs-archives-XLIX-B2-2026-1311-2026) motivates normal-based patches, adaptive parameters and structured spatial relationships. Punctora independently implements the geometric experiment; it does not reproduce the paper's complete system, performance or language agent.

SpatialLM informs the replaceable structured-proposal boundary. Pointcept/Sonata point labels, Apple Point-3D LLM spatial tokens, GPT4Point, MiniGPT-3D, ENEL and PointLLM-R remain optional research candidates. None is needed to finish M2 or launch M3; predictions would still need original-scan fitting and review. Creator/component notices remain in the attribution register. No external training data, paper text, model weights or region-growing source implementation was copied.

## M3 handoff and pending field evidence

Start with the desktop/worker job protocol and a local-origin cloud/model overlay using the same coordinate mapping. Add progress/cancellation, parameter review, unsupported-region flags, schema-2 project save/reopen, generation lifecycle cleanup, and validated IFC export. Preserve the observed faces and evidence when a user edits inferred geometry. Transactional project saves, renderer preview formats and persistent edit identity are M3 work.

Keep these checks open while developing M3:

1. Broader scanner/export E57 files, optional channels and vendor extensions, checked against an independent reference. Two supplied examples have passed [full-record import checks](M2_SUPPLIED_E57_VERIFICATION.md), using a shared native decoder; reconstruction and independent scanner accuracy remain unverified.
2. Annotated real floor subsets, assessed with the same provider comparison and agreed model tolerances.
3. A representative building E57 with measured import, fitting, RAM, evidence storage and correction effort.
4. Confirmed project CRS, vertical datum, orientation and control-point round trips. Missing CRS can remain explicitly unknown for local processing.

The attached point-cloud guidelines, pre-meeting checklist and acquisition report distinguish survey quality, agreed tolerances, registration/reference information and inaccessible areas. Generated fitting results do not certify those acquisition requirements or the resulting BIM model's contractual acceptance.
