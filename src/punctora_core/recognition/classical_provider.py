"""Adapter for the existing detector, not a new learned semantic baseline."""
from copy import deepcopy
from dataclasses import asdict, replace
import numpy as np
from shapely.geometry import Point, Polygon

from .. import __version__
from ..annotation_io import content_digest
from ..evidence import face_selection
from ..quality_benchmark import model_snapshot
from ..reconstruction import ReconstructionSettings, reconstruct
from .contracts import TAXONOMY
from .provider import RecognitionProvider, TilePrediction


class ClassicalProvider(RecognitionProvider):
    def __init__(self, settings=None, model=None):
        self.settings = replace(settings or ReconstructionSettings(), compute_backend="cpu")
        self.model = model
        self.instances, self.warnings = [], []

    def descriptor(self):
        value = {"id": "classical", "version": __version__, "backend": "CPU",
                 "score_kind": "binary_original_surface_support", "settings": asdict(self.settings),
                 "supplied_model_sha256": content_digest(self.model.to_dict()) if self.model is not None else None,
                 "point_label_tolerance_m": .035, "adapter_version": 1}
        return {**value, "fingerprint": content_digest(value)}

    def prepare(self, cloud, identity, directory, control):
        from ..cloud_io import CloudData
        from ..cropping import crop_mask
        from ..storage import mapped_array
        control.check()
        owned = []
        try:
            if self.model is None:
                count = sum(int(crop_mask(cloud.points[b:b + control.chunk_points], identity["crop"]).sum())
                            for b in range(0, len(cloud.points), control.chunk_points))
                if count == 0:
                    raise ValueError("Recognition crop contains no original points")
                if count == len(cloud.points):
                    local = cloud
                else:
                    # Exact crop, mapped to avoid materialising the source cloud.
                    fields = {"points": ("<f8", (count, 3)), "scan_index": ("<u8", (count,)),
                              "source_record_index": ("<u8", (count,)), "working_index": ("<u8", (count,))}
                    arrays = {name: mapped_array(directory / (name + ".npy"), dtype, shape)
                              for name, (dtype, shape) in fields.items()}
                    owned.extend(arrays.values())
                    cursor = 0
                    for begin in range(0, len(cloud.points), control.chunk_points):
                        control.check()
                        keep = crop_mask(cloud.points[begin:begin + control.chunk_points], identity["crop"])
                        length = int(keep.sum())
                        for name, output in arrays.items():
                            original = getattr(cloud, name)
                            values = np.arange(begin, begin + len(keep), dtype="<u8") if original is None else original[begin:begin + len(keep)]
                            output[cursor:cursor + length] = values[keep]
                        cursor += length
                    local = CloudData(**arrays, metadata=deepcopy(cloud.metadata))
                settings = replace(self.settings, maximum_working_memory_gb=control.memory_limit_bytes / 1024**3,
                                   processing_chunk_points=control.chunk_points)
                # Existing detector retained intact; progress checks cancellation.
                model = reconstruct(local, settings, progress=lambda *_: control.check(),
                                    diagnostics=control.reconstruction_diagnostics)
            else:
                model = self.model
            self.snapshot = model_snapshot(model, identity)
            self.warnings = [*model.warnings,
                             "Classical semantic labels cover observed wall/surface support only; openings and inferred axes are not point-label truth"]
            self.instances = []
            source_ids = {e["id"]: "classical:" + content_digest({"source": identity["source_sha256"], "element": e})[:24]
                          for e in self.snapshot["elements"]}
            for element in self.snapshot["elements"]:
                shape = element["geometry"]
                if shape["type"] == "surface":
                    xy = np.asarray(shape["footprint"])
                    z1, z2 = shape.get("solid_base", shape["base"]), shape.get("solid_base", shape["base"]) + shape.get("thickness", 0.)
                else:
                    xy = np.asarray([shape["start"], shape["end"]])
                    z1 = shape["base"]
                    z2 = z1 + (shape["steps"] * shape["rise"] if shape["type"] == "stair" else shape["height"])
                extent = shape.get("thickness", shape.get("width", 0.)) / 2 if shape["type"] != "surface" else 0.
                item = {"id": source_ids[element["id"]], "class": element["class"], "status": "proposed",
                        "geometry": deepcopy(shape), "bounds_m": [[*(xy.min(axis=0) - extent), z1], [*(xy.max(axis=0) + extent), z2]],
                        "support_reference": "ProposalSet source arrays, independently revalidate before acceptance",
                        "provenance": deepcopy(element.get("provenance", {})), "support_state": element.get("support_state", "unknown"),
                        "native_score": None, "native_score_kind": "unavailable_for_geometry_instance",
                        "observed_faces": deepcopy(element.get("observed_faces", []))}
                if element.get("host_id") is not None:
                    item["host_id"] = source_ids[element["host_id"]]
                self.instances.append(item)
        finally:
            for value in owned:
                value._mmap.close()

    def infer_chunk(self, tile, directory, control):
        labels = np.full(len(tile.points), -1, dtype="<i2")
        scores = np.zeros(len(tile.points), dtype="<f4")
        # Lowest taxonomy ID wins overlapping classical support, independent of
        # source element order. Void/opening geometry cannot label actual points.
        for element in sorted(self.snapshot["elements"], key=lambda e: (TAXONOMY.index(e["class"]), e["id"])):
            control.check()
            selected = np.zeros(len(labels), dtype=bool)
            if element["class"] == "wall":
                for face in element.get("observed_faces", []):
                    selected |= face_selection(tile.points, face, .035, 0.)[0]
            elif element["geometry"]["type"] == "surface":
                geometry = element["geometry"]
                plane = geometry.get("plane", [0., 0., geometry["base"]])
                z = tile.points[:, 0] * plane[0] + tile.points[:, 1] * plane[1] + plane[2]
                candidates = np.flatnonzero(np.abs(tile.points[:, 2] - z) <= .035)
                polygon = Polygon(geometry["footprint"], geometry.get("holes", []))
                for row in candidates:
                    selected[row] = polygon.covers(Point(tile.points[row, :2]))
            selected &= labels < 0
            labels[selected], scores[selected] = TAXONOMY.index(element["class"]), 1.
        return TilePrediction(labels, scores)
