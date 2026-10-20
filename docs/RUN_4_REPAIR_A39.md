# Run 4 A39: durable diagnostics and live specialist stages

## Returned A38 failure

The submitted `RS 138 EG Kita` crop contained 68,013,122 selected points. Base reconstruction completed in 105.91 seconds. Every A-through-J asset passed preflight, the owned A38 exchange worked, and 268 isolated-worker requests completed with zero inference failures. Peak combined recognition RSS was 22,440,873,984 bytes, below the 38,404,315,545-byte cap.

Recognition reached `specialist_image_views` and then failed while publishing a heartbeat. Windows denied replacement of the fully written temporary file with `last-performance.json`. The traceback ends in `atomic_json`, not ONNX Runtime, the owned exchange, geometry fusion or RAM admission. The saved project remained unpublished and preserved.

Code inspection found that recognition's monitor and inference threads could enter the same performance-writer closure concurrently. The returned report proves a destination replacement denial; it cannot distinguish that internal race from a short external reader, indexer or antivirus lock. A39 therefore addresses both demonstrated hazards without weakening atomic publication.

## Repair

- One lock now serializes snapshot assembly and publication to the immutable job diagnostic and `last-performance.json`. Older heartbeats cannot race newer ones or mutate shared retained state concurrently.
- Atomic JSON replacement keeps the flushed temporary file and retries a transient `PermissionError` on a bounded 25, 50, 100, 200, 400 and 800 millisecond schedule. A permanent denial still fails visibly after 1.575 seconds.
- The top status now reports nine real pipeline stages. Recognition heartbeats expose the active image branch, current view tile or point-semantic request, source-block count and elapsed time when those facts exist.
- The provider line changes from preflight pending to the requested provider, actual provider, CPU runtime and A-through-J readiness as soon as preflight completes.
- A brief blue highlight occurs only when the named stage changes. Elapsed-time heartbeats do not continuously flash, and text remains the primary state indicator.

The detailed stages are:

1. runtime and A-through-J asset validation;
2. source opening and crop materialization;
3. base geometry reconstruction;
4. specialist identity and spatial-tile preparation;
5. plan/section view generation and image branches A-through-H/J;
6. point-semantic branch I;
7. proposal stitching and source-array validation;
8. original-point refitting and optional hybrid evidence;
9. evidence retention, candidate validation and atomic publication.

No geometry rule, threshold, model asset, ONNX graph, source coordinate, evidence identity or IFC mapping changes in A39. Provider/cache identity remains 4.4 because proposal semantics are unchanged. Desktop/core version is 0.3.0a39.

## Internal evidence and remaining checkpoint

The diagnostic regressions reproduce a transient replacement denial and concurrent heartbeat entry. They require successful bounded retry, valid final JSON and a maximum of one active publication. Progress regressions bind image views, branch I, proposal stitching and original-point fusion to their displayed stages and live counters. The desktop verification checks the long live status, truthful runtime line and stage-change highlight.

The returned report also records 199,387 source blocks, 8,215,941,036 selected point visits and 2,746.60 seconds of specialist source reading. That is a measured performance issue, not the cause of this failure, and A39 does not claim it is solved.

External quality acceptance remains pending. Re-run the same small `RS 138 EG Kita` crop first. If it publishes successfully, report ceiling closure and wall-wide-window recognition, then run the stairwell crop and report stair/wall alignment and completeness.
