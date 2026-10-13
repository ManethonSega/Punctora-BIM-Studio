"""Run 3: original-evidence projections and graph, no saved-model mutation."""
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import os
from pathlib import Path
import numpy as np

from ..annotation_io import content_digest, file_digest
from ..glazed_facades import projected_bay_groups
from ..planar_index import cluster_original_points
from ..quality_benchmark import write_report
from .contracts import TAXONOMY, ProviderUnavailable, array_descriptor, load_proposal_set, safe_artifact_path
from .element_graph import build_graph
from .instance_fusion import canonical_source_rows, column_instance, fuse_opening_candidates, projected_semantic_regions, region_evidence
from .provider import RecognitionProvider, TilePrediction
from .vision_provider import ProjectedEvidenceProvider, validate_detections
from .wall_projection import project_wall, wall_frames


@dataclass(frozen=True)
class HybridSettings:
    cell_m: float = .05
    face_band_m: float = .025
    depth_radius_m: float = .35
    maximum_projection_cells: int = 250000
    maximum_wall_context_points: int = 250000
    maximum_regions_per_view: int = 512
    minimum_class_points: int = 6
    minimum_opening_width_m: float = .5
    minimum_opening_height_m: float = .55
    minimum_edge_support: float = .65
    duplicate_iou: float = .7
    duplicate_boundary_m: float = .15
    column_radius_m: float = .25
    column_minimum_points: int = 6
    maximum_column_points: int = 250000
    maximum_cluster_neighbours: int = 2048

    def validate(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value) or value <= 0:
                raise ValueError("Hybrid settings must be finite positive numbers: " + name)
            if (name.startswith("maximum_") or name in {"minimum_class_points", "column_minimum_points"}) and not isinstance(value, int):
                raise ValueError("Hybrid count limits must be integers")
        if not 0 < self.minimum_edge_support <= 1 or not 0 < self.duplicate_iou <= 1 or self.face_band_m >= self.depth_radius_m:
            raise ValueError("Invalid hybrid support, overlap or depth band")
        return self


class HybridProvider(RecognitionProvider):
    """Reuse source labels unchanged, fuse instances using complementary evidence.

    Both 2D and 3D channels originate from the same scan and may be correlated.
    No combined probability is manufactured. The 2D worker is optional, while
    the classical frame/void path always runs independently.
    """
    def __init__(self, upstream_directory, vision=None, settings=None):
        self.upstream_directory = Path(upstream_directory).resolve()
        self.settings = (settings or HybridSettings()).validate()
        self.classical = ProjectedEvidenceProvider(self.settings.minimum_opening_width_m, self.settings.minimum_opening_height_m,
                                                   self.settings.minimum_edge_support, self.settings.maximum_regions_per_view)
        self.vision = vision
        self.instances, self.warnings, self.maps = [], [], {}
        self.channels = {}

    def bind_source(self, cloud, control):
        self.channels = {}
        for name in ("colors", "color_valid"):
            values = getattr(cloud, name)
            if values is None:
                self.channels[name] = None
                continue
            digest = hashlib.sha256()
            digest.update(content_digest({"shape": list(values.shape), "dtype": values.dtype.str}).encode())
            for begin in range(0, len(values), control.chunk_points):
                control.check()
                digest.update(np.ascontiguousarray(values[begin:begin + control.chunk_points]).tobytes())
            self.channels[name] = digest.hexdigest()

    def descriptor(self):
        upstream = load_proposal_set(self.upstream_directory, verify_arrays=False)
        value = {"id": "hybrid_instances", "version": "3", "backend": "CPU_original_geometry_plus_optional_isolated_vision",
                 "score_kind": "upstream_point_scores_and_separate_instance_evidence",
                 "upstream_proposal_sha256": upstream["proposal_sha256"], "upstream_cache_key": upstream["cache_key"],
                 "point_score_origin": deepcopy(upstream["provider"]), "settings": asdict(self.settings),
                 "source_channel_digests": self.channels,
                 "classical_2d": self.classical.descriptor(), "optional_2d": self.vision.descriptor() if self.vision else None}
        return {**value, "fingerprint": content_digest(value)}

    def prepare(self, cloud, identity, directory, control):
        self.upstream = load_proposal_set(self.upstream_directory, cancelled=control.cancelled)
        if self.upstream["identity"] != identity or self.upstream["input_digests"] != control.input_digests:
            raise ValueError("Hybrid input differs from upstream original points/IDs, crop or coordinate mapping")
        if "hybrid_v1" in self.upstream.get("extensions", {}):
            raise ValueError("Hybrid fusion requires the unfused Run 2 source, not repeated fusion of its own proposals")
        self.root = Path(directory) / "hybrid"
        self.root.mkdir()
        self.artifacts, self.frames, self.candidates, self.column_sources = [], [], [], []
        self.evidence = [{"id": "upstream:instances", "kind": "upstream_proposed_geometry",
                          "upstream_proposal_sha256": self.upstream["proposal_sha256"], "acceptance": "not_asserted"}]
        self.warnings = ["Hybrid instances remain review-only; host/profile validation and all IFC cuts wait for Run 4",
                         "2D and 3D evidence can be correlated; native scores are retained separately, never combined probabilities"]
        for name in ("labels", "scores"):
            self.maps[name] = np.load(safe_artifact_path(self.upstream_directory, self.upstream["arrays"][name]["path"]), mmap_mode="r", allow_pickle=False)
        self.vision_active = self.vision is not None
        self.stats = {"wall_views": 0, "opening_regions": 0, "both_face_duplicates_removed": 0,
                      "original_point_projection_visits": 0, "unsupported_2d_classes": {}, "unsupported_3d_classes": {},
                      "vision_requested": self.vision.descriptor() if self.vision else None, "vision_used": []}
        if self.vision:
            try:
                self.vision.prepare(directory, control)
            except ProviderUnavailable as exc:
                self.vision.close()
                self.vision_active = False
                self.warnings.append("Optional 2D unavailable, classical projected evidence retained: " + str(exc))

    def _save(self, name, value, role=None):
        relative = "hybrid/" + name + ".npy"
        path = self.root / (name + ".npy")
        np.save(path, value, allow_pickle=False)
        descriptor = array_descriptor(path, relative, value)
        if role: descriptor["role"] = role
        self.artifacts.append(descriptor)
        return relative

    def _view(self, projection):
        prefix = projection.frame.id.split(":")[1]
        paths = {name: self._save(prefix + "-" + name, getattr(projection, name), "source_rows" if name == "source_rows" else None)
                 for name in ("face_counts", "return_counts", "signed_depth_m", "rgb", "rgb_valid", "source_rows", "pixel_ids", "face_distances_m")}
        self.frames.append({"id": projection.frame.id, "frame": projection.frame.to_dict(), "arrays": paths})

    def _region(self, projection, region, provider_descriptor, cloud):
        mask_sha = hashlib.sha256(region["mask"].tobytes()).hexdigest()
        evidence_id = "region:" + content_digest({"frame": projection.frame.id, "provider": provider_descriptor["fingerprint"],
            "class": region["class"], "box": region["box"], "mask_sha256": mask_sha,
            "score": region.get("native_score"), "score_kind": region["score_kind"]})[:24]
        if any(e["id"] == evidence_id for e in self.evidence):
            return  # Exact duplicate output from one provider, same evidence.
        proof = region_evidence(projection, region, cloud, self.maps["labels"], self.maps["scores"],
                                self.settings.face_band_m, self.settings.minimum_class_points)
        prefix = evidence_id.split(":")[1]
        row_path = self._save(prefix + "-support", proof["support_rows"], "source_rows")
        interior_path = self._save(prefix + "-interior", proof["interior_rows"], "source_rows")
        frame_path = self._save(prefix + "-frame", proof["frame_rows"], "source_rows")
        mask_path = self._save(prefix + "-mask", region["mask"])
        self.evidence.append({"id": evidence_id, "kind": "projected_region_and_original_points", "frame_id": projection.frame.id,
            "class_reported": region["class"], "box": region["box"], "provider": provider_descriptor,
            "native_score": region.get("native_score"), "score_kind": region["score_kind"],
            "source_rows_path": row_path, "interior_rows_path": interior_path, "frame_rows_path": frame_path,
            "pixel_mask_path": mask_path, "void_only": proof["void_only"], "filling": "unknown",
            "source_support_count": len(proof["support_rows"]), "class_claims": proof["class_claims"],
            "semantic_counts": proof["semantic_counts"], "unknown_semantic_points": proof["unknown_points"],
            "unsupported_semantic_classes": proof["unsupported_semantic_classes"], "provider_evidence": deepcopy(region.get("evidence", {}))})
        if region["class"] in {"opening", "door", "window", "glazing"}:
            self.candidates.append({"id": evidence_id, "host_id": projection.frame.host_id, "frame": projection.frame,
                "bounds": projection.frame.local_bounds(region["box"]), "class_claims": proof["class_claims"],
                "void_only": proof["void_only"], "support_count": len(proof["support_rows"]),
                "kind": region.get("evidence", {}).get("method", "2d_detector")})
        elif region["class"] == "column":
            self.column_sources.append({"rows": proof["interior_rows"], "evidence_id": evidence_id, "host_id": projection.frame.host_id})
        else:
            counts = self.stats["unsupported_2d_classes"]
            counts[region["class"]] = counts.get(region["class"], 0) + 1

    def prepare_instances(self, cloud, identity, directory, control, spatial_index):
        options = self.settings
        estimate = (options.maximum_projection_cells * 256 + min(options.maximum_wall_context_points, len(cloud.points)) * 96
                    + min(options.maximum_column_points, len(cloud.points)) * 256)
        if estimate > control.working_budget // 2:
            raise ValueError("Hybrid projection/clustering limits exceed the shared recognition RAM budget")
        walls = {i["id"]: i for i in self.upstream["instances"] if i["class"] == "wall"}
        if not walls:
            self.warnings.append("No preliminary walls: wall projections unavailable; semantic column proposals can still be evaluated")
        for wall in sorted(walls.values(), key=lambda w: w["id"]):
            control.check()
            frames = wall_frames(wall, options.cell_m)
            faces = []
            for frame in frames:
                a = np.array(frame.origin_xy) + frame.normal_xy * frame.offset_m
                b = a + np.array(frame.along_xy) * frame.length_m
                faces.append({"start": a.tolist(), "end": b.tolist(), "z_min": frame.base_m, "z_max": frame.base_m + frame.height_m})
            rows = spatial_index.rows_near_faces(faces, options.depth_radius_m, .0)
            for frame in frames:
                control.check()
                projection = project_wall(cloud, rows, frame, identity["crop"], face_band_m=options.face_band_m,
                    depth_radius_m=options.depth_radius_m, maximum_cells=options.maximum_projection_cells,
                    maximum_context_points=options.maximum_wall_context_points, chunk_points=control.chunk_points, check=control.check)
                self._view(projection)
                self.stats["wall_views"] += 1
                self.stats["original_point_projection_visits"] += len(rows)
                classical = self.classical.infer(projection, directory, control)
                regions = [(r, self.classical.descriptor()) for r in classical]
                semantic_provider = {"id": "original_semantic_projection", "version": "1", "backend": "CPU",
                    "score_kind": self.upstream["provider"]["score_kind"], "upstream_proposal_sha256": self.upstream["proposal_sha256"]}
                semantic_provider["fingerprint"] = content_digest(semantic_provider)
                semantic_regions = projected_semantic_regions(projection, self.maps["labels"], self.maps["scores"], classical,
                    options.minimum_class_points, options.maximum_regions_per_view, control.check)
                regions.extend((r, semantic_provider) for r in validate_detections(semantic_regions, projection, options.maximum_regions_per_view))
                if self.vision_active:
                    try:
                        extra = validate_detections(self.vision.infer(projection, directory, control), projection, options.maximum_regions_per_view)
                        regions.extend((r, self.vision.descriptor()) for r in extra)
                        if self.vision.descriptor() not in self.stats["vision_used"]:
                            self.stats["vision_used"].append(self.vision.descriptor())
                    except ProviderUnavailable as exc:
                        self.vision.close()
                        self.vision_active = False
                        self.warnings.append("Optional 2D unavailable on a view, classical evidence retained: " + str(exc))
                for region, provider in regions:
                    control.check()
                    self._region(projection, region, provider, cloud)
                # Keep prior geometry as an additional proposal, never as an
                # accepted opening. Back-project its actual source returns.
                for old in self.upstream["instances"]:
                    if old.get("host_id") != wall["id"] or old["class"] not in {"opening", "door", "window"}:
                        continue
                    g = old["geometry"]
                    local = frame.local(np.array([[*g["start"], g["base"]], [*g["end"], g["base"] + g["height"]]]))
                    low, high = local[:, :2].min(axis=0), local[:, :2].max(axis=0)
                    low = np.maximum(0, np.floor(low / frame.cell_m).astype(int))
                    high = np.minimum(np.array(frame.shape[::-1]), np.ceil(high / frame.cell_m).astype(int))
                    if np.all(high > low):
                        value = {"class": "opening", "box": [int(low[0]), int(low[1]), int(high[0]), int(high[1])],
                                 "native_score": None, "score_kind": "upstream_geometry_no_class_authority", "evidence": {"method": "upstream_opening_geometry", "source_instance_id": old["id"]}}
                        self._region(projection, validate_detections([value], projection)[0], self.upstream["provider"], cloud)
                del projection
            if isinstance(rows, np.memmap):
                rows._mmap.close()
        pieces = []
        for begin in range(0, len(cloud.points), control.chunk_points):
            control.check()
            values = self.maps["labels"][begin:begin + control.chunk_points]
            selected = np.flatnonzero(values == TAXONOMY.index("column")) + begin
            pieces.append(selected.astype("<u8"))
            if sum(len(p) for p in pieces) > options.maximum_column_points:
                raise ValueError("Semantic columns exceed the explicit original-point limit")
            for label in np.unique(values[values >= 12]):
                kind = TAXONOMY[int(label)]
                counts = self.stats["unsupported_3d_classes"]
                counts[kind] = counts.get(kind, 0) + int((values == label).sum())
        semantic_rows = canonical_source_rows(np.concatenate(pieces), cloud)
        if len(semantic_rows):
            identifier = "semantic:column"
            path = self._save("semantic-column-rows", semantic_rows, "source_rows")
            self.evidence.append({"id": identifier, "kind": "original_semantic_column_points", "source_rows_path": path,
                                  "source_support_count": len(semantic_rows), "score_kind": self.upstream["provider"]["score_kind"]})
            self.column_sources.append({"rows": semantic_rows, "evidence_id": identifier, "host_id": None})
        columns = []
        if self.column_sources:
            if sum(len(s["rows"]) for s in self.column_sources) > 4 * options.maximum_column_points:
                raise ValueError("Repeated column evidence exceeds the explicit aggregate support limit")
            selected = canonical_source_rows(np.concatenate([s["rows"] for s in self.column_sources]), cloud)
            clusters = cluster_original_points(cloud.points[selected], cloud.scan_index[selected], cloud.source_record_index[selected],
                options.column_radius_m, options.column_minimum_points, options.maximum_column_points,
                options.maximum_cluster_neighbours, control.check)
            for cluster in clusters:
                control.check()
                support = selected[cluster]
                linked = [s for s in self.column_sources if np.intersect1d(support, s["rows"]).size]
                candidate = column_instance(support, cloud, identity["source_sha256"], linked[0]["evidence_id"],
                                            next((s["host_id"] for s in linked if s["host_id"]), None))
                if candidate:
                    values = self.maps["labels"][support]
                    conflicting = [kind for kind in ("door", "window") if int((values == TAXONOMY.index(kind)).sum()) >= options.minimum_class_points]
                    candidate["class_claims"] = [{"class": "column", "basis": "projected_or_semantic_column_hypothesis"},
                                                  *[{"class": kind, "basis": "conflicting_original_semantic_labels"} for kind in conflicting]]
                    if conflicting: candidate["classification_state"] = "conflicting"
                    candidate["evidence_ids"] = sorted(s["evidence_id"] for s in linked)
                    path = self._save(candidate["id"].split(":")[-1] + "-column-support", canonical_source_rows(support, cloud), "source_rows")
                    proof_id = "component:" + candidate["id"].split(":")[-1]
                    self.evidence.append({"id": proof_id, "kind": "original_column_component", "source_rows_path": path,
                                          "source_support_count": len(support), "clustering": "deterministic_original_id_dbscan"})
                    candidate["evidence_ids"].append(proof_id)
                    columns.append(candidate)
        openings = fuse_opening_candidates(self.candidates, walls, identity["source_sha256"], options.duplicate_iou, options.duplicate_boundary_m)
        self.stats["opening_regions"] = len(self.candidates)
        self.stats["both_face_duplicates_removed"] = len(self.candidates) - len(openings)
        self.instances = [deepcopy(i) for i in self.upstream["instances"] if i["class"] not in {"opening", "door", "window"}]
        self.instances.extend([*openings, *columns])
        for item in self.instances:
            if "evidence_ids" not in item: item["evidence_ids"] = ["upstream:instances"]
        groups = projected_bay_groups(openings)
        graph = build_graph(identity, self.upstream["proposal_sha256"], self.instances, self.evidence, groups)
        write_report(self.root / "element-graph-v1.json", graph)
        self.artifacts.append({"path": "hybrid/element-graph-v1.json", "sha256": file_digest(self.root / "element-graph-v1.json")})
        write_report(self.root / "projections-v1.json", {"schema_version": 1, "identity": identity, "views": self.frames})
        self.artifacts.append({"path": "hybrid/projections-v1.json", "sha256": file_digest(self.root / "projections-v1.json")})

    def infer_chunk(self, tile, directory, control):
        control.check()
        return TilePrediction(np.asarray(self.maps["labels"][tile.context_rows], dtype="<i2"),
                              np.asarray(self.maps["scores"][tile.context_rows], dtype="<f4"))

    def write_artifacts(self, directory, control):
        control.check()
        os.rename(self.root, Path(directory) / "hybrid")
        return {"hybrid_v1": {"schema_version": 1, "upstream_proposal_sha256": self.upstream["proposal_sha256"],
                 "cut_policy": "no_cuts_before_run4_host_validation", "graph_path": "hybrid/element-graph-v1.json",
                 "projection_manifest_path": "hybrid/projections-v1.json", "artifacts": self.artifacts,
                 "diagnostics": self.stats}}

    def close(self):
        if self.vision: self.vision.close()
        for value in self.maps.values(): value._mmap.close()
        self.maps = {}
