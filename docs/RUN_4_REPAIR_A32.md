# Run 4 repair: 0.3.0a32

Historical record: the returned A32 stairwell test still failed. See the
[A33 amendment](RUN_4_REPAIR_A33.md) for the current repair and its limits.

A31 introduced an index-shadowing regression on the positive wall-query path.
This amendment repairs that crash, an independently reproduced section-alignment
defect and the subsequently reported stairwell slab-profile failure. It retains
the earlier CPU/RAM work and all unresolved Run 4
quality responsibilities. Run 4 remains awaiting the bounded external checkpoint.

## Returned A31 evidence

The screenshot and `BIG.zip` report the same error:
`'int' object has no attribute 'cell_size_m'`. The archive SHA-256 is
`cd6b876fbd1036b7bd05c902c5007b1854a756a4ab875d3e45619dda15552858`.
Its 14 entries contain the saved import, preview and failed-job diagnostics,
without the original working cloud or a published model.

| Observation | Verified value |
| --- | --- |
| Source | RS 138 EG Kita.e57; 210,167,583 original points |
| Source SHA-256 | `2c8f5f27778a894c3f38a6adb27c6ee53cebe72ce1607a3d8b2132830b40bce1` |
| Selected crop | 53,711,158 original points |
| Failed operation | 387.72 seconds, about 6 minutes 28 seconds |
| Recognition prefix | 254.77 seconds; failed in `prepare_instances` |
| CPU budget | 31 of 32 logical processors |
| Recognition RAM policy | 80%; combined limit 39,894,247,833 bytes |
| Sampled combined recognition peak | 19,877,634,048 bytes; no RAM-cap failure |
| Reached image branches | D/E/F/G/H/J returned inference results |
| Unreached branches | A/B/C sections and I point inference |
| Saved project | Original import retained; model remains absent |

The diagnostic traceback reaches `_stream_plan_tile`, then `SourceBox.blocks`
and `_iter_box_rows`. Its completed image calls do not establish complete branch
or model success. Worker CPU/wall telemetry includes preflight and cannot be used
as whole-application utilization.

This crop differs from A30's 50,162,412-point crop. Both operations failed.
Their elapsed times are descriptive failure observations, not a paired speedup
or evidence of a complete-operation runtime. Geometry publication and evidence
export still need a completed run on the user's computer.

### Returned stairwell evidence

The second screenshot and `Small(1).zip` report
`Profile repair would change components or introduce holes`. That archive's
SHA-256 is `06b07d3ea93d6ecf32481889cd21b921418e0524c31fb5ea9073e7acd60f70b9`.
Treppenhaus Sued stopped after **48.51 seconds**, in `slab_zone_geometry` calling
`clean_profile`, before specialist recognition. Its saved import contains
39,068,825 points and no published model. The original E57 was subsequently
retrieved from the shared Drive and verified against the project's source hash:
`758bffcc05e5704fd678220786f84c5ba4e38e6f110dfc356f2f40fd3f9745fb`.

## Challenges, causes and fixes

| Challenge | Demonstrated cause | A32 fix |
| --- | --- | --- |
| Crash after a positive J wall detection | A loop reused the spatial-index parameter name for an integer view counter; later wall/section reads received that integer | Distinct `spatial_index` and `view_index` variables at every affected use |
| B/C opening and beam proposals shifted away from an offset wall | Wall-scoped sections used the plan tile centre as their projection/restoration origin | Carry an origin per section job; use the J polygon centre for wall-scoped B/C |
| Passing tests missed positive detections | The isolated image worker returned no positive J boxes, so wall-specific lookup and section paths were not reached | Add positive detector outputs and require nonempty J instances and A/B/C proposals |
| Valid slab rejected during numerical cleaning | A sub-nanometre connection can split into several polygons on the existing contour grid | Explicitly retain every resulting slab component within the existing total area/symmetric-difference budget |

A generated horizontal wall reproduced the section displacement at 2.57 m. A
27-degree wall reproduced about 2.294 m perpendicular displacement. Both use
survey coordinates around seven/five million metres. After repair, decoded
section endpoints lie within 1 micrometre of the generated wall plane. This is
synthetic coordinate-contract evidence, not real-scan fitting accuracy.

Slab profile cleaning keeps its original single-profile contract. A new plural
API allows decomposition only for an already valid original exterior, with
unchanged geometry budgets, no introduced holes and a valid STEP representation
for each result. Minimum-component filtering happens before decomposition, so a
small lobe of an eligible slab is retained. Unchanged components retain their
IDs; split bodies receive deterministic child IDs and separately calculated
support/coverage evidence. Fixture-pattern classification uses the parent's
complete hole group, preventing decomposition from authorizing new fixture cuts.

Preserving the unsnapped narrow connection was rejected because an actual IFC
tessellation check produced the wrong volume despite valid profile syntax.
The retained approach verifies both slab bodies and real-hole/fixture cut policy
with tessellated IFC volumes. This is a geometry repair, not suppressed validation.

All original points, f64 coordinates, uint64 scan/record identities, ten model
branches, physical views, TTA votes, thresholds and learned weights retain their
contracts. A overview and orthogonal fallback sections keep their previous
origins. Implementation fingerprints include the changed core sources and
invalidate incompatible cached proposals.

## Engineering and result-analysis checks

All three mechanisms were observed failing before their repairs and passing afterwards.
The isolated worker test exercises the actual decoders, original-point index,
proposal publication and source-array references, with deterministic positive
fixture outputs. It checks:

- Positive J instances and wall-scoped B/C execution, plus nonempty A/B/C proposals.
- Exact serial/parallel instances, proposals, labels, scores and support rows.
- Exact original scan, record and working-row identities, including records above `2**53`.
- An identical-settings cache hit with the complete unchanged published report.
- Existing active-wave cancellation and unpublished staging cleanup.
- Independent perpendicular-distance checks on offset horizontal and rotated walls.
- Valid narrow-neck slab decomposition, small-lobe retention and deterministic identities.
- Genuine matched-face voids versus fixture holes distributed across split bodies,
  including preview area and actual tessellated IFC volume.

The engineering/test-quality skills were used for failing reproductions, missing
positive-path coverage and independent review. The result-analysis method keeps
source/crop identity, failure-stage scope and descriptive timings separate from
externally reviewed reconstruction quality. No quality or speed score is
inferred from fixture logits or a failed execution prefix.

Internal verification and Windows packaging results are recorded in PR #8.
The independent review found no remaining required issue in the focused repair.

Local final verification: **486 tests passed in 356.92 seconds**. Generated
quality-evaluator, immutable recognition replay/source-key export, hybrid replay
and acceptance-data separation checks also passed. Independent read-only review
ran the positive runtime cases and all 19 profile/slab safety tests successfully.

### Original stairwell CPU replay

The verified 39,068,825-point E57 completed classical reconstruction in **82.22
seconds**, or **90.43 seconds including IFC export**, on this Linux host with
four reconstruction workers and a 3.5 GiB explicit ceiling. All original points
were available; the existing bounded detection sampler remained active. The
result has 4 storeys, 30 walls, 8 slabs, 16 openings, 6 stair flights and 7 landings.
IFC validation passed with 90 tessellated products and no EXPRESS, geometry or
profile errors. The original file hash was unchanged after replay. See the
[bounded replay evidence](evidence/run4-a32-stairwell-cpu.json).

Importantly, instrumenting the old A31 profile function on these CPU-generated
contours produced **zero old profile failures**. This run therefore establishes
original-source CPU reconstruction/export compatibility, not reproduction of the
user's exact Windows/OpenCL contour or proof that every cause of that error has
been eliminated. The returned archive lacks that contour. Specialist inference,
desktop publication, complete evidence export and user visual acceptance are
outside this replay; its timing is not a complete-operation speed claim.

## Remaining performance and quality checkpoint

The EG Kita archive cannot replay the exact crop locally because its original
working cloud is absent. The original stairwell scan is available for a separate
CPU reconstruction/profile replay. The host used for internal checks is limited
to eight CPUs and 8 GiB RAM. It cannot qualify this 53.7-million-point Windows run or infer
the user's full CPU/GPU utilization.

Repeated source passes remain visible in diagnostics. In particular, section
queries currently gather support with a separate bounded pass per retained box.
A future shared support pass must preserve deterministic support rows and every
query before replacing that path. This repair makes no complete-runtime promise.

Install A32 in a separate directory and use the same saved crop/settings. First
check that recognition passes the previously failing wall-detection stage and
publishes a model. Return `last-performance.json` and the reconstruction job
diagnostic, even if the run fails. For a completed model, return matched cloud/
model views of ceiling fixture holes, wall-wide windows and stair direction.
The previous ceiling/glazing/stair findings remain open until reviewed.

Disposition: **implementation repair with internal verification; awaiting external
checkpoint**. Missing external evidence alone does not require repeating Run 4.
No full Fassade run is requested before the bounded crop has usable runtime.

## Dependency sources

The installed/pinned Shapely version is 2.1.2. Its official
[`set_precision` reference](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.set_precision.html)
documents that narrow sections can disappear and produce multipolygons. Its
[`make_valid` reference](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.make_valid.html)
documents possible geometry collections. Both behaviors are checked against the
actual installed library in the regression fixtures; no dependency was changed.
