# Run 4 A38: owned specialist worker exchange

## Returned failure

The submitted A36 `RS 138 EG Kita` crop contained 68,757,314 selected points. Reconstruction completed in about 26 minutes with 52 consolidated walls, 13 openings, one stair flight, one landing and eight slab openings. All A-through-J assets and ONNX Runtime CPU preflight passed. Recognition remained inside its memory ceiling.

Recognition then failed at the first parallel image wave because the isolated worker could not open `0-tensor.npy` below the deep project proposal-staging path. This is downstream of the A36 control repair: the inline request reached the worker correctly, but large tensor, feed, output and response payloads still depended on reopening files inside the same fragile project path boundary.

The report proves the named tensor was unavailable when the worker opened it. It does not distinguish a Windows path/filesystem visibility failure from external removal of that transient entry, so A38 does not claim a narrower unobserved cause.

## Repair

The provider now owns one private exchange directory in the operating-system temporary area for the duration of a specialist attempt.

- Image tensors, point-branch feed arrays, feed manifests, ONNX outputs and worker response files use the exchange instead of the project proposal-staging tree.
- NPY inputs are written under a private temporary name, closed and atomically renamed before the inline request exposes their final names to the worker.
- The persistent worker is stopped before exchange cleanup. Failed requests stop the worker without deleting files beneath caller contexts that are still unwinding.
- The exchange is removed on success, failure and cancellation and never enters evidence, a proposal generation, a saved project or an IFC.
- Reviewed proposal artifacts and original-point traceability continue to use the existing private generation and atomic publication rules.

The worker protocol is `persistent-json-lines-v3-owned-exchange`. The specialist provider identity is 4.4 and the desktop/core version is 0.3.0a38, preventing older proposal caches from being reported as an A38 specialist result.

## Internal evidence

The regression creates a deep Unicode project path and requires image tensors, image outputs, point feeds, point outputs and response paths to remain inside the separate owned exchange. It verifies that no tensor enters project staging and that `close()` removes the exchange. The isolated worker integration now opens every image tensor rather than allowing tests that only wrote synthetic outputs.

These tests establish transport location, complete-name publication, worker access and cleanup. They do not establish real-scan recognition quality. The external checkpoint remains the small `RS 138 EG Kita` ceiling/wall-wide-window crop, followed by the stairwell crop after the first result completes.
