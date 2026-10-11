# Large desktop results, 0.3.0a22

The customer's 210,167,583-point reconstruction completed, including original
record evidence export, in 835.2169 seconds (13 minutes 55 seconds). The live
report records 16.6096 cloud-equivalent passes, 139 fitted walls, 27 wall openings,
one stair flight and 42 slab-opening candidates. Candidate count is not IFC cut
count. Geometry, glazing and slab policy still require review against the scan.
The measured peak worker RSS was 20,141,772,800 bytes. Existing optional OpenCL
voxel work was active; wall fitting remained on the CPU.

The desktop subsequently rejected the result with `Worker response exceeds the
message budget`: a result containing model evidence and derived preview meshes
exceeded the 16 MiB stdout control-line budget. Its screen therefore retained the
old empty model even though detection and evidence export had completed.

WorkerClient now creates a separate temporary exchange directory for each job.
It streams the full request to request.json and sends a small control envelope.
The worker writes the complete result atomically to result.json and sends its
location, job identity and protocol version. The desktop validates the expected
path and payload identity, parses the file without the control-line size limit,
and deletes the exchange after success, failure or handled cancellation. Source
points, IDs, evidence and geometry are not thinned to fit the protocol. Existing
small inline worker callers remain compatible. Progress/error control messages
retain the existing limit.

The project itself is saved before the worker emits its final result. Open the
existing project with 0.3.0a22 before considering another detection run: the
completed reconstruction should already be in the .punctora file and its assets.
This fix does not change reconstruction or IFC classification algorithms.

Python tests cover transfers above 16 MiB, exact original-valued payloads,
identity mismatch, partial-file cleanup and inline compatibility. A native
WorkerClient check runs on Windows and Linux CI with a 20 MiB request and result,
checking exact IDs above 2^53, f64 precision, cancellation and cleanup.

The customer's screenshot names Intel UHD via hardware ANGLE/D3D11 and shows
66.8 FPS from movement diagnostics. Only the cloud is visible because the model
result was rejected. This is useful target-hardware evidence, but is not yet
acceptance of sustained movement with the reconstructed model and cloud visible.
