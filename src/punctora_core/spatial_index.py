"""Lossless cell index: bounded sorted runs, unchanged f64 points and IDs."""
from collections import OrderedDict
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from weakref import ref
import numpy as np

CELL_DTYPE = np.dtype([("x", "<i8"), ("y", "<i8"), ("z", "<i8")])


class SpatialPointIndex:
    def __init__(self, cloud, cell, budget, chunk, scratch_directory=None):
        self.cloud, self.cell_size_m = cloud, float(cell)
        self.memory_budget_bytes = int(budget)
        self.chunk_points = max(1, min(int(chunk), budget // 256))
        self.runs, self.stats, self.visited = [], {}, {}
        self.lock = RLock()
        self.observers = {}
        self.mapped_arrays = []
        self.query_memory_limit = budget//4
        self.cache, self.cache_bytes = OrderedDict(), 0
        self.cache_limit = budget // 4
        self.scratch = TemporaryDirectory(prefix="punctora-spatial-",dir=scratch_directory)
        self.spilled = len(cloud.points)*96 > budget//2
        self.closed = False

    @classmethod
    def build(cls, cloud, cell_size_m=.25, memory_budget_bytes=None,
              chunk_points=100_000, progress=lambda *_: None, scratch_directory=None):
        from .sampling import available_memory_bytes
        if not np.isfinite(cell_size_m) or cell_size_m <= 0:
            raise ValueError("Spatial-index cell size must be positive and finite")
        budget = int(available_memory_bytes()*.70) if memory_budget_bytes is None else int(memory_budget_bytes)
        if budget < 4096:
            raise ValueError("Insufficient spatial-index working memory")
        index = cls(cloud,cell_size_m,budget,chunk_points,scratch_directory)
        try:
            for begin in range(0, len(cloud.points), index.chunk_points):
                p = cloud.points[begin:begin+index.chunk_points]
                coordinates = np.floor(p/cell_size_m)
                if np.any(coordinates < -(2**63)) or np.any(coordinates >= 2**63):
                    raise ValueError("Spatial cell coordinate exceeds int64 range")
                cells = np.empty(len(p), dtype=CELL_DTYPE)
                for axis, name in enumerate(CELL_DTYPE.names):
                    cells[name] = coordinates[:, axis].astype(np.int64)
                order = np.argsort(cells, kind="stable")
                unique, starts = np.unique(cells[order], return_index=True)
                rows = order.astype(np.int64)+begin
                index.runs.append(tuple(index._retain(a, f"run-{len(index.runs)}-{name}")
                                  for a, name in ((unique,"cells"),(starts,"starts"),(rows,"rows"))))
                progress(begin+len(p), len(cloud.points))
            return index
        except BaseException:
            index.close()
            raise

    def _retain(self, values, name):
        if not self.spilled:
            return values
        result = np.lib.format.open_memmap(Path(self.scratch.name)/f"{name}.npy",
                                          mode="w+", dtype=values.dtype, shape=values.shape)
        result[:] = values
        result.flush()
        return result

    @property
    def populated_cells(self):
        # A cell may occur in several run directories.
        return sum(len(run[0]) for run in self.runs)

    def rows_near_faces(self, faces, radius_m, endpoint_margin_m):
        """Conservative intersection with buffered finite faces, including height."""
        if self.closed:
            raise RuntimeError("Spatial index is closed")
        pieces, cell = [], self.cell_size_m
        for cells, starts, rows in self.runs:
            positions = []
            for face in faces:
                a, b = np.asarray(face["start"],float), np.asarray(face["end"],float)
                length = float(np.linalg.norm(b-a))
                if length <= 1e-12:
                    continue
                direction = (b-a)/length
                a, b = a-direction*endpoint_margin_m, b+direction*endpoint_margin_m
                lower = np.floor((np.minimum(a,b)-radius_m)/cell).astype(np.int64)
                upper = np.floor((np.maximum(a,b)+radius_m)/cell).astype(np.int64)
                left = np.searchsorted(cells["x"],lower[0],side="left")
                right = np.searchsorted(cells["x"],upper[0],side="right")
                selected = cells[left:right]
                mask = ((selected["y"]>=lower[1]) & (selected["y"]<=upper[1]) &
                        (selected["z"]>=np.floor(face["z_min"]/cell)) &
                        (selected["z"]<=np.floor(face["z_max"]/cell)))
                ids = np.flatnonzero(mask)
                if len(ids):
                    centres = np.column_stack((selected["x"][ids],selected["y"][ids]))*cell+cell/2
                    along = np.clip((centres-a)@direction,0,np.linalg.norm(b-a))
                    distances = np.linalg.norm(centres-a-along[:,None]*direction,axis=1)
                    ids = ids[distances<=radius_m+np.sqrt(2)*cell/2+1e-10]
                    positions.append(ids+left)
            if positions:
                for position in np.unique(np.concatenate(positions)):
                    end = starts[position+1] if position+1<len(starts) else len(rows)
                    pieces.append(rows[starts[position]:end])
        if not pieces:
            return np.empty(0,dtype=np.int64)
        count = sum(len(p) for p in pieces)
        result = self._allocate((count,),np.dtype("<i8"),count*8>self.query_memory_limit)
        cursor = 0
        for piece in pieces:
            result[cursor:cursor+len(piece)] = piece
            cursor += len(piece)
        result.sort(kind="quicksort")
        return result

    def _allocate(self, shape, dtype, mapped):
        if not mapped:
            return np.empty(shape,dtype=dtype)
        result = np.lib.format.open_memmap(Path(self.scratch.name)/f"query-{len(self.mapped_arrays)}.npy",
                                          mode="w+",dtype=dtype,shape=shape)
        # Do not keep evicted query maps resident merely to remember cleanup.
        self.mapped_arrays.append(ref(result))
        return result

    @staticmethod
    def _size(local, rows):
        return local.points.nbytes+rows.nbytes+sum(getattr(local,n).nbytes for n in
                  ("scan_index","source_record_index","working_index") if getattr(local,n) is not None)

    def local_cloud(self, faces, radius_m, endpoint_margin_m, stage=None):
        from .cloud_io import CloudData
        key = (tuple((tuple(f["start"]),tuple(f["end"]),f["z_min"],f["z_max"]) for f in faces),
               float(radius_m),float(endpoint_margin_m))
        with self.lock:
            cached = self.cache.get(key)
            if cached is not None:
                self.cache.move_to_end(key)
                local, rows = cached
            else:
                rows = self.rows_near_faces(faces,radius_m,endpoint_margin_m)
                if not len(rows):
                    return None, rows
                c = self.cloud
                row_bytes = 32+sum(getattr(c,n).dtype.itemsize for n in
                                  ("scan_index","source_record_index","working_index") if getattr(c,n) is not None)
                mapped = len(rows)*row_bytes>self.query_memory_limit
                def gather(source):
                    shape = (len(rows),)+source.shape[1:]
                    output = self._allocate(shape,source.dtype,mapped)
                    for begin in range(0,len(rows),self.chunk_points):
                        output[begin:begin+self.chunk_points] = source[rows[begin:begin+self.chunk_points]]
                    return output
                kwargs = {n:gather(getattr(c,n)) for n in ("scan_index","source_record_index","working_index")
                          if getattr(c,n) is not None}
                kwargs.setdefault("working_index",rows)
                local = CloudData(gather(c.points),metadata=c.metadata,**kwargs)
                size = self._size(local,rows)
                if size<=self.cache_limit:
                    while self.cache and self.cache_bytes+size>self.cache_limit:
                        _, old = self.cache.popitem(last=False)
                        self.cache_bytes -= self._size(*old)
                    self.cache[key] = (local,rows)
                    self.cache_bytes += size
            if stage:
                visited = self.visited.get(stage)
                if visited is None:
                    visited = np.memmap(Path(self.scratch.name)/f"visited-{len(self.visited)}.bin",mode="w+",
                                        dtype=np.bool_,shape=(len(self.cloud.points),))
                    self.visited[stage] = visited
                record = self.stats.setdefault(stage,{"points_processed":0,"unique_points_visited":0})
                for begin in range(0,len(rows),self.chunk_points):
                    ids = rows[begin:begin+self.chunk_points]
                    record["unique_points_visited"] += int(np.count_nonzero(~visited[ids]))
                    visited[ids] = True
                if cached is None:
                    record["points_processed"] += len(rows)  # original-record materialization
                if stage in self.observers:
                    self.observers[stage].update(self.report(stage))
            return local, rows

    def observe(self, stage, record):
        with self.lock:
            self.observers[stage] = record

    def visit(self, stage, count):
        with self.lock:
            self.stats.setdefault(stage,{"points_processed":0,"unique_points_visited":0})["points_processed"] += int(count)
            if stage in self.observers:
                self.observers[stage].update(self.report(stage))

    def report(self, stage):
        with self.lock:
            result = dict(self.stats.get(stage,{"points_processed":0,"unique_points_visited":0}))
        result.update(point_cloud_passes=result["points_processed"]/max(1,len(self.cloud.points)),
                      unique_source_points=len(self.cloud.points),
                      point_cloud_passes_scope="measured original-point visits / complete source cloud")
        return result

    def close(self):
        if getattr(self,"closed",True):
            return
        self.closed = True
        self.cache.clear()
        queries = [reference() for reference in self.mapped_arrays]
        for array in [a for run in self.runs for a in run]+list(self.visited.values())+queries:
            if isinstance(array,np.memmap):
                array._mmap.close()
        self.runs.clear()
        self.visited.clear()
        self.mapped_arrays.clear()
        self.scratch.cleanup()

    def __del__(self):
        self.close()
