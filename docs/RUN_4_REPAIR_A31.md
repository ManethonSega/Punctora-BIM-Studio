# Run 4 repair: 0.3.0a31

This amendment addresses the returned a30 EG Kita crash and excessive runtime.
Earlier EG Kita and Treppenhaus Sued findings and later element-family quality
responsibilities remain in force.

## Returned a30 evidence

The uploaded project archive contains the saved import, preview and durable
performance diagnostics, but not the original working cloud or failed model.
The screenshot reports a `MultiPolygon` / `exterior` failure.

| Fact | Verified value |
| --- | --- |
| Original scan | 210,167,583 points |
| Selected crop | 50,162,412 points; 23.87% of source |
| Complete operation | 53,258.38 s; 14 h 47 min 38 s |
| Specialist recognition | 53,105.88 s; about 99.7% of total |
| Reconstruction and evidence | 110.24 s |
| Model-view population | 57,853,370; 1.1533 times the crop |
| Specialist branches | All A–J active |
| Last geometry-fusion phase | 379.08 s, included in recognition |
| Sampled reconstruction peak RSS | 22,104,592,384 bytes |
| OpenCL | Voxel indexing: 996 calls, 2.283 s; not ONNX inference |
| Saved project | Model remains null; original import generation preserved |

Europe/Berlin times: started 14 October 2026 at 22:57:13; failed 15 October at
13:44:52. The job was already failed when reported as still running. The six-hour
a29 case and fourteen-hour a30 case are separate measurements. Improved overlap
alone did not solve specialist runtime.

## Crash repair

The reporting signature rounds a valid polygon to a 1 micrometre grid. A valid
narrow connection can split during this operation, producing a MultiPolygon.
The old implementation then accessed a single exterior. A generated valid slab
reproduces the exact exception; signature version 2 canonicalizes every polygon
component and hole. It does not discard geometry or change coordinates or cuts.

The regression checks component sensitivity, ordering/orientation invariance and
unchanged serialized geometry. The user's actual offending polygon cannot be
identified from this archive. The reproduced defect is consistent with the
reported error and failure timing.

Legacy reporting hashes and version-2 hashes are not directly comparable; records
without a signature version are version 1. Run 1's independent quality snapshot
signature is unchanged. New failures retain exception type and source frame
locations without capturing local variables.

## Runtime implementation

1. Desktop CPU-worker settings reach recognition. Automatic mode reserves one
   logical processor and respects container quotas. Explicit requests are clamped
   to available CPUs. Production inference no longer has a fixed two-thread cap.
2. Independent D/E/F/G/H views execute in bounded waves with interleaved branches.
   D results precede J refinement; independent J views can share a loaded CPU
   session. Every tensor keeps batch size one, its physical frame and audited
   preprocessing. Session creation and LRU changes stay on the server thread.
   Results are consumed in input order, not completion order.
3. At most five image jobs are admitted, bounded by CPU, session-cache and
   estimated activation budgets. Each image pool receives `cpu_budget // lanes`
   threads; their product cannot exceed the CPU budget. Point inference has its
   own phase budget. Nested BLAS/OpenMP pools are limited to one and idle ORT
   spinning is disabled. CPU utilization alone is not the success metric.
4. Preflight retains admitted sessions. Eviction precedes replacement creation.
   Runtime choices are included in session keys and provider fingerprints.
   Provider 4.1 / model-pack contract 2 records this policy; all supplied graph
   and companion hashes remain unchanged.
5. Original-neighbour queries use the CPU budget. Source f64 coordinates, radius,
   neighbour count, normal sign, voxel representatives, all forty point tensors
   and inverse/source mappings retain their contracts.
6. Tiny spatial-cell reads are combined into capped blocks without reordering or
   losing rows. All twelve physical plan fields are rasterized in one source
   pass. No points, TTA views, branches, model precision, score/vote thresholds or
   physical raster scales are reduced to obtain speed.
7. Durable diagnostics retain nested host phases, per-branch session/input/run/
   output times, worker process CPU/wall seconds and spatial-cell/block/point-read
   counters. Concurrent component times overlap and cannot be summed as elapsed
   time. Late failures preserve the last specialist heartbeat.
8. `job_completed` is emitted for desktop publication only. Earlier reconstruction
   completion has a separate event. Failures/cancellation have terminal events.
   Total time includes crop, geometry, recognition, validation, evidence and
   publication. This change does not enable GPU ONNX inference.

## User-requested RAM policy

Recognition defaults to **80%**, with an API policy range of **70–80%**. For
baseline process RSS `B`, currently available RAM `A`, physical/container RAM `T`,
fraction `f` and optional lower absolute user cap `C`:

`combined_limit = min(B + f*A, f*T, C when supplied)`

`working_budget = combined_limit - B`

The user's 64 GB is not assumed free: the actual available-memory reading decides
the budget. Source, worker and descendant processes are sampled together. Cached
graphs and concurrent activation estimates share this working budget. Admission
and sampled RSS are not an OS hard allocator limit. Reconstruction sampling keeps
its 70% automatic policy, so both stages remain in the requested 70–80% band.

## Verification and benchmark

The core command is `python -m pytest -q`. Regression coverage includes the
reproduced crash, complete-component preservation, CPU/RAM admission, bounded
concurrency, result ordering, exact parallel normal parity, serial/parallel
proposal/label/score/source-support parity, active-wave cancellation, cleanup and
failed-diagnostic preservation. Twelve streamed rasters match the independent
all-at-once renderer at survey coordinates, including rotated/mirrored views.

Local verification: **475 tests passed in 352.44 seconds** on the final core
revision. The signature and per-cell regressions were observed failing before
their respective repairs and passing afterwards.

The supplied D/E/I weights were hash-verified and measured on a Linux host limited
to eight CPUs and 8 GiB RAM using ORT 1.23.2, with fixed generated inputs. The
benchmark separates cold starts, alternates warm configuration order and records
descriptive paired timings. It compares legacy two-thread sequential work with
the new seven-CPU budget. It also compares A30 per-cell reads with coalesced reads,
checking exact point/source-ID digests. See [JSON evidence](evidence/run4-a31-specialist-runtime.json).

| Bounded component check | Legacy | a31 | Result |
| --- | --- | --- | --- |
| D/E image pair, median of five warm trials | 0.7785 s | 0.3963 s | 1.96x faster; both masks/logits exact |
| I, 8,192 voxels, median of five warm trials | 0.7048 s | 0.3587 s | 1.96x faster; zero label differences; maximum logit difference 9.54e-6 |
| 96,000 points / 12,000 spatial cells | 0.4883 s / 12,000 blocks | 0.02164 s / 2 blocks | Exact row/value digests; about 22.6x faster for this reader fixture |

```sh
python scripts/benchmark_specialist_runtime.py --model-root /absolute/path/to/models --output outputs/runtime/benchmark.json
```

These are component measurements, not scan-quality scores or an EG Kita completion
promise. Point logits can differ slightly across thread counts. Generated label
parity does not establish real-scan parity or absence of threshold-sensitive
changes. The exact fifty-million-point crop and Windows/AMD hardware remain
unqualified by this host's component benchmark.

## Checkpoint

Keep the original project unchanged; install a31 separately. Use the same crop
and unchanged settings, testing the affected ceiling/window crop first. Return
`last-performance.json`, the job diagnostic and matched cloud/model views of
ceiling coverage, wall-wide glazing and stair alignment. The report now includes
the effective CPU/RAM plan and branch/read counters; a full assets upload is not
needed for timing diagnosis.

Reproduced a30 defects justify this implementation repair. After internal checks,
the disposition is **awaiting the bounded external checkpoint**, not accepted.
Missing external review alone never means Repeat. A full Fassade run is not
required before the crop has usable runtime. No under-twenty-minute or six-hour
guarantee is inferred from microbenchmarks.

## Sources and review methods

- [ORT thread management](https://onnxruntime.ai/docs/performance/tune-performance/threading.html): explicit pools, sequential graph execution, contention and spinning.
- [ORT CPU-session concurrency and test references](https://github.com/microsoft/onnxruntime/discussions/14073): concurrent runs; construction/cache changes remain serialized here.
- [SciPy 1.17 cKDTree query](https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.spatial.cKDTree.query.html): exact default queries and `workers`.

Engineering methods: systematic debugging, source-driven development, code review,
test-gap analysis, test anti-pattern review and verification before completion.
Result-analysis methods: matched inputs, descriptive timing, numerical/label
parity, immutable source identity, and separation of internal checks from external
reconstruction-quality acceptance. No model training or accuracy claim is added.
