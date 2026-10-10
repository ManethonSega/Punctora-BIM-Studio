"""Shared CPU/RAM planning and process-wide stage telemetry."""
from contextlib import contextmanager
from dataclasses import dataclass
import os
import shutil
import subprocess
import threading
import time
try:
    import psutil
except ImportError:  # optional diagnostic enhancement; /proc/Windows fallbacks remain usable
    psutil = None
from .sampling import available_memory_bytes, resolved_cpu_workers


def _process():
    # Read our own procfs counters directly on Linux. Some hosted runtimes
    # virtualize psutil's process counters and report impossible sub-MB RSS.
    # Windows has no procfs and retains the native psutil implementation.
    if psutil is not None and not os.path.isfile("/proc/self/statm"):
        try:
            return psutil.Process()
        except psutil.Error:
            pass
    class Self:
        def memory_info(self):
            try:
                with open("/proc/self/statm", encoding="ascii") as stream:
                    rss = int(stream.read().split()[1])*os.sysconf("SC_PAGE_SIZE")
            except (OSError, IndexError, ValueError):
                rss = 0
            return type("Mem", (), {"rss": rss})()
        def cpu_times(self):
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return type("Cpu", (), {"user": usage.ru_utime, "system": usage.ru_stime})()
    return Self()


@dataclass
class ResourcePlan:
    workers: int
    concurrent_storeys: int
    workers_per_storey: int
    memory_bytes: int
    point_limit: int
    chunk_points: int
    available_at_start: int

    @classmethod
    def create(cls, settings, source_points, storeys=1):
        available = available_memory_bytes()
        baseline = _process().memory_info().rss
        source_reserve = int(source_points)*24
        memory = min(int(settings.maximum_working_memory_gb*1024**3)-baseline-source_reserve,
                     int(available*.60)-source_reserve)
        if memory < 64*1024**2:
            raise ValueError("Insufficient available RAM for reconstruction; close other applications")
        workers = resolved_cpu_workers(settings.cpu_workers)
        concurrent = min(max(1, int(storeys)), workers, max(1, memory//(256*1024**2)))
        workers_per_storey = max(1, workers//concurrent)
        bytes_per_point = 1024 if settings.surface_method == "region_growing" else 768
        per_storey_memory = max(64*1024**2, memory//concurrent)
        chunk_cap = max(100, per_storey_memory//max(1, workers_per_storey*768*4))
        chunk = max(100, min(settings.processing_chunk_points, int(chunk_cap)))
        # Leave room for the selected points after reserving the simultaneous
        # NumPy waves used by each worker.  This is a planning estimate, not an
        # allocation request, so the sampler still checks the actual inputs.
        spare = max(30*bytes_per_point,
                    per_storey_memory - workers_per_storey*chunk*768)
        point_limit = max(30, min(int(source_points), settings.maximum_detection_points,
                                  int(spare//bytes_per_point)))
        return cls(workers, concurrent, workers_per_storey, memory, point_limit, int(chunk), available)

    def report(self):
        return {**self.__dict__, "memory_scope": "shared working-set estimate, not an OS allocation guarantee"}


class StageProfiler:
    def __init__(self, backend):
        self.backend = backend
        self.process = _process()
        self.records = []
        self.nvidia = shutil.which("nvidia-smi")

    @contextmanager
    def stage(self, name, **details):
        record = {"stage": name, "sample_points": None, "detected_elements": {}, **details, "status": "running"}
        started = time.perf_counter()
        before = self.process.cpu_times()
        gpu_before = self.backend.report()
        samples = []
        stop = threading.Event()
        def sample():
            cpu_percent = psutil.cpu_percent(interval=None) if psutil is not None else None
            samples.append({"rss_bytes": self.process.memory_info().rss,
                            "system_cpu_percent": cpu_percent,
                            "available_memory_bytes": available_memory_bytes()})
        sample()
        def monitor():
            while not stop.wait(.25):
                sample()
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        try:
            yield record
            record["status"] = "complete"
        except BaseException as exc:
            record.update(status="failed", error=str(exc))
            raise
        finally:
            stop.set(); thread.join(); sample()
            after = self.process.cpu_times()
            seconds = time.perf_counter()-started
            cpu_seconds = after.user+after.system-before.user-before.system
            gpu_after = self.backend.report()
            record.update(seconds=seconds, process_cpu_seconds=cpu_seconds,
                          process_cpu_percent_of_machine=100*cpu_seconds/max(seconds, 1e-9)/max(1, os.cpu_count() or 1),
                          peak_process_rss_bytes=max(s["rss_bytes"] for s in samples),
                          minimum_available_memory_bytes=min(s["available_memory_bytes"] for s in samples),
                          system_cpu_percent_mean=(sum(s["system_cpu_percent"] for s in samples if s["system_cpu_percent"] is not None)
                                                   / max(1, sum(s["system_cpu_percent"] is not None for s in samples))),
                          gpu_calls=gpu_after["gpu_calls"]-gpu_before["gpu_calls"],
                          gpu_transfer_and_compute_seconds=gpu_after["gpu_transfer_and_compute_seconds"]-gpu_before["gpu_transfer_and_compute_seconds"],
                          gpu_device_utilization_percent=None, gpu_device_memory_used_bytes=None,
                          gpu_counter_status="Device counters unavailable on this host",
                          sampling_interval_seconds=.25,
                          resource_scope="process-wide; overlapping stages are not additive")
            if self.nvidia:
                try:
                    output = subprocess.run([self.nvidia, "--query-gpu=utilization.gpu,memory.used",
                                             "--format=csv,noheader,nounits"], capture_output=True,
                                             text=True, timeout=2, check=True).stdout
                    values = [list(map(float, line.split(","))) for line in output.strip().splitlines()]
                    record.update(gpu_device_utilization_percent=[v[0] for v in values],
                                  gpu_device_memory_used_bytes=[int(v[1]*1024**2) for v in values],
                                  gpu_counter_status="NVIDIA device-wide end-of-stage snapshot")
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
            self.records.append(record)

    def report(self):
        return {"stages": self.records, "compute": self.backend.report(),
                "peak_process_rss_bytes": max((r.get("peak_process_rss_bytes", 0) for r in self.records), default=0),
                "measurement_limits": "RSS sampled every 250 ms; CPU is process-wide; unavailable GPU counters are null"}
