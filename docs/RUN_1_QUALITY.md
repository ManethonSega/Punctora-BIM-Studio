# Quality Run 1: frozen truth and evaluation foundation

This is Run 1 of the thirteen-run quality plan in issue #1. It is separate from
the earlier spatial-index scale work. Starting commit:
`5327fdc172edec7849cbd30553591945b71aeb9b` (a27 development branch).
Reconstruction, detection thresholds, model schema and desktop behavior are
unchanged. This run adds read-only evaluation and developer commands.

## What is frozen now

The supplied a27 facade IFC and telemetry were hash-identified. Aggregate facts
are in `docs/quality/a27-artifact-baseline-v1.json`. No supplied IFC, raw scan,
customer annotation or model weight is committed.

The artifact baseline is **not independent ground truth**. It establishes
which output is being discussed: 13 walls, 98 opening elements, 2 windows,
0 doors, 0 slabs/roofs/ramps and 2 stair flights. Recognition accuracy,
source-record retention and complete floor/ceiling boundaries are unevaluated.
No measurement is invented from screenshots or successful export. The frozen
artifact's historical limitation text does not govern implementation sequencing.
The user revised the workflow: internal tests gate engineering runs, and
external quality qualification follows the completion of Run 9.

`docs/quality/acceptance-manifest.template.json` records the required facade,
Kita, stairwell, no-stair and held-out cases as pending. Copy it into ignored
`quality-local/`, not into production settings. Missing required cases fail
the benchmark, including when the missing case is held out.

## Local contracts

Independent truth and standalone predictions use schema 1 and metre units.
Every artifact declares `case_id`, the complete source `source_sha256`,
`coordinate_mapping` (`translation_m` and `yaw_degrees`) and `crop` (null or
the application's `polygon`, `z_min`, `z_max` crop). These must agree exactly
across the manifest, truth and prediction. Geometry remains float64/Python
double; original record IDs must be integer values, never floating point.

Truth additionally declares a `truth_revision`, `class_states` for all twelve
classes (`wall`, `door`, `window`, `opening`, `floor`, `slab`, `ceiling`, `roof`,
`stair`, `landing`, `ramp`, `column`) and explicit exclusions. Each state is
`present`, `absent`, `uncertain` or `out_of_scope`. `absent` is a real negative
case, not a synonym for unobserved. `present` means the independent element
list is complete within the declared evaluable crop. Uncertain/excluded
geometry is reported separately, not used to generate false certainty.

Elements have a stable truth `id`, `class`, `geometry` and optional
`support_state`, `source_records`, `observed_faces`, `void_only`,
`connections`, `connected_ids`, `observed_treads` and `inferred_treads`.
Geometry forms are:

| Type | Required geometry |
| --- | --- |
| wall | start/end XY, base, height, thickness; optional local profile_xz |
| opening | start/end XY bottom edge, base, height; element host_id |
| surface | footprint XY, holes, base; optional plane `[a,b,c]` for `z=ax+by+c`, thickness |
| stair | start/end XY, base, width, rise, going, steps |
| ramp | start/end XY, base, width, total rise |
| column | start/end XY plan axis, base, width, height |

All rings must be finite, valid and nondegenerate. This evaluator rejects
invalid profiles; it never repairs truth to fit a candidate. Tread indices
must be unique, in bounds and disjoint between observed and inferred sets.
Relations must resolve to declared IDs.

Semantic samples are keyed by `(source_sha256, scan_index,
source_record_index)`, with `label` and optional `boundary`. Missing
predictions count as false negatives. Extra predictions outside the labelled
sample are reported, not extrapolated to whole-cloud precision. Boundary
sample F1 is a labelled-sample measure; geometric surface boundary F1 uses
length covered within the declared boundary tolerance.

Ready manifest cases additionally require `source_kind` (`E57` or
`generated_fixture`), `split`, `truth`, `truth_sha256`, `prediction`,
`prediction_sha256`, `truth_revision`, and explicit numeric `gates`.
Optional `source_path` verifies the complete scan by bounded streaming hash.
An E57 case needs a visual-review record bound to the exact truth and
prediction hashes before it passes:

```json
{
  "visual_review": {
    "status": "passed",
    "reviewer": "independent reviewer",
    "truth_sha256": "<64 lowercase hexadecimal characters>",
    "prediction_sha256": "<64 lowercase hexadecimal characters>"
  }
}
```

Use the existing generated regression tests as executable contract examples,
not as real-building truth. A `generated_regression` suite can pass its tests
but cannot establish real-scan quality acceptance. It can support an internal
implementation gate without claiming that real-building accuracy improved.

## Metrics and safety

- Sorted, maximum-cardinality one-to-one matching, then minimum geometric
  cost. Nearby walls on different levels cannot match. Matrix size is bounded;
  larger annotation suites must be partitioned into explicit crops.
- Per-class instance precision/recall/IoU/F1 and independent sampled semantic
  precision/recall/IoU/F1. Empty denominators remain null.
- Wall endpoints, plane/angle, height/thickness/base, unsupported extension,
  union axis coverage, missing intervals, overlap length and wall-profile
  area coverage. Axis coverage alone does not certify full wall regions.
- Opening dimensions, class, matched host and independently recomputed host
  containment. A provider's containment flag is not trusted.
- Surface area IoU, symmetric difference, Hausdorff boundary distance and
  tolerance-based boundary precision/recall/F1, including concavity and holes.
- Applied cuts compared against independent permitted holes. An unmatched
  cut host makes safety unevaluated, not zero unsafe cuts.
- Stair/ramp dimensions, steps, observed/inferred counts and endpoint/landing
  associations. Absent stair cases report every proposed stair as a false
  positive. Explicit roofs and ramps can be annotated before schema 3 exists.
- ID/order-independent geometry signatures include profiles, holes, hosts,
  landing/endpoint associations and tread support states. Repeated results
  expose per-element differences rather than just a changed hash.
- Full mmap evidence arrays are checked in bounded chunks. Independent sample
  identities must occur on the *matched element*, not just somewhere in the
  project. Complete array fingerprints and missing identifiers are recorded.
  Counts and record examples do not prove full evidence retention.

Schema-2 model predictions can be used directly as `elements.json`. Their
metadata source, coordinate mapping and actual application crop are checked.
Rejected elements are not evaluated as accepted geometry. No absent
schema-3 class is fabricated. Provider-native point labels can use the
standalone prediction contract; connecting future providers is Run 2 work.
An optional `semantic_prediction` sidecar (with its own SHA-256) can provide
sample labels alongside an existing schema-2 model. It must have the same
source/crop/mapping and an empty element list, so labels cannot author geometry.
Floor surface levels are the top of the slab, not its underside extrusion
base. Both the evaluable face level and the solid base remain in the snapshot.
Roof plane height errors are separate from XY boundary distance. Unknown
surface roles remain slabs rather than being silently certified as ceilings.

The schema-2 coverage evidence currently contains areas and component bounds,
not full measured/justified/unsupported polygon partitions. Area declarations
are shown as **provider-reported**, not independent coverage certification.
Run 5 must preserve the polygons for stronger coverage evaluation.

## Commands

Freeze supplied artifact facts (same output is idempotent, changed content is
refused, use a new reviewed baseline revision):

```sh
python -m punctora_core quality-freeze-artifacts --ifc path/model.ifc --performance path/performance.json --output quality-local/a27-artifact-baseline-v1.json
```

Evaluate local acceptance without reconstructing or changing source data:

```sh
python -m punctora_core quality-evaluate quality-local/benchmark.json --output outputs/quality/report.json
python -m punctora_core quality-evaluate quality-local/benchmark.json --output quality-local/baseline-v1.json --freeze
python -m punctora_core quality-evaluate quality-local/benchmark.json --output outputs/quality/candidate.json --compare-baseline quality-local/baseline-v1.json
```

Exit codes: 0 means the declared evaluation passed, 1 means a required case or
gate did not pass, 2 means an invalid command/manifest/baseline. A missing
metric fails its gate. Comparisons refuse changed source/crop/mapping, truth
revision, truth digest, matching tolerance or acceptance threshold. Reports
are deterministic and contain no wall-clock generation timestamp.

CI checks that truth/tolerance changes and reconstruction changes are not in
the same commit. This is a guard, not review approval. Local customer truth
also needs separately reviewed revisions even though it stays outside git.

## Current Run 1 implementation decision

**Proceed.** The evaluator foundation and internal regression suite passed.
The revised plan applies real-scan numerical/overlay evidence at each relevant
responsibility checkpoint. An unavailable external input leaves that checkpoint
awaiting evidence; a reproduced defect can request targeted repair or redesign.
Quality reports return numerical results and missing-input status, but no
automatic engineering-run disposition.

**Redesign/update future run**, Run 6 must export full coverage-class polygon
partitions (not only areas/bounds), and Run 2 must provide source-keyed semantic
sample predictions through this contract. This clarifies evaluation artifacts,
not recognition thresholds. Existing source/provenance/geometry safety rules
remain unchanged.
