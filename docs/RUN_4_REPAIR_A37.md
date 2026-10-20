# Run 4 A37: reconstruction RAM admission accounting

## Returned failure

The submitted A36 RS 138 EG Kita crop contained 68,757,314 points. Level detection completed, then reconstruction admission failed before the spatial index or geometry stages. The report recorded 24,298,508,288 available bytes and a 17,276,260,352-byte Punctora working set on a 64 GiB computer.

The planner treated 70% of currently available physical RAM as a total process limit and then subtracted the existing Punctora RSS. Available physical RAM already excludes that RSS, so it was counted twice. The faulty calculation produced a negative working budget and the misleading instruction to close applications. This run requested Classical recognition, so the A36 inline specialist transport was not exercised.

## Repair

The automatic reconstruction ceiling now matches the established recognition policy shape:

1. begin with the current Punctora RSS;
2. add at most 70% of currently available physical RAM;
3. cap the combined process limit at 70% of total physical RAM;
4. apply a lower explicit `maximum_working_memory_gb` ceiling when configured;
5. reserve mapped-source and working-chunk memory from the resulting additional budget.

For the submitted measurements this admits 16,984,955,801 bytes, 15.82 GiB, of additional reconstruction working memory after the 24,000,000-byte mapped-source reserve. It remains below the total-memory safety ceiling. Diagnostics now include total physical RAM and the combined process limit. A genuine rejection reports available, Punctora and total GiB instead of implying that installed RAM equals usable RAM.

No geometry algorithm, recognition threshold, A-J asset, source identity, coordinate precision, review state or publication rule changes in A37. A36's inline worker request transport remains intact.

## Internal evidence

The regression uses the exact submitted available-memory and process-RSS measurements. It fails under the A36 formula and passes after the repair. Existing tests cover reclamation before rejection, explicit lower ceilings, mapped-source reserves, the 70% available-memory working budget and the independent 70% total-memory process ceiling.

Internal tests and portable-package results establish admission-control behavior only. Completion and real-scan geometry quality remain external checkpoints.
