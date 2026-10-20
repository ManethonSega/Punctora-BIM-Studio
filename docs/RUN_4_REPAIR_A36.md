# Run 4 A36: durable specialist worker control transport

## Submitted failure

The submitted A35 `RS 138 EG Kita` crop imported all 210,167,583 source points and selected 69,160,774 crop points. Reconstruction completed before recognition, including 48 consolidated walls, 15 openings, one stair flight and one landing. All A through J assets and ONNX Runtime 1.23.2 passed scan-free preflight.

Specialist recognition then failed in `prepare_instances` after 134.55 seconds. The persistent specialist worker received an absolute path to a newly written transient `request.json`, but its first attempt to open that file raised `Errno 2`. The complete desktop operation stopped after 431.90 seconds. The saved project remained unchanged.

The absent staging tree observed after the failure is expected. Failed and cancelled generations are unpublished and are deleted by the project generation context. That cleanup proves the partial generation did not become a saved model, but it cannot make a path-based worker request reliable.

## Repair

The persistent worker protocol is now `persistent-json-lines-v2-inline-request`.

- The host serializes the small validated request object directly into the existing JSON-lines pipe.
- The worker accepts only an inline object tied to the monotonically increasing request ID. The obsolete path-string request contract is rejected.
- Large NumPy tensors and ONNX outputs remain bounded file-backed data inside the private attempt directory.
- Response identity, timeouts, cancellation, combined parent/child RAM monitoring, session admission and atomic proposal publication are unchanged.
- No temporary request file enters evidence, the immutable proposal cache or a saved project.

This follows the Cloud2BIM reference decision for job-local state and validated atomic generations. Its E57-to-XYZ working-data route does not address this incident because import and reconstruction had already completed before the worker-control failure.

The specialist provider identity is 4.3 and the desktop/core version is 0.3.0a36, so an A35 proposal cache cannot be reported as an A36 specialist result.

## Regression coverage

The repair is guarded at both ends of the persistent connection.

1. A generated long Unicode project path reproduces the A35 missing-file error when the host sends a request path, then passes with the inline request.
2. The production worker accepts the inline object, writes the response for the matching request, and rejects the obsolete path-string contract.
3. Existing serial/parallel image waves, point branch I, cancellation, proposal publication and source-identity tests remain in the normal suite.

These checks prove the transport contract and cleanup behavior. They do not establish real-scan recognition quality. The next bounded external checkpoint remains the same small EG Kita ceiling and wall-wide-window crop, followed by the stairwell crop.
