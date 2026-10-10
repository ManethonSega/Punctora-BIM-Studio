# Run 1: reconstruction scale candidate, 0.3.0a18

Status: implementation and synthetic verification. The 210,167,583-point,
same-computer runtime and real-project geometry gates are pending. This is not
a completed performance acceptance run.

## Change from 8241da1

One index is built from the complete reconstruction cloud, shared across all
storeys, fitting, opening detection and source-evidence export. It groups
original row references into XYZ cells; it never rounds the original float64
coordinates or replaces scan/record identities with representatives. After a
conservative cell query, the original geometric selectors remain authoritative.

The former diagonal-only neighbour expansion could omit valid records. Queries
now intersect buffered finite faces conservatively at every wall angle. Each
fitting face selects its own height cells. Openings query the complete host
interval and height, with the same signed-plane return envelope as the reference
implementation. This includes returns outside offset observed faces.

Index sorting uses bounded runs instead of a whole-cloud sorting workspace.
Large run directories, row references and local point/ID copies use disposable
mapped files. The index receives half the existing resource planner's working
budget, which remains within the 70% available-memory policy. Its local cache
has a separate bounded allowance; parallel queries have smaller per-query
allowances. These are allocation policies, not a hard operating-system RSS
limit: mapped pages and other pipeline stages also use memory.

Equal queries reuse the same exact local subset. Fitting and openings share
the index and cache, but use different envelopes where opening evidence requires
wider returns. A fitting-only subset must never truncate the opening raster.

## Diagnostics and lifecycle

Fitting, opening and export loops count actual original-valued point visits,
including source-record materialization on cache misses. Per-stage mapped
visited-row bitmaps count distinct source rows, without summing overlaps as new
points. The report retains the source population as a separate reference.
Cell-directory operations and scans of validation masks are not described as
source-point geometric passes.

The denominator for cloud-equivalent visits is the complete reconstruction
cloud, including for multiple storeys. Index construction contributes one pass.
Source-evidence export reuses the retained index, extends the same live report,
and includes its duration, CPU and memory samples. The original heartbeat and
desktop cancellation paths remain active. Normal success and handled failure
close mapped files. Desktop termination removes only unpublished index temporary
directories after marking the durable report cancelled.

Python callers can use `write_model_evidence(cloud, model, directory)` to export
with retained runtime state. Call `model._spatial_index.close()` when a returned
model will not be exported. The private runtime handles are never serialized.

## Reproducible synthetic comparison

Command:

```sh
PYTHONPATH=src python3 scripts/benchmark_spatial_index.py --walls 144
```

Fixture: 144 separated walls, seven overlapping height faces each, a 61 x 61
grid of original points per wall, 535,824 source records total. Scan IDs and
working/source-record IDs are independently assigned. One CPU worker and BLAS
thread are used for both paths. The benchmark asserts fitted-face agreement
within 1e-10 m, equal evidence counts, equal opening outputs and byte-for-byte
equal exported source-record arrays.

The final recorded run used Python 3.12.14, NumPy 2.3.5, SciPy 1.17.0 and
OpenCV 4.11.0 on Linux 6.18.44 x86_64, nine reported logical CPUs. The source
baseline was local commit 8241da1021a9c5a345e130a524e0a003a299e1ba plus the
candidate changes saved with this report. See the accompanying JSON for timings.

| Measurement | Reference | Indexed |
| --- | ---: | ---: |
| Fitting duration | 21.284 s | 1.353 s |
| Index construction | none | 0.328 s |
| Fitting including index | 21.284 s | 1.680 s |
| Fitting cloud-equivalent visits | 3,168 | 8.623 |
| Index + fitting + openings + evidence export visits | not the reference fitting-only count | 12.623 |
| Opening duration | 3.064 s | 0.420 s |
| Evidence export duration | 3.771 s | 0.169 s |

Fitting speedup including index construction was 12.67x in the final run
(14.24x in an earlier run). These measurements include no E57 decoding, wall
proposal discovery, slabs, topology, stairs or IFC creation. They cannot be
extrapolated as the 210-million-point application's elapsed time.

## Acceptance still required

Local validation: all 194 Python tests passed. After the final mapped-cache
lifetime adjustment, the 36 spatial-index, wall-slice and performance tests
passed again. The Windows desktop build has not been run in this Linux
workspace, which has no .NET SDK.

Run the candidate Windows package on both the 210-million-point project and
RS 138 Treppenhaus Sued. Retain live diagnostics, final element geometry,
source-record evidence and reviewed staircase results. Confirm fewer than 25
complete-cloud-equivalent visits, no accepted-geometry/evidence regression and
less than 20 minutes on the same computer. If any gate fails, Run 1 remains open.

No Rust or new GPU backend is introduced. Preview, slab-hole policy and glazed
facade classification remain outside this candidate.
