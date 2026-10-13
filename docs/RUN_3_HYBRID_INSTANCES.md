# Quality Run 3: hybrid 3D and projected 2D instances

Based on Run 2 commit `c2de73669c60a8b5118838397f25a79f826517eb`, stacked on
its development branch, not the older main branch. Run 2 Linux/Windows core
and desktop CI passed before this work began. This is the third run in the
nine-run quality plan, separate from earlier stair/slab work numbered Run 3.

## Implemented workflow

`Run 2 originals/proposals -> both wall views -> classical and optional 2D
regions -> original-point back-projection -> deterministic clusters/fusion ->
ProposalSet and ElementGraph -> review`

The developer workflow writes immutable proposal generations. It does not
change accepted model objects, desktop detection, saved projects, preview
cuts, opening hosts or IFC export. Run 4 remains responsible for validating
hosts, dimensions, profiles and cuts. No learned weights are downloaded or
bundled, and no new inference dependencies enter the base converter.

| Component | Behavior |
| --- | --- |
| `wall_projection.py` | Canonical f64 frames, mirrored views, signed depth, occupancy, optional original RGB and exact original-row pixel associations |
| `vision_provider.py` | Classical frame/void baseline plus a replaceable isolated local 2D worker protocol |
| `instance_fusion.py` | Complete-link both-view duplicate groups, independent class/filling/geometry evidence and provider-native scores |
| `element_graph.py` | Fingerprinted nodes, relations and evidence; reject missing references, containment cycles, promotion and cuts |
| `hybrid.py` | Match the Run 2 input exactly, reuse one job spatial index, produce evidence/graph artifacts and preserve point labels/scores |
| Existing raster/glazing/index modules | Add pure review-only void/repeated-bay helpers and bounded deterministic original-point DBSCAN; legacy detector behavior unchanged |

## Geometry and evidence

Frames are canonical under preliminary wall endpoint reversal. Front and back
views mirror along-wall pixels and reverse signed-depth convention. Two
measured planes are used when supplied. One measured face has two opposite
views of that same plane, not a fabricated measured back surface. With no
observed face, the envelope plane is explicitly inferred and cannot produce
a certified classical void candidate.

Pixels have a lower-left origin and half-open integer boxes. The final row or
column may be shorter than a full pixel. Ratios within 1e-7 of an integral
cell count suppress numerical slivers from rigid transforms at survey-size
coordinates. Pixel centres round-trip through the frame; subpixel local
coordinates/depth retain f64. Original record identity is exact, while rigid
coordinate arithmetic has ordinary f64 rounding. Source points are retrieved
through their original row associations, never replaced with pixel centres.

Projection arrays retain face counts, all local returns, nearest signed
depth, representative RGB and its validity mask. Unobserved depth is NaN,
not a zero plane. RGB is original f64 with no assumed 0-255 normalization;
the representative is selected by depth and immutable source key. Colors and
validity have bounded streaming fingerprints and invalidate hybrid caches.
The optional CLI source manifest now supports f64 `colors` N x 3 and boolean
`color_valid` N arrays alongside the required geometry/ID arrays.

Projection/back-projection uses only cropped original records, including
uint64 record IDs above 2^53. Evidence stores exact source-row arrays for
interior returns, observed frame support and column components, plus the
original detector mask and frame. These rows resolve through the ProposalSet
scan/record arrays and complete source SHA, never through floating point IDs.
Artifacts verify layouts, digests, pixel association/count consistency,
source/crop containment, mask dimensions, evidence counts and host-frame
identity before publication.

## What the candidates mean

Missing pixels alone are insufficient. Classical void proposals require
measured jambs and a head; above-floor gaps also require a sill. A floor-connected
portal remains an `opening` with unknown filling unless complementary point or
2D evidence supports a suggested class. Sparse/recessed returns are preserved;
a lack of glass returns cannot prove there is no opening or glass.

Door/window semantic labels and 2D masks can supply **suggested** classes.
Connected projected semantic components can also propose closed flush fillings
when occupancy contains no void. Components already covered by bounded frame
masks are not emitted again as broad duplicate envelopes across repeated bays.
Conflicting classes remain an unresolved opening, even when one provider's
native score is numerically much larger. A 2D class assertion with no filling
returns cannot certify a void's filling. The actual filling/material remains
unknown in every proposed opening. Unsupported native labels remain visible
in diagnostics/evidence rather than becoming the nearest IFC class.

Point-only and image evidence come from the same scan and may be correlated.
No independent probability is inferred from having two channels. Native
scores and their meanings remain separate; instance `native_score` is null
when a combined score would be misleading. Confidence cannot validate a host
or cut.

Both views/providers use conservative complete-link duplicate groups, so a
chain of nearby repeated façade bays does not collapse into one opening.
Grouping repeated bays retains individual holes and opaque piers; it does
not certify glazing material or curtain-wall construction. Cross-host wall
overlap reconciliation is deferred to Run 4; preliminary host IDs are not
silently rewritten into final topology.

Columns can originate from supplied 3D column labels or projected protruding
vertical-strip hypotheses. DBSCAN runs on original f64 neighbours ordered by
exact source keys. Ambiguous border points select the lowest stable core
component. Dense neighbourhoods or excess points fail explicitly. All column
channels are clustered together, avoiding duplicate both-view components.
Conflicting door/window semantics remain visible on an unresolved column
hypothesis. A vertical strip alone does not establish structural function.

Only observed component extents are retained. Missing bases/tops and occluded
gaps are not completed. A thin planar/line component may have bounds and exact
support but insufficient thickness for a parametric column. It then retains
`geometry: null`, `geometry_state: insufficient_for_parametric_geometry`,
proposed status and graph evidence. This narrow ProposalSet extension is
allowed only for an evidence-backed hybrid column; other malformed geometry
still fails. No new Column IFC/model schema is introduced in Run 3.

The classical baseline does not promise free-standing column recognition
without a semantic or projection cue. Real column recall, detector choice and
domain gap are final qualification items after Run 9, not invented capabilities.

## Optional isolated detector

`VisionProvider` can be replaced without changing geometry authority. The
default is `ProjectedEvidenceProvider`. `IsolatedVisionProvider` requires
explicit absolute Python, trusted local worker and configuration paths with
digests, runtime fingerprint and timeout. Configuration schema 1 must declare
`trusted_local_worker: true`, the same runtime fingerprint and any local
`model_assets` with exact file hashes. Missing assets/devices can leave the
classical path active. Bad digests, malformed boxes/masks and wrong response
identity fail; they are not silently accepted or downgraded.

The external worker receives NPZ image channels and a JSON request with frame,
source-image hash, configuration/hash, runtime fingerprint and response path.
It launches with the explicitly chosen Python `-I`, no shell or inherited
PYTHONPATH. A successful schema-1 response binds `frame_id`, `image_sha256`
and `runtime_fingerprint`, then supplies detections with class, integer `box`,
provider-native `native_score`/`score_kind` and optional `mask_pixels` (flat
row-major true-pixel indices). Exit 20 declares availability failure. Other
failure statuses or invalid outputs fail the job. Cancellation terminates
only the owned worker process tree and discards incomplete generations.

The worker and declared runtime are user-supplied, trusted local code. This
adapter verifies supplied file identities, not an independently audited model
build or deterministic GPU stack. The orchestration performs no install or
download. A particular pretrained 2D model is not silently substituted; no
learned 2D quality/hardware result is claimed by transport fixtures.

Cache identity includes requested detector/configuration/runtime, source
geometry/IDs, optional color/validity, upstream generation, frame/fusion
settings and core implementation. A published generation is a record of that
experiment, including per-view fallback and partial detector availability.
After changing the external environment/device, declare a new runtime
fingerprint to perform a fresh experiment rather than overwrite a generation.

## Resource and lifecycle checks

The job retains Run 2's 70%-of-available-at-start ceiling, stricter user cap,
bounded index/fusion, sampled combined process RSS, cancellation and diagnostic
heartbeat. Explicit cell, point, region and neighbour limits reject oversized
work without silent decimation. Large/dense walls currently require an
explicitly partitioned crop or larger admitted limits, not automatic coarser
resolution. RSS sampling is not an OS hard allocation guarantee.

Projection visit counters count repeated local original-coordinate visits,
not unique whole-cloud points or full-cloud-equivalent passes. No speed claim
or designated-computer timing gate is made. Quality remains the priority.
RAM admission now accounts for the actual source count when it is smaller than
the configured context maximum. CloudData error representations show safe
array metadata, allowing closed mmap inputs to be reported without touching
unmapped NumPy values.
If startup admission is insufficient, reconstruction/recognition first collect
completed reference cycles and, on supported Linux allocators, return already
free native heap pages. They then remeasure available RAM and reapply the same
70% ceiling and stricter user cap. Live source arrays remain untouched; genuine
shortage still fails. This is startup resource cleanup, not relaxed admission
or a change to detector/geometry rules.

## Commands and output

```sh
python -m punctora_core recognition-fuse quality-local/input.json --proposal-dir quality-local/run2/CONTENT_KEY --cache-dir quality-local/run3 --diagnostics outputs/hybrid-status.json
python -m punctora_core recognition-fuse quality-local/input.json --proposal-dir quality-local/run2/CONTENT_KEY --cache-dir quality-local/run3 --vision-assets quality-local/vision-assets.json
PYTHONPATH=src python scripts/verify_hybrid_instances.py --output-dir outputs/hybrid-generated
```

Optional `--settings`, `--tiles` and `--ram-gb` configure declared bounds.
Inputs must be the same original points/IDs, frame and crop as the unfused
Run 2 generation. Re-fusing an already hybrid generation is rejected.
Diagnostics cannot overwrite source assets or live in either immutable cache.

Each generation contains the original ProposalSet arrays and fingerprinted
`hybrid/projections-v1.json`, per-view images/row maps, per-region evidence,
`hybrid/element-graph-v1.json` and hybrid diagnostics. All graph nodes and
relations remain proposed/unresolved, with source evidence IDs. Host/part_of
cycles, missing references, acceptance promotion and any applied cut are
invalid. Evidence, graph and all arrays validate before atomic publication.
Cache replay retains the identical generation. No customer artifacts, source
scans, labels, weights or PDFs are committed.

## Internal gate and forward handoff

Controlled fixtures cover both-view pixel/local/source-key round trips,
rotated large-coordinate walls, repeated bays and door-shaped voids, sparse
filling returns, complementary labels, conflicting score scales, unavailable
and unsupported providers/classes, deterministic clustering, thin/volumetric
columns, crop/identity guards, corruption, cancellation, isolated transport,
RGB cache invalidation and zero accepted cuts. The smoke also runs the actual
classical detector on 52,804 generated originals, projects ten wall views,
publishes the graph and replays the cache without changing point labels/scores.

**Implementation disposition: Proceed with revised future scope**, after
internal regressions pass. Missing independent annotations, visual review,
model assets or designated hardware do not require repetition. External
recognition/geometry improvement is evaluated after all nine runs finish.

Run 4 must validate host profiles, physical openings, cross-host duplicates,
visibility/occlusion and class disagreements before applying any cut. It must
also treat incomplete column envelopes as unresolved geometry, not infer a
positive thickness just to satisfy a schema. Run 7 must preserve/align exact
proposal evidence separately from accepted geometry when composing models.
Run 8 must ground descriptions in support/state and omit unmeasured material,
structural function and unresolved dimensions. Run 9 must retain deterministic
source-order/clustering/graph parity and the classical fallback in native or
inference optimizations. None of these updates requires external qualification
before implementation can continue.
