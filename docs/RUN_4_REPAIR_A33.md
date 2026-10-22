# Run 4 repair: 0.3.0a33

A32 did not resolve Sega's stairwell failure. This amendment addresses additional
profile representations rejected by the same guard and preserves the exact
failing contour in future diagnostics. It does not claim to have reproduced the
missing Windows contour. Run 4 is not accepted.

## Returned A32 evidence

The screenshot identifies version 0.3.0a32 and reports
`Profile repair would change components or introduce holes`.
`Small(2).zip` has SHA-256
`0d40c1a28f67f39a0f1327b5d23eaf76ad3913d32672832716b14dd53f8910dc`.
Its 14 entries contain the imported project, preview and failed-operation
performance report, without the original cloud cache or offending contour.

| Observation | Verified value |
| --- | --- |
| Source | RS 138 Treppenhaus Sued.e57 |
| Original/valid points | 39,068,825 |
| Source bytes | 745,524,224 |
| Source SHA-256 | `758bffcc05e5704fd678220786f84c5ba4e38e6f110dfc356f2f40fd3f9745fb` |
| Crop | None |
| Surface mode / reconstruction scope | Contours / Auto |
| Failed desktop operation | 45.9242153 seconds |
| Failure boundary | `slab_zone_geometry` calling `clean_profiles` |
| Specialist inference | Not reached |
| Saved model | Absent; imported project retained |

The failure was before recognition. It supplies no evidence about A-J execution,
recognition quality or complete-operation performance. Its final error report
also overwrote earlier stage/settings evidence, preventing precise replay.

## Challenges, demonstrated causes and changes

| Challenge | Demonstrated cause | A33 change |
| --- | --- | --- |
| Point-touching compound boundary rejected | A32 disallowed several repaired bodies when the original exterior was invalid, even with zero occupied-area change | Retain every polygon leaf within the unchanged area, difference and overlap budgets |
| Bodies lost in nested collection | A point-touching contour plus zero-width backtrack produces a GeometryCollection containing a MultiPolygon | Iteratively collect nested polygon leaves; exclude zero-area linework without dropping solid bodies |
| Existing exterior bay becomes a hole on the numerical grid | A sub-nanometre mouth closes; A32 rejected all interior rings | Partition through existing voids into hole-free slab bodies, preserving the occupied set and leaving the bay empty |
| Fragment decisions can change after partition | A real hole or fixture can cross the partition and produce fragments smaller than the original eligibility threshold | Classify the complete parent hole before partition; retain every positive fragment with its parent identity, evidence and decision |
| Failure report loses the evidence needed for replay | A minimal final error replaced the last heartbeat and reset measured geometry time | Merge durable snapshots; retain stages, settings, source identity, events and measured geometry/evidence duration |
| Geometry failure still cannot be reproduced from its report | Original contour and library versions were absent | Attach bounded exact original WKB, hash, validity, precision, versions and slab/zone identity to profile errors, including native GEOS failures |

The contour grid remains 1 nanometre. The existing budget remains
`max(1e-8, original_perimeter * precision * 4)` square metres. Both occupied-area
change and symmetric difference must fit this budget; overlapping children must
also remain within it. Meaningful self-intersections remain errors. The
single-profile API still rejects multiple bodies. Slab callers explicitly accept
the plural representation, deterministic child IDs and per-body evidence.

Partitioning reduces the total number of interior rings on every accepted split.
No largest-component selection, convex hull, hole filling, tolerance increase or
source-point edit is used. Genuine matched-face holes remain eligible for cuts;
fixture-pattern fragments retain their unvalidated state. The new tests verify
actual IFC tessellated volume, not only syntactically valid profiles.

Contour capture is complete through 8,192 vertices. Larger contours retain their
count, hash, validity, area, precision and library versions, with an explicit
`omitted_above_8192_vertices` marker. They do not silently claim a complete
capture. Exact contour coordinates are source-derived diagnostic data. Canonical
point arrays and source selectors are not copied into reports or changed.

## Verification and limits

Engineering and test-quality skills guided observed failing regressions,
boundary coverage, mutation checks and independent read-only review. The
result-analysis method distinguishes returned failure evidence, generated
geometry checks and original-source compatibility from external quality review.

- The new point-touching, nested-body and precision-closed-bay cases failed before
  repair and pass afterwards. Multiple voids and survey-coordinate offsets are
  included.
- A parent hole crossing a partition retains both its 0.112 and 0.528 square
  metre fragments. Real-hole and three-fixture cases verify preview area, IFC
  opening relations and actual tessellated volume.
- Failure tests verify exact WKB capture, payload bounds, native GEOS errors,
  heartbeat/timing retention and an unchanged saved project with empty staging.
- Removing the meaningful-geometry budget guard makes its regression fail; the
  exact source was restored after this executed mutation experiment.
- Independent review identified nested-body loss and two diagnostic gaps. Those
  findings were repaired with observed failing tests. Final read-only review
  found no remaining actionable issue in this focused diff.

Final local verification: **501 tests passed in 348.40 seconds**. CI and package
results are recorded in PR #8 after execution. No generated case establishes the
user's exact Windows contour or recognition accuracy.

The first full-suite attempt was not accepted as verification: it had 32 failures
and 16 setup errors, predominantly RAM admission failures after the large replay
warmed this host's file cache. It also had a facade-count mismatch under that
resource condition. Releasing cached pages of the replay files restored reported
available memory from 1,201,905,664 to 7,970,205,696 bytes. The standalone rerun
then passed all 501 cases without changing application memory limits, detection
settings or assertions.

### Original-source desktop project replay

The complete 39,068,825-point scan passed the classical desktop project path in
105.04 seconds, including reconstruction, evidence export, validation and model
publication. A separate IFC export/revalidation took 11.14 seconds. Import and
specialist inference are outside these timings. This is descriptive compatibility
evidence on this host, not a designated-computer speed claim.

The saved model reopened identically. All 18,921,609 exported wall-evidence rows
matched the original scan and record identifiers. All seven imported channels
matched an independent original-source cache by full-file SHA-256; the source E57
hash was unchanged. IFC validation passed with 89 tessellated products and no
EXPRESS, geometry or profile errors. The model contains 4 storeys, 31 walls,
8 slabs, 15 openings, 6 flights and 7 landings.

Automatic resource admission selected seven workers and a 286,687-point detection
budget. Earlier CPU replays used different resource budgets, so their element
counts and timings do not establish paired parity or improvement. The full
original source remained available to fitting and evidence stages. See
[the bounded desktop replay evidence](evidence/run4-a33-stairwell-desktop.json).

Publication recorded zero staging bytes. After return, this host recreated
492,395,608 bytes at old staging paths. An independent asynchronous `os.replace`
probe with plain binary files and no Punctora imports also recreated source paths
five seconds after a successful rename. This observed host behavior limits a
post-return cleanup assertion here; it is not reported as an application cleanup
pass or used to change production cleanup code.

## Bounded checkpoint

Install A33 separately and reopen the same imported stairwell project with the
same contour/Auto settings. First check that reconstruction passes the previous
slab-profile stop and publishes a model. If it fails, return the small
`last-performance.json` or the matching reconstruction diagnostic. A profile
failure now includes its exact contour when within the capture bound, so another
report need not depend on screenshots alone. A 39 GB asset upload is unnecessary
for this diagnostic.

For a completed specialist operation, the earlier ceilings, wall-wide glazing,
stair direction and full-runtime findings still require matched cloud/model
views and a complete report. Treppenhaus's earlier visually acceptable classical
result is retained as user evidence; it is not relabelled as specialist success.
No full Fassade run is requested before the smaller cases have usable runtime.

Disposition: implementation repair with internal evidence, awaiting the bounded
Windows checkpoint. External evidence missing by itself does not force Repeat.

## Dependency sources

No dependency changed. The pinned Shapely 2.1.2 official
[`set_precision` documentation](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.set_precision.html)
explains collapsed narrow sections and multipolygon results. Its
[`make_valid` documentation](https://shapely.readthedocs.io/en/2.1.2/reference/shapely.make_valid.html)
covers geometry collections; the
[`split` documentation](https://shapely.readthedocs.io/en/2.1.2/manual.html#splitting)
describes explicit geometry partitioning. Tests exercise the installed library
and require conserved occupied area; documentation alone is not proof of safety.
