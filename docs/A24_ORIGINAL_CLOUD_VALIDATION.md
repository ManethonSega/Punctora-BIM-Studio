# 0.3.0a24 original-cloud validation

This report compares the cumulative Runs 1–4 candidate with the complete
`RS 138 EG Kita.e57` source and the supplied a22 IFC. It is a reconstruction
diagnostic, not a survey-accuracy certificate or ground-truth BIM comparison.

## Source and identity

- E57 SHA-256: `2c8f5f27778a894c3f38a6adb27c6ee53cebe72ce1607a3d8b2132830b40bce1`
- Valid records: 210,167,583
- Coordinates: `f64`
- Scan identifiers: `uint32`
- Original E57 record identifiers: `uint64`
- Corrected occupied storey interval: 1.85010 m to 4.85498 m local Z

The spatial index stores source row numbers and materializes all identity
channels with every local point subset. The final model contains immutable
selectors and 5,600 checked record examples across its walls; complete evidence
export uses the same selectors to write working row, scan ID and original E57
record ID columns. No `f32` reconstruction copy is introduced.

## Geometry result

| Measure | a22 IFC | 0.3.0a24 candidate |
| --- | ---: | ---: |
| Walls | 139 | 176 |
| Wall openings | 27 | 59 |
| Windows | 1 | 34 |
| Doors | 22 | 19 |
| Unknown opening candidates | 4 | 6 |
| Slabs | 13 | 2 consolidated surfaces |
| Review-only slab gaps | not safely distinguished | 43 |
| Stair flights | 1 | 1 |

The strict persistent-vertical-evidence plan comparison places 98.9508% of
wall-evidence pixels within 0.20 m of candidate wall geometry. The a22 overlay
had 11 missing regions; the candidate has three, with length proxies of 0.48 m,
0.36 m and 0.32 m. The reported missing corner is covered. Conversely, 83.7752%
of candidate wall-raster pixels are close to this strict full-height evidence.
Openings and partial-height walls lower that second measure, but unsupported
candidate spans still require visual review.

The large recognized façade contains four 1.60 m panels across a 7.85 m zone.
Another repeated zone spans adjacent reconciled hosts and retains all supported
bays. These systems export as normal `IfcWindow` elements because continuous
curtain-wall rail and mullion evidence is insufficient. Opposite-face opening
duplicates are removed after wall reconciliation.

The reconstructed stair has six steps, 0.18982 m rise, 0.25892 m going and
1.08447 m width. Treads 0, 1, 2 and 5 have original-point support; occluded
treads 3 and 4 are identified as inferred. Reopened IFC geometry reports zero
physical stair/slab intersection and zero residual area below the required
2.0 m headroom envelope.

All 43 horizontal occupancy gaps remain visible review candidates and zero are
exported as slab voids. This includes the repeated light-fixture-like gaps.

## IFC validation

The reopened IFC4 contains 292 tessellated products. EXPRESS validation and
geometry creation report no findings or errors. This proves file consistency;
it does not establish dimensional accuracy by itself.

## Performance result

The full 210,167,583-record reconstruction completed in 2,614.995 seconds in
the constrained 8 GiB Linux validation container; IFC write and reopen brought
the harness total to 2,629.591 seconds. The run processed 5,330,401,851 logical
point visits, or 25.363 complete-source equivalents. Stage diagnostics report
27.445 logical passes when storey-filtered proposal and stair sample passes are
counted as whole stage passes.

| Indexed stage | Point visits | Unique source points visited | Complete-source equivalents |
| --- | ---: | ---: | ---: |
| Index construction | 210,167,583 | 210,167,583 | 1.000 |
| Wall fitting | 1,590,667,450 | 124,731,950 | 7.569 |
| Opening detection | 1,750,711,695 | 174,161,796 | 8.330 |
| Final wall/opening reconciliation | 324,924,432 | 40,574,141 | 1.546 |

This reduces the prior diagnostic count from 2,616 passes to approximately
25.36 complete-cloud equivalents, but it is slightly above the preferred
below-25 threshold. This container also does not meet the under-20-minute exit
requirement. Run 1 therefore remains open until the Windows candidate completes
under 20 minutes on the same computer, including evidence export. Diagnostics
now distinguish unique points from repeated visits for every indexed stage.

## Remaining acceptance

- Inspect the three small unmatched wall-evidence regions and candidate spans
  without strict full-height support.
- Run the portable Windows build on the same 210-million-point file and record
  the complete reconstruction plus evidence-export time.
- Measure adaptive orbit performance and full-quality restoration on the Intel
  UHD adapter.
- Rerun and compare `RS 138 Treppenhaus Sued` to confirm the existing normal
  doors, windows and staircase project remain correct.

