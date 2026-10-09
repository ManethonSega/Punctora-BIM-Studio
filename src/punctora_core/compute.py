"""Optional bounded GPU arithmetic with deterministic CPU fallback."""
import threading
import time
import numpy as np


class ComputeBackend:
    def __init__(self, preference="auto", memory_mb=256):
        self.name = "CPU"
        self.device = None
        self.memory_bytes = max(32, int(memory_mb)) * 1024**2
        self.fallbacks = []
        self.calls = 0
        self.seconds = 0.0
        self.peak_bytes = 0
        self._lock = threading.RLock()
        if preference in {"auto", "cuda"}:
            try:
                import open3d as o3d
                if not o3d.core.cuda.is_available():
                    raise RuntimeError("Open3D CUDA is unavailable")
                device = o3d.core.Device("CUDA:0")
                probe = o3d.core.Tensor([1.0], dtype=o3d.core.float64, device=device)
                probe.floor().cpu()
                self.o3d, self.device, self.name = o3d, device, "Open3D CUDA"
                return
            except Exception as exc:
                self.fallbacks.append(f"CUDA: {exc}")
                if preference == "cuda":
                    return
        if preference in {"auto", "opencl"}:
            try:
                import pyopencl as cl
                devices = [d for p in cl.get_platforms() for d in p.get_devices(cl.device_type.GPU)
                           if getattr(d, "double_fp_config", 0)]
                if not devices:
                    raise RuntimeError("No double-precision OpenCL GPU is available")
                device = max(devices, key=lambda d: d.global_mem_size)
                self.cl = cl
                self.context = cl.Context([device])
                self.queue = cl.CommandQueue(self.context, properties=cl.command_queue_properties.PROFILING_ENABLE)
                self.memory_bytes = min(self.memory_bytes, int(device.global_mem_size*.1),
                                        int(device.max_mem_alloc_size)*2)
                self.program = cl.Program(self.context, """
                    #pragma OPENCL EXTENSION cl_khr_fp64 : enable
                    __kernel void voxel(__global const double *p, __global long *out,
                                        double ox, double oy, double oz, double size) {
                        size_t i=get_global_id(0);
                        out[3*i]=(long)floor((p[3*i]-ox)/size+1e-9);
                        out[3*i+1]=(long)floor((p[3*i+1]-oy)/size+1e-9);
                        out[3*i+2]=(long)floor((p[3*i+2]-oz)/size+1e-9);
                    }
                """).build()
                self.kernel = cl.Kernel(self.program, "voxel")
                self.name, self.device = "OpenCL", device.name.strip()
            except Exception as exc:
                self.fallbacks.append(f"OpenCL: {exc}")

    def voxel_indices(self, points, origin, size):
        if not len(points):
            return np.empty((0, 3), dtype=np.int64)
        scaled = (points-origin)/size+1e-9
        if not np.isfinite(scaled).all() or np.max(np.abs(scaled)) > np.iinfo(np.int64).max/2:
            raise ValueError("Coordinate extent exceeds the voxel index limit")
        if self.name == "CPU":
            return np.floor(scaled).astype(np.int64)
        with self._lock:
            try:
                output = np.empty(points.shape, dtype=np.int64)
                chunk = max(1, self.memory_bytes//192)
                for begin in range(0, len(points), chunk):
                    part = np.ascontiguousarray(points[begin:begin+chunk], dtype=np.float64)
                    started = time.perf_counter()
                    if self.name == "Open3D CUDA":
                        o3d = self.o3d
                        tensor = o3d.core.Tensor(part, dtype=o3d.core.float64, device=self.device)
                        anchor = o3d.core.Tensor(origin, dtype=o3d.core.float64, device=self.device)
                        result = ((tensor-anchor)/size+1e-9).floor().to(o3d.core.int64).cpu().numpy()
                    else:
                        cl = self.cl
                        inp = cl.Buffer(self.context, cl.mem_flags.READ_ONLY|cl.mem_flags.COPY_HOST_PTR, hostbuf=part)
                        out = cl.Buffer(self.context, cl.mem_flags.WRITE_ONLY, part.nbytes)
                        event = self.kernel(self.queue, (len(part),), None, inp, out,
                                            *map(np.float64, origin), np.float64(size))
                        result = np.empty(part.shape, dtype=np.int64)
                        cl.enqueue_copy(self.queue, result, out, wait_for=[event]).wait()
                        inp.release(); out.release()
                    output[begin:begin+len(part)] = result
                    self.seconds += time.perf_counter()-started
                    self.calls += 1
                    self.peak_bytes = max(self.peak_bytes, len(part)*192)
                # Make boundary behaviour match NumPy exactly.
                output[np.abs(scaled-np.rint(scaled)) < 1e-7] = np.floor(scaled[np.abs(scaled-np.rint(scaled)) < 1e-7]).astype(np.int64)
                return output
            except Exception as exc:
                self.fallbacks.append(f"{self.name} failed, CPU retry: {exc}")
                self.name, self.device = "CPU", None
                return np.floor(scaled).astype(np.int64)

    def report(self):
        return {"backend": self.name, "device": str(self.device) if self.device is not None else None,
                "gpu_calls": self.calls, "gpu_transfer_and_compute_seconds": self.seconds,
                "gpu_peak_allocation_estimate_bytes": self.peak_bytes,
                "gpu_memory_budget_bytes": self.memory_bytes, "fallbacks": list(self.fallbacks),
                "scope": "bounded voxel indexing; fitting and topology remain CPU"}
