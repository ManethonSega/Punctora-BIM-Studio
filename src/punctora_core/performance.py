"""Shared CPU/RAM planning and process-wide stage telemetry."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
try:
    import psutil
except ImportError:  # optional diagnostic enhancement; /proc/Windows fallbacks remain usable
    psutil = None
from .sampling import available_memory_bytes, resolved_cpu_workers


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


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
    baseline_process_rss_bytes: int
    source_cloud_bytes_estimate: int
    available_memory_fraction_limit: float

    @classmethod
    def create(cls, settings, source_points, storeys=1):
        available = available_memory_bytes()
        baseline = _process().memory_info().rss
        source_reserve = int(source_points)*24
        # Zero means automatic. The process may use at most 70% of the memory
        # that was available when planning began; the remaining 30% protects
        # the desktop, OS and other applications. A non-zero user ceiling can
        # only lower that automatic budget.
        automatic = int(available*.70)
        policy = (automatic if settings.maximum_working_memory_gb == 0 else
                  min(automatic, int(settings.maximum_working_memory_gb*1024**3)))
        memory = policy-baseline-source_reserve
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
        return cls(workers, concurrent, workers_per_storey, memory, point_limit, int(chunk), available,
                   baseline, source_reserve, .70)

    def report(self):
        return {**self.__dict__,
                "temporary_parallel_wave_bytes_estimate": self.concurrent_storeys*self.workers_per_storey*self.chunk_points*768,
                "memory_scope": "shared working-set ceiling, not an OS allocation request or guarantee"}


class StageProfiler:
    """Live, cancellation-surviving reconstruction telemetry.

    The optional diagnostics callback receives an atomic snapshot at run start,
    stage boundaries and every heartbeat interval. The desktop writes those
    snapshots outside the disposable generation directory, so terminating the
    worker cannot erase the latest completed heartbeat.
    """
    def __init__(self, backend, diagnostics=None, context=None, heartbeat_seconds=5.0):
        self.backend = backend
        self.process = _process()
        self.records = []
        self.nvidia = shutil.which("nvidia-smi")
        self.diagnostics = diagnostics
        self.context = dict(context or {})
        self.heartbeat_seconds = max(1., float(heartbeat_seconds))
        self.started = time.perf_counter()
        self.started_at = _utc_now()
        self.updated_at = self.started_at
        self.status = "running"
        self.resource_plan = None
        self.events = [{"event": "job_started", "at": self.started_at}]
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._next_stage_instance = 1
        self._emit()

    def set_resource_plan(self, plan):
        with self._lock:
            self.resource_plan = deepcopy(plan)
            self.events.append({"event": "resource_plan_created", "at": _utc_now()})
        self._emit()

    def _thread_count(self):
        if psutil is not None:
            try:
                return self.process.num_threads()
            except (AttributeError, psutil.Error):
                pass
        try:
            return len(os.listdir("/proc/self/task"))
        except OSError:
            return None

    def _io_counters(self):
        if psutil is not None:
            try:
                value = self.process.io_counters()
                return {"read_bytes": int(value.read_bytes), "write_bytes": int(value.write_bytes)}
            except (AttributeError, psutil.Error):
                pass
        return None

    def _snapshot_unlocked(self):
        active = [r["stage"] for r in self.records if r.get("status") == "running"]
        compute = self.backend.report()
        return {"schema_version": 2, **deepcopy(self.context), "status": self.status,
                "started_at_utc": self.started_at, "updated_at_utc": self.updated_at,
                "elapsed_seconds": time.perf_counter()-self.started,
                "active_stages": active, "heartbeat_seconds": self.heartbeat_seconds,
                "resource_plan": deepcopy(self.resource_plan),
                "stages": deepcopy(self.records), "events": deepcopy(self.events),
                "point_cloud_passes_total": sum(r.get("point_cloud_passes") or 0 for r in self.records),
                "points_processed_total": sum(r.get("points_processed") or 0 for r in self.records),
                "compute": compute,
                "gpu_backend_activated": compute["backend"] != "CPU" and compute["gpu_calls"] > 0,
                "peak_process_rss_bytes": max((r.get("peak_process_rss_bytes", 0) for r in self.records), default=0),
                "host": {"platform": platform.platform(), "python": sys.version.split()[0],
                         "logical_cpu_count": os.cpu_count()},
                "measurement_limits": ("RSS and process threads are sampled; process CPU time is summed across threads. "
                                       "Blocked I/O wait is not exposed portably and is not fabricated. GPU activity "
                                       "describes Punctora compute calls; NVIDIA device counters are supplemental.")}

    def _emit(self):
        if self.diagnostics is None:
            return
        # Multiple storey stage monitors can finish together. Serialize writes
        # and take the snapshot after acquiring the write lock so an older
        # temporary snapshot cannot replace a newer state.
        with self._write_lock:
            with self._lock:
                self.updated_at = _utc_now()
                snapshot = self._snapshot_unlocked()
            self.diagnostics(snapshot)

    def finish(self, status, error=None):
        with self._lock:
            if self.status != "running":
                return
            self.status = status
            event = {"event": f"job_{status}", "at": _utc_now()}
            if error:
                event["error"] = str(error)
            self.events.append(event)
        self._emit()

    @contextmanager
    def stage(self, name, **details):
        with self._lock:
            stage_instance = self._next_stage_instance
            self._next_stage_instance += 1
        record = {"stage": name, "stage_instance": stage_instance,
                  "started_at_utc": _utc_now(), "sample_points": None,
                  "detected_elements": {}, **details, "status": "running"}
        started = time.perf_counter()
        before = self.process.cpu_times()
        io_before = self._io_counters()
        gpu_before = self.backend.report()
        samples = []
        stop = threading.Event()
        def sample():
            cpu_percent = psutil.cpu_percent(interval=None) if psutil is not None else None
            current = {"rss_bytes": self.process.memory_info().rss,
                            "process_threads": self._thread_count(),
                            "system_cpu_percent": cpu_percent,
                            "available_memory_bytes": available_memory_bytes()}
            samples.append(current)
            record.update(elapsed_seconds=time.perf_counter()-started,
                          current_process_rss_bytes=current["rss_bytes"],
                          current_process_threads=current["process_threads"],
                          current_available_memory_bytes=current["available_memory_bytes"])
        sample()
        with self._lock:
            self.records.append(record)
            self.events.append({"event": "stage_started", "stage": name,
                                "stage_instance": record["stage_instance"], "at": record["started_at_utc"]})
        self._emit()
        def monitor():
            next_heartbeat = time.perf_counter()+self.heartbeat_seconds
            while not stop.wait(.25):
                with self._lock:
                    sample()
                if time.perf_counter() >= next_heartbeat:
                    self._emit()
                    next_heartbeat = time.perf_counter()+self.heartbeat_seconds
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
            io_after = self._io_counters()
            processed = record.get("points_processed") or record.get("sample_points")
            io_delta = ({key: max(0, io_after[key]-io_before[key]) for key in io_after}
                        if io_before is not None and io_after is not None else None)
            record.update(seconds=seconds, process_cpu_seconds=cpu_seconds,
                          non_cpu_wall_seconds_single_core_equivalent=max(0., seconds-cpu_seconds),
                          cpu_capacity_seconds=seconds*max(1, os.cpu_count() or 1),
                          unused_cpu_capacity_seconds=max(0., seconds*max(1, os.cpu_count() or 1)-cpu_seconds),
                          blocked_wait_seconds=None,
                          cpu_wait_scope=("Direct blocked-wait time is unavailable portably. The single-core-equivalent "
                                          "gap is informative for serial stages only; unused capacity is not proof of I/O wait."),
                          process_cpu_percent_of_machine=100*cpu_seconds/max(seconds, 1e-9)/max(1, os.cpu_count() or 1),
                          peak_process_rss_bytes=max(s["rss_bytes"] for s in samples),
                          peak_process_threads=max((s["process_threads"] or 0 for s in samples), default=0),
                          peak_rss_increase_bytes=max(0, max(s["rss_bytes"] for s in samples)-samples[0]["rss_bytes"]),
                          minimum_available_memory_bytes=min(s["available_memory_bytes"] for s in samples),
                          system_cpu_percent_mean=(sum(s["system_cpu_percent"] for s in samples if s["system_cpu_percent"] is not None)
                                                   / max(1, sum(s["system_cpu_percent"] is not None for s in samples))),
                          gpu_calls=gpu_after["gpu_calls"]-gpu_before["gpu_calls"],
                          gpu_transfer_and_compute_seconds=gpu_after["gpu_transfer_and_compute_seconds"]-gpu_before["gpu_transfer_and_compute_seconds"],
                          gpu_device_utilization_percent=None, gpu_device_memory_used_bytes=None,
                          gpu_counter_status="Device counters unavailable on this host",
                          io_bytes=io_delta,
                          points_per_second=(None if processed is None else float(processed)/max(seconds, 1e-9)),
                          completed_at_utc=_utc_now(),
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
            with self._lock:
                self.events.append({"event": "stage_finished", "stage": name,
                                    "stage_instance": record["stage_instance"],
                                    "status": record["status"], "at": record["completed_at_utc"]})
            self._emit()

    def report(self):
        with self._lock:
            return self._snapshot_unlocked()
