"""Atomic desktop projects, bounded previews and immutable source generations."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid
from datetime import datetime, timezone

import numpy as np

from .cloud_io import CloudData
from .cropping import EMPTY_CROP, crop_active, materialize_crop, validate_crop
from .e57_io import read_e57
from .evidence import write_model_evidence
from .fixtures import demo_cloud
from .ifc_export import write_ifc
from .model import BuildingModel, Landing, Opening, SlabOpening, Stair, slab_opening_is_validated
from .convergence import compare_budgets
from .reconstruction import ReconstructionSettings, reconstruct
from .sampling import release_completed_working_memory
from .level_bounds import validate_detection_options
from dataclasses import replace
from .wall_editing import merge_walls, split_wall

# The preview is a display-only sample. 500k points remains small compared with
# the immutable working cloud (12 MB on disk, 14 MB in the GPU vertex buffer)
# while giving large surveys enough visual density for element review.
PREVIEW_LIMIT = 500_000
PREVIEW_CANDIDATE_MULTIPLIER = 4
PREVIEW_GRID_BINS = 1024


def _mix64(values):
    """Deterministic vectorised SplitMix64, used only to thin display samples."""
    values = np.asarray(values, dtype=np.uint64).copy()
    with np.errstate(over="ignore"):
        values += np.uint64(0x9E3779B97F4A7C15)
        values = (values ^ (values >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        values = (values ^ (values >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return values ^ (values >> np.uint64(31))


def spatial_preview_indices(points, limit=PREVIEW_LIMIT):
    """Choose a repeatable, spatially balanced display-only subset.

    At most four preview budgets are read from evenly distributed source rows.
    One representative from each occupied 3D display cell is preferred before
    remaining capacity is filled. This prevents source-record order from making
    one scan station dominate the viewport without scanning or sorting the full
    source cloud in memory.
    """
    count = len(points)
    if count <= limit:
        return np.arange(count, dtype=np.int64)
    candidate_count = min(count, limit * PREVIEW_CANDIDATE_MULTIPLIER)
    positions = np.arange(candidate_count, dtype=np.uint64)
    ids = (positions * np.uint64(count - 1) // np.uint64(candidate_count - 1)).astype(np.int64)
    sample = np.asarray(points[ids], dtype=np.float64)
    minimum = np.min(sample, axis=0)
    span = np.max(sample, axis=0) - minimum
    keys = np.zeros(candidate_count, dtype=np.uint64)
    for axis, shift in enumerate((0, 10, 20)):
        if span[axis] > 0:
            cells = np.floor((sample[:, axis] - minimum[axis]) / span[axis]
                             * (PREVIEW_GRID_BINS - 1)).astype(np.uint64)
            keys |= np.minimum(cells, PREVIEW_GRID_BINS - 1) << np.uint64(shift)
    unique_keys, first = np.unique(keys, return_index=True)
    if len(first) >= limit:
        scores = _mix64(unique_keys)
        chosen = first[np.argpartition(scores, limit - 1)[:limit]]
    else:
        selected = np.zeros(candidate_count, dtype=bool)
        selected[first] = True
        remaining = np.flatnonzero(~selected)
        needed = limit - len(first)
        scores = _mix64(ids[remaining].astype(np.uint64) ^ keys[remaining])
        fill = remaining[np.argpartition(scores, needed - 1)[:needed]]
        chosen = np.concatenate((first, fill))
    return np.sort(ids[chosen])


def read_json(path):
    def invalid(value):
        raise ValueError(f"Nonfinite JSON value: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=invalid)


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, allow_nan=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _performance_writer(path, job_id, command):
    """Persist both the latest trace and an immutable-name trace for this job."""
    root = assets_for(path)
    history = root / "diagnostics" / f"{command}-{job_id}.json"
    latest = root / "last-performance.json"
    started = time.perf_counter()
    started_utc = datetime.now(timezone.utc).isoformat()
    def write(report, final=False):
        value = {**report, "job_id": job_id, "command": command,
                 "diagnostic_file": str(history.name)}
        if command == 'reconstruct':
            value['geometry_and_evidence_seconds'] = report.get('geometry_and_evidence_seconds',report.get('total_seconds',0.))
            elapsed = time.perf_counter()-started
            value.update(total_seconds=elapsed,elapsed_seconds=elapsed,
                started_at_utc=started_utc,updated_at_utc=datetime.now(timezone.utc).isoformat(),
                runtime_scope='complete desktop operation: crop, reconstruction, recognition, validation, evidence and publication')
            value['point_counter_scope']='stage counters cover reconstruction/evidence; specialist model/normal/raster visits are reported separately'
            if not final and value.get('status') not in {'failed','cancelled'}:
                value['status']='running'
            elif final:
                value['status']='completed'
        atomic_json(history, value)
        atomic_json(latest, value)
        return value
    return write, history


def _initial_performance(job_id, command, **details):
    now = datetime.now(timezone.utc).isoformat()
    return {"schema_version": 2, "job_id": job_id, "command": command,
            "status": "running", "started_at_utc": now, "updated_at_utc": now,
            "active_stages": [], "stages": [],
            "events": [{"event": "job_started", "at": now}], **details}


def mark_performance_cancelled(path, job_id):
    """Mark the last durable heartbeat after the desktop terminates a worker."""
    uuid.UUID(hex=job_id)
    root = assets_for(project_path(path))
    matches = list((root / "diagnostics").glob(f"*-{job_id}.json")) if (root / "diagnostics").is_dir() else []
    if not matches:
        return {"updated": False}
    report = read_json(matches[0])
    now = datetime.now(timezone.utc).isoformat()
    report.update(status="cancelled", updated_at_utc=now)
    report.setdefault("events", []).append({"event": "job_cancelled", "at": now,
                                              "scope": "recorded by desktop after worker termination"})
    atomic_json(matches[0], report)
    atomic_json(root / "last-performance.json", report)
    # The terminated worker cannot run TemporaryDirectory's finalizer. Remove
    # only its unpublished index workspaces, never source or published data.
    temporary = safe_path(root,f"staging/{job_id}")
    if temporary.is_dir():
        for directory in temporary.glob("punctora-spatial-*"):
            if directory.is_dir() and not directory.is_symlink():
                shutil.rmtree(safe_path(root,str(directory.relative_to(root))))
    return {"updated": True, "diagnostic": str(matches[0])}


def safe_path(root, relative):
    root = Path(root).resolve()
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("A project-relative data path is required")
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("Data path escapes its project directory")
    return target


def project_path(path):
    path = Path(path).resolve()
    if path.suffix.lower() != ".punctora":
        raise ValueError("Choose a .punctora project file")
    return path


def assets_for(path):
    path = project_path(path)
    return path.parent / (path.stem + ".assets")


@contextmanager
def project_lock(path):
    """OS locks release on cancellation/process death, on Windows and POSIX."""
    path = project_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".punctora.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Another job is using this project") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def ensure_assets(path, project_id):
    root = assets_for(path)
    marker = root / "owner.json"
    if root.exists():
        if not marker.is_file() or read_json(marker).get("project_id") != project_id:
            raise ValueError("The project data folder belongs to another project")
    else:
        root.mkdir(parents=True)
        atomic_json(marker, {"project_id": project_id})
    return root


def load_project(path):
    path = project_path(path)
    state = read_json(path)
    if state.get("schema_version") != 1 or state.get("assets_directory") != assets_for(path).name:
        raise ValueError("Unsupported project schema or data folder")
    state["crop"] = validate_crop(state.get("crop"))
    state['reconstruction_options']=validate_detection_options(state.get('reconstruction_options'))
    state["model_crop"] = validate_crop(state.get("model_crop"))
    if not isinstance(state.get("model_crop_stale", False), bool):
        raise ValueError("Invalid crop/model state")
    state["model_crop_stale"] = model_input_stale(state)
    uuid.UUID(hex=state["project_id"])
    uuid.UUID(hex=state["revision"])
    root = assets_for(path)
    if not root.is_dir():
        raise ValueError("Project data is missing; keep the project file and assets folder together")
    ensure_assets(path, state["project_id"])
    if state.get("model") is not None:
        model = BuildingModel.from_dict(state["model"])
        if model.metadata.get("project_id") != state["project_id"]:
            raise ValueError("Model identity differs from its project")
        # Rebuild derived preview meshes, including older projects without them.
        # This is an in-memory refresh, not a save or revision change.
        state["model"] = json.loads(json.dumps(model.to_dict()))
    for generation in state["generations"]:
        uuid.UUID(hex=generation)
        if not safe_path(root, f"generations/{generation}").is_dir():
            raise ValueError("Project data is incomplete; keep the project file and assets folder together")
    preview = state["preview"]
    if (preview.get("format") != "xyzrgb-f32-le" or not isinstance(preview["point_count"], int)
            or not 0 < preview["point_count"] <= PREVIEW_LIMIT):
        raise ValueError("Unsupported preview format or point count")
    if safe_path(root, preview["path"]).stat().st_size != preview["point_count"] * 24:
        raise ValueError("Preview data length differs from its manifest")
    for wall in (state.get("model") or {}).get("walls", []):
        records = wall.get("evidence", {}).get("records")
        if records and not safe_path(root, records["path"]).is_file():
            raise ValueError("Wall evidence data is missing")
    recognition = state.get("recognition")
    if recognition is not None:
        if (not isinstance(recognition, dict) or recognition.get("schema_version") != 1
                or recognition.get("requested_mode") not in {"classical", "specialist", "hybrid"}
                or not isinstance(recognition.get("overlay_proposals"), list)
                or len(recognition["overlay_proposals"]) > 5000):
            raise ValueError("Invalid desktop recognition state")
        proposal_path = recognition.get("proposal_manifest")
        if proposal_path is None and recognition["overlay_proposals"]:
            raise ValueError("Recognition overlays require a published ProposalSet")
        if proposal_path is not None:
            proposal_path = safe_path(root, proposal_path)
            if proposal_path.name != "proposals-v1.json" or not proposal_path.is_file():
                raise ValueError("Recognition ProposalSet is missing")
            from .recognition.contracts import load_proposal_set
            load_proposal_set(proposal_path.parent, verify_arrays=False)
        for proposal in recognition["overlay_proposals"]:
            polygon = np.asarray(proposal.get("polygon_xy_m", []), dtype=np.float64)
            z = np.asarray([proposal.get("z_min_m"), proposal.get("z_max_m")], dtype=np.float64)
            if (proposal.get("status") != "proposed"
                    or proposal.get("geometry_authority") != "review_only"
                    or proposal.get("class") not in {"wall", "opening", "window", "door", "beam", "column", "stair", "slab", "ceiling", "roof"}
                    or polygon.ndim != 2 or polygon.shape[1:] != (2,) or len(polygon) < 3
                    or not np.isfinite(polygon).all() or not np.isfinite(z).all() or z[1] <= z[0]):
                raise ValueError("Malformed review-only specialist overlay")
    return state


def check_revision(state, expected):
    if expected != state["revision"]:
        raise ValueError("Project changed since it was opened; reopen before saving")


def load_cloud(path, state):
    root = assets_for(path)
    ref = state["cloud"]
    directory = safe_path(root, f"generations/{ref['generation']}")
    if ref["kind"] == "fixture":
        return CloudData(np.load(directory / "points.npy", mmap_mode="r", allow_pickle=False))
    manifest = state["import_manifest"]
    arrays = {}
    allowed = {"points": ("<f8", [manifest["valid_point_count"], 3]),
               "colors": ("<f8", [manifest["valid_point_count"], 3]),
               "intensity": ("<f8", [manifest["valid_point_count"], 1]),
               "scan_index": ("<u4", [manifest["valid_point_count"]]),
               "source_record_index": ("<u8", [manifest["valid_point_count"]]),
               "color_valid": ("|b1", [manifest["valid_point_count"]]),
               "intensity_valid": ("|b1", [manifest["valid_point_count"]])}
    for name, descriptor in manifest["cache"]["files"].items():
        if name not in allowed or (descriptor["dtype"], descriptor["shape"]) != allowed[name]:
            raise ValueError("Unsupported working-cloud channel descriptor")
        stored = safe_path(directory / "working-cache", descriptor["path"])
        dtype = np.dtype(descriptor["dtype"])
        if stored.stat().st_size != int(np.prod(descriptor["shape"])) * dtype.itemsize:
            raise ValueError("Working-cloud channel is truncated")
        arrays[name] = np.memmap(stored, mode="r", dtype=dtype, shape=tuple(descriptor["shape"]))
    return CloudData(**arrays, metadata={"coordinate_frame": "E57-derived local metres",
                     "coordinate_mapping": manifest["coordinate_mapping"]})


def write_preview(cloud, directory, generation, working_bounds=None):
    count = min(PREVIEW_LIMIT, len(cloud.points))
    ids = spatial_preview_indices(cloud.points, count)
    preview = np.empty((count, 6), dtype="<f4")
    preview[:, :3] = cloud.points[ids]
    preview[:, 3:] = [.45, .65, .72]
    if cloud.colors is not None:
        color = cloud.colors[ids]
        maximum = float(np.max(color))
        scale = 1 if maximum <= 1 else 255 if maximum <= 255 else 65535 if maximum <= 65535 else maximum
        valid = cloud.color_valid[ids] if cloud.color_valid is not None else np.ones(count, dtype=bool)
        preview[valid, 3:] = np.clip(color[valid] / scale, 0, 1)
    preview.tofile(directory / "preview.bin")
    # E57 import already measured the complete cloud. Reuse those f64 bounds
    # instead of inferring a height scale from the display sample or crop.
    if working_bounds is not None:
        minimum_z = float(working_bounds['minimum'][2])
        maximum_z = float(working_bounds['maximum'][2])
    else:
        minimum_z, maximum_z = float('inf'), float('-inf')
        for begin in range(0, len(cloud.points), 200_000):
            z = cloud.points[begin:begin+200_000, 2]
            minimum_z = min(minimum_z, float(z.min()))
            maximum_z = max(maximum_z, float(z.max()))
    return {"format": "xyzrgb-f32-le", "path": f"generations/{generation}/preview.bin",
            "height_scale": {"minimum_z_m": minimum_z, "maximum_z_m": maximum_z,
                             "scope": "complete imported cloud in local metres"},
            "point_count": count, "source_point_count": len(cloud.points),
            "sampling": ("deterministic spatial-cell sample from up to "
                         f"{count * PREVIEW_CANDIDATE_MULTIPLIER:,} distributed source rows; display only"),
            "color_scaling": "sample-range normalization; original channels unchanged"}


def close_cloud(cloud):
    """Release cached file mappings before directory publication on Windows."""
    for name in ("points", "colors", "intensity", "color_valid", "intensity_valid", "scan_index", "source_record_index", "working_index"):
        channel = getattr(cloud, name, None)
        while channel is not None:
            mapping = getattr(channel, "_mmap", None)
            if mapping is not None:
                if not mapping.closed:
                    mapping.close()
                break
            channel = getattr(channel, "base", None)


@contextmanager
def generation_stage(path, project_id, token):
    uuid.UUID(hex=token)
    root = ensure_assets(path, project_id)
    directory = safe_path(root, f"staging/{token}")
    directory.mkdir(parents=True, exist_ok=False)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def publish_generation(path, token, stage):
    final = safe_path(assets_for(path), f"generations/{token}")
    final.parent.mkdir(exist_ok=True)
    os.replace(stage, final)


def create_project(path, job_id, source=None, two_storeys=False, progress=lambda *_: None):
    path = project_path(path)
    with project_lock(path):
        if path.exists():
            raise ValueError("Project already exists; choose a new project filename")
        marker = assets_for(path) / "owner.json"
        # Resume a cancelled first import without overwriting a saved project.
        project_id = read_json(marker)["project_id"] if marker.is_file() else uuid.uuid4().hex
        uuid.UUID(hex=project_id)
        ensure_assets(path, project_id)
        save_performance, _ = _performance_writer(path, job_id, "import" if source else "demo")
        import_report = _initial_performance(job_id, "import" if source else "demo",
                                             source_kind="E57" if source else "fixture")
        save_performance(import_report)
        with generation_stage(path, project_id, job_id) as stage:
            progress(5, "Reading scan" if source else "Creating example")
            if source:
                read_started = time.perf_counter()
                import_report["active_stages"] = ["e57_read_decompression_and_cache"]
                import_report["stages"].append({"stage": "e57_read_decompression_and_cache",
                                                "status": "running",
                                                "started_at_utc": datetime.now(timezone.utc).isoformat()})
                save_performance(import_report)
                imported = read_e57(source, stage / "working-cache", 200000)
                cloud, manifest = imported.cloud, imported.manifest
                read_seconds = time.perf_counter()-read_started
                import_report["stages"][-1].update(
                    status="complete", seconds=read_seconds,
                    raw_points=manifest["raw_point_count"], valid_points=manifest["valid_point_count"],
                    points_per_second=manifest["raw_point_count"]/max(read_seconds, 1e-9),
                    source_size_bytes=manifest["source"]["size_bytes"],
                    scope="combined E57 read, decompression, validation, coordinate conversion and cache writing",
                    completed_at_utc=datetime.now(timezone.utc).isoformat())
                import_report["active_stages"] = []
                save_performance(import_report)
                kind = "E57"
            else:
                cloud, manifest, kind = demo_cloud(two_storeys), None, "fixture"
                np.save(stage / "points.npy", cloud.points, allow_pickle=False)
            progress(70, "Preparing preview")
            preview = write_preview(cloud, stage, job_id, manifest['working_bounds_m'] if manifest else None)
            model = None
            if not source:
                progress(80, "Reconstructing example")
                candidate = reconstruct(cloud, name=path.stem,
                                        diagnostics=save_performance,
                                        diagnostic_context={"job_id": job_id, "command": "demo"})
                candidate.metadata["project_id"] = project_id
                candidate.warnings = [w for w in candidate.warnings if "No desktop review" not in w]
                model = candidate.to_dict()
            state = {"schema_version": 1, "project_id": project_id, "revision": uuid.uuid4().hex,
                     "name": path.stem, "assets_directory": assets_for(path).name,
                     "generations": [job_id], "cloud": {"kind": kind, "generation": job_id},
                     "preview": preview, "import_manifest": manifest, "model": model,
                     "crop": dict(EMPTY_CROP), "model_crop": dict(EMPTY_CROP), "model_crop_stale": False,
                     "coordinate_confirmation": {"z_up": not bool(source), "crs": "unconfirmed", "vertical_datum": "unconfirmed"},
                     "warnings": manifest["warnings"] if manifest else ["Generated example, not a survey."],
                     "processing_backend": candidate.metadata.get("performance", {}).get(
                         "compute_backend", "CPU") if model is not None else "not reconstructed"}
            close_cloud(cloud)
            publish_generation(path, job_id, stage)
            # Cancellation before this replacement can only leave an unused generation.
            atomic_json(path, state)
            import_report.update(status="completed", updated_at_utc=datetime.now(timezone.utc).isoformat())
            import_report.setdefault("events", []).append({"event": "job_completed", "at": import_report["updated_at_utc"]})
            if source:
                save_performance(import_report)
            progress(100, "Project ready")
            return state


def _desktop_recognition(state, cloud, model, request, stage, save_performance, progress):
    """Run immutable proposals, then validate original-point model candidates."""
    mode = request.get("recognition_mode", "classical")
    if mode not in {"classical", "specialist", "hybrid"}:
        raise ValueError("Recognition mode must be classical, specialist or hybrid")
    if mode == "classical":
        return {"schema_version": 1, "requested_mode": "classical", "actual_provider": "classical",
                "requested_provider": "classical", "provider_chain": ["classical"],
                "geometry_authority": "existing deterministic reconstruction",
                "active_branches": [], "missing_branches": [], "fallback_reason": None,
                "model_pack_manifest_sha256": None, "loaded_hashes": {},
                "proposal_manifest": None, "overlay_proposals": []}
    model_root = request.get("specialist_model_directory")
    if not isinstance(model_root, str) or not model_root.strip():
        return {"schema_version": 1, "requested_mode": mode, "actual_provider": "classical",
                "requested_provider": "PunctoraSpecialistProvider", "provider_chain": ["classical"],
                "geometry_authority": "existing deterministic reconstruction",
                "active_branches": [], "missing_branches": list("ABCDEFGHIJ"),
                "fallback_reason": "No explicit specialist model directory was selected; automatic downloads are disabled",
                "model_pack_manifest_sha256": None, "loaded_hashes": {},
                "proposal_manifest": None, "overlay_proposals": []}
    model_root = Path(model_root).resolve()
    specialist_python = request.get("specialist_python") or os.environ.get("PUNCTORA_SPECIALIST_PYTHON") or __import__("sys").executable
    specialist_python = str(Path(specialist_python).resolve())
    if state.get("import_manifest") is None:
        return {"schema_version": 1, "requested_mode": mode, "actual_provider": "classical",
                "requested_provider": "PunctoraSpecialistProvider", "provider_chain": ["classical"],
                "geometry_authority": "existing deterministic reconstruction",
                "active_branches": [], "missing_branches": list("ABCDEFGHIJ"),
                "fallback_reason": "Specialist desktop recognition requires imported original scan and record identities",
                "model_pack_manifest_sha256": None, "loaded_hashes": {},
                "proposal_manifest": None, "overlay_proposals": []}
    from .annotation_io import read_json as annotation_read_json
    from .recognition.classical_provider import ClassicalProvider
    from .recognition.hybrid import HybridProvider
    from .recognition.job import run_recognition
    from .recognition.contracts import safe_artifact_path
    from .recognition.specialist_provider import (PunctoraSpecialistAssets,
        PunctoraSpecialistProvider, SpecialistSettings)
    from .recognition.tiling import TileSettings
    manifest = state["import_manifest"]
    translation = manifest["coordinate_mapping"]["working_to_source_translation_m"]
    identity = {"case_id": state["project_id"], "source_sha256": manifest["source"]["sha256"],
                "coordinate_mapping": {"translation_m": list(map(float, translation)), "yaw_degrees": 0.},
                "crop": deepcopy(state["crop"]) if crop_active(state["crop"]) else None}
    manual = state["reconstruction_options"].get("manual_levels", [])
    if manual:
        levels = tuple({**value, "evidence_state": "user_supplied_bound_not_measured_floor"} for value in manual)
    else:
        levels = tuple({"name": item.name, "bottom_m": item.elevation, "top_m": item.ceiling,
                        "evidence_state": "detected_level_bound_not_measured_floor"}
                       for item in model.storeys)
    provider = PunctoraSpecialistProvider(
        PunctoraSpecialistAssets(specialist_python, str(model_root)),
        SpecialistSettings(level_bounds=levels))
    fallback = ClassicalProvider(model=model)
    tiles = TileSettings(size_m=8., overlap_m=.06, normal_radius_m=.3, index_cell_m=.25,
                         maximum_context_points=1_500_000, maximum_tiles=4096,
                         adaptive_partition=True, vertical_overlap_m=.06, separate_normal_context=True,
                         minimum_core_m=.25, maximum_subdivision_depth=16)
    latest = {}
    recognition_started=time.perf_counter()
    def diagnostic(value):
        latest.clear(); latest.update(deepcopy(value))
        performance = deepcopy(model.metadata.get("performance", {}))
        performance["recognition"] = {"requested_mode": mode, **latest,
            'phase_elapsed_seconds':latest.get('elapsed_seconds',0.),
            'elapsed_seconds':time.perf_counter()-recognition_started}
        performance.setdefault("schema_version", 2)
        performance.setdefault("status", "running")
        if latest.get('status') in {'failed','cancelled'}:performance['status']=latest['status']
        save_performance(performance)
    progress(62, f"Running {mode} specialist evidence")
    proposal_directory, proposal, cache_hit = run_recognition(
        cloud, identity, provider, stage / "recognition", tile_settings=tiles,
        fallback=fallback, diagnostics=diagnostic)
    specialist = proposal.get("extensions", {}).get("specialist_v1")
    fusion = None
    if specialist:
        from .recognition.geometry_fusion import fuse_geometry
        from .recognition.job import RecognitionControl
        from .spatial_index import SpatialPointIndex
        settings = ReconstructionSettings(**request.get('settings',{}))
        progress(76, 'Refitting specialist candidates against original points')
        with RecognitionControl(int(latest.get('memory_limit_bytes',0)),65536,diagnostics=diagnostic) as control:
            control.stage='original_point_geometry_fusion'
            fusion_index=SpatialPointIndex.build(cloud,.2,control.working_budget//4,control.chunk_points,
                scratch_directory=stage,progress=lambda *_:control.check())
            try:
                fusion=fuse_geometry(cloud,model,proposal,proposal_directory,fusion_index,control,settings)
            except BaseException:
                fusion_index.close();raise
            model._spatial_index=fusion_index
    overlays = []
    if specialist:
        overlay_report = annotation_read_json(safe_artifact_path(proposal_directory, specialist["proposals_path"]))
        overlays.extend(item for item in overlay_report["proposals"]
                        if "polygon_xy_m" in item and "z_min_m" in item and "z_max_m" in item)
        overlays = overlays[:5000]
        for instance in proposal["instances"][:5000 - len(overlays)]:
            if instance["class"] != "wall" or instance.get("geometry", {}).get("type") != "wall":
                continue
            geometry = instance["geometry"]
            start, end = np.asarray(geometry["start"]), np.asarray(geometry["end"])
            direction = end - start
            length = np.linalg.norm(direction)
            if length <= 1e-12:
                continue
            side = np.array([-direction[1], direction[0]]) / length * geometry["thickness"] / 2
            overlays.append({"id": instance["id"], "branch": "J", "class": "wall", "status": "proposed",
                             "polygon_xy_m": [(start - side).tolist(), (end - side).tolist(),
                                              (end + side).tolist(), (start + side).tolist()],
                             "z_min_m": geometry["base"], "z_max_m": geometry["base"] + geometry["height"],
                             "geometry_authority": "review_only"})
    provider_chain = [proposal["provider"]["id"]]
    final_directory, final_proposal, final_hit = proposal_directory, proposal, cache_hit
    if mode == "hybrid":
        progress(74, "Fusing specialist and projected review-only evidence")
        final_directory, final_proposal, final_hit = run_recognition(
            cloud, identity, HybridProvider(proposal_directory), stage / "hybrid-recognition",
            tile_settings=tiles, diagnostics=diagnostic)
        provider_chain.append(final_proposal["provider"]["id"])
    warning = next((value for value in proposal["warnings"] if "fallback" in value.lower()), None)
    relative = final_directory.relative_to(stage).as_posix() + "/proposals-v1.json"
    specialist_relative = proposal_directory.relative_to(stage).as_posix() + "/proposals-v1.json"
    active = [name for name, value in (specialist or {}).get("branches", {}).items() if value["status"] == "active"]
    missing = [name for name, value in (specialist or {}).get("branches", {}).items() if value["status"] != "active"]
    if specialist is None and proposal["provider"]["id"] == "classical":
        missing = list("ABCDEFGHIJ")
    result = {"schema_version": 1, "requested_mode": mode,
              "requested_provider": "PunctoraSpecialistProvider",
              "actual_provider": final_proposal["provider"]["id"], "provider_chain": provider_chain,
              "geometry_authority": "original-point validated unreviewed candidates; provider proposals remain review-only",
              "geometry_fusion": fusion,
              "active_branches": active, "missing_branches": missing,
              "model_pack_manifest_sha256": (specialist or {}).get("model_pack_manifest_sha256"),
              "loaded_hashes": {name: value.get("graph_sha256") for name, value in
                                (specialist or {}).get("branches", {}).items() if value["status"] == "active"},
              "fallback_reason": warning, "proposal_manifest": f"generations/{request['job_id']}/{relative}",
              "specialist_proposal_manifest": f"generations/{request['job_id']}/{specialist_relative}",
              "proposal_cache_hit": bool(final_hit), "overlay_proposals": overlays,
              "model_view_population": (specialist or {}).get("point_model_view_population", 0),
              "original_population": len(cloud.points)}
    model.metadata["recognition"] = {key: deepcopy(value) for key, value in result.items() if key != "overlay_proposals"}
    model.metadata.setdefault("performance", {})["recognition"] = {
        **deepcopy(model.metadata["recognition"]),'elapsed_seconds':time.perf_counter()-recognition_started,
        'status':'complete','runtime_diagnostics':deepcopy(latest)}
    return result


def reconstruct_project(path, request, progress=lambda *_: None):
    with project_lock(path):
        state = load_project(path)
        check_revision(state, request["expected_revision"])
        mode=request.get('model_action','replace')
        if mode not in {'replace','add'}:raise ValueError('Model action must be replace or add')
        previous_model=BuildingModel.from_dict(state['model']) if mode=='add' and state.get('model') else None
        previous_generations=list(state['generations'])
        if not request.get("confirm_z_up"):
            raise ValueError("Confirm that the scan uses Z as the upward direction before reconstruction")
        token = request["job_id"]
        save_performance, _ = _performance_writer(path, token, "reconstruct")
        save_performance(_initial_performance(
            token, "reconstruct", project_name=state["name"],
            e57_read_decompression={"seconds": 0.0,
                                    "scope": "not repeated; reconstruction reads the imported memory-mapped cache"}))
        with generation_stage(path, state["project_id"], token) as stage:
            progress(5, "Opening working cloud")
            source_cloud = load_cloud(path, state)
            cloud = source_cloud
            settings = ReconstructionSettings(**request.get("settings", {}))
            options=validate_detection_options(request.get('reconstruction_options',state.get('reconstruction_options')))
            settings=replace(settings,reconstruction_scope=options['scope'])
            crop_directory = stage / "crop-working"
            try:
                if crop_active(state["crop"]):
                    progress(10, "Applying non-destructive project crop")
                    cloud, crop_report = materialize_crop(
                        source_cloud, state["crop"], crop_directory, settings.processing_chunk_points)
                else:
                    crop_report = {"active": False, "source_points": len(source_cloud.points),
                                   "selected_points": len(source_cloud.points), "crop": state["crop"]}
                progress(20, "Finding surfaces and fitting elements")
                if request.get("compare_budgets"):
                    if options['manual_levels']:
                        raise ValueError('Budget comparison requires automatic levels; disable it for manual bounds')
                    model, budget_report = compare_budgets(
                        cloud,settings,progress=progress,diagnostics=save_performance,scratch_directory=stage)
                    atomic_json(assets_for(path) / "budget-comparison.json", budget_report)
                    model.metadata["budget_comparison"] = budget_report
                else:
                    model = reconstruct(cloud, settings,manual_levels=options['manual_levels'],name=state["name"],
                                        progress=progress, diagnostics=save_performance,scratch_directory=stage,
                                        diagnostic_context={"job_id": token, "command": "reconstruct",
                                                            "project_name": state["name"],
                                                            "source_points": len(cloud.points),
                                                            "e57_read_decompression": {"seconds": 0.0,
                                                                "scope": "not repeated; memory-mapped import cache"}})
                model.metadata["project_id"] = state["project_id"]
                state['reconstruction_options']=options
                model.metadata['reconstruction_options']=options
                model.metadata["crop"] = crop_report
                if crop_report["active"]:
                    model.warnings.append(
                        f"Reconstruction used {crop_report['selected_points']:,} of "
                        f"{crop_report['source_points']:,} source points inside the saved project crop.")
                if state["import_manifest"]:
                    manifest = state["import_manifest"]
                    model.metadata["source"] = manifest["source"]
                    model.metadata["coordinate_mapping"] = manifest["coordinate_mapping"]
                    model.metadata["e57"] = {"coordinate_metadata": manifest["coordinate_metadata"],
                                              "coordinate_metadata_status": manifest["coordinate_metadata_status"]}
                    model.warnings.extend(manifest["warnings"])
                geometry_seconds=model.metadata.get('performance',{}).get('total_seconds',0.)
                if request.get('recognition_mode','classical') != 'classical':
                    completed_index=getattr(model,'_spatial_index',None)
                    if completed_index is not None:completed_index.close()
                    model._spatial_index=None
                release_completed_working_memory()
                recognition = _desktop_recognition(state, cloud, model, request, stage, save_performance, progress)
                progress(79, "Retaining final source evidence")
                evidence_started=time.perf_counter()
                evidence = stage / "evidence" / "records"
                evidence.parent.mkdir()
                write_model_evidence(cloud,model,evidence,settings.processing_chunk_points)
                model.metadata['performance']['geometry_and_evidence_seconds']=geometry_seconds+time.perf_counter()-evidence_started
                for wall in model.walls:
                    record = wall.evidence.get("records")
                    if record:
                        record["path"] = f"generations/{token}/{record['path']}"
                for proposal in model.metadata.get("surface_proposals", []):
                    record = proposal.get("representative_cloud_records")
                    if record:
                        record["path"] = f"generations/{token}/{record['path']}"
                model.metadata["recognition"] = {key: deepcopy(value) for key, value in recognition.items()
                                                 if key != "overlay_proposals"}
                if recognition.get("fallback_reason"):
                    model.warnings.append("Recognition fallback: " + recognition["fallback_reason"])
                state["recognition"] = recognition
                progress(80, "Validating model candidates")
                model.warnings = [w for w in model.warnings if "No desktop review" not in w]
                model.warnings.append("Whole-cloud deviation reporting remains pending; review observed and inferred geometry separately.")
                if previous_model is not None:
                    from .model_merge import merge_models
                    current=model
                    model,merge_report=merge_models(previous_model,current,namespace='run-'+token[:8])
                    model._spatial_index=getattr(current,'_spatial_index',None)
                    model.metadata['reconstruction_options']=options
                    model.metadata['crop']=crop_report
                    model.metadata['performance']=current.metadata.get('performance',{})
                    model.metadata['recognition']={key:deepcopy(value) for key,value in recognition.items()
                                                   if key!='overlay_proposals'}
                state["model"] = model.to_dict()
                state["model_crop"] = deepcopy(state["crop"])
                state["model_crop_stale"] = False
                state["generations"] = list(dict.fromkeys([
                    *(previous_generations if previous_model is not None else [state['cloud']['generation']]),token]))
                state["coordinate_confirmation"]["z_up"] = True
                state["revision"] = uuid.uuid4().hex
                state["processing_backend"] = model.metadata.get("performance", {}).get(
                    "compute_backend", "CPU")
                from .reproducibility import geometry_signature
                model.metadata['reproducibility']=geometry_signature(model)
                model.metadata['performance']=save_performance(model.metadata.get('performance',{}))
                state['model']=model.to_dict()
                # This snapshot becomes visible only after publication below.
                # last-performance.json is the authoritative end-to-end clock.
                state['model']['metadata']['performance']['status']='completed'
                state['model']['metadata']['performance']['end_to_end_report']='last-performance.json'
            except BaseException as exc:
                failure=deepcopy(model.metadata.get('performance',{})) if 'model' in locals() else {}
                failure.update(status='cancelled' if isinstance(exc,InterruptedError) else 'failed',error=str(exc))
                save_performance(failure)
                raise
            finally:
                if "model" in locals() and getattr(model,"_spatial_index",None) is not None:
                    model._spatial_index.close()
                if cloud is not source_cloud:
                    close_cloud(cloud)
                close_cloud(source_cloud)
                shutil.rmtree(crop_directory, ignore_errors=True)
            try:
                publish_generation(path, token, stage)
                atomic_json(path, state)
            except BaseException as exc:
                save_performance({**model.metadata.get('performance',{}),'status':'failed','error':str(exc)})
                raise
            from .project_storage import storage_report
            final_performance={**model.metadata.get('performance',{}),'storage':storage_report(assets_for(path))}
            save_performance(final_performance,final=True)
            progress(100, "Candidates ready for review")
            return state


def add_project_model(path,request,progress=lambda *_:None):
    """Atomically add another saved model and copy its complete reference arrays."""
    from contextlib import ExitStack
    from .model_merge import merge_models
    source_path=project_path(request['source_project'])
    target_path=project_path(path)
    with ExitStack() as stack:
        for item in sorted({source_path,target_path}):stack.enter_context(project_lock(item))
        state=load_project(target_path);check_revision(state,request['expected_revision'])
        incoming_state=load_project(source_path)
        if not state.get('model') or not incoming_state.get('model'):
            raise ValueError('Both projects need a saved detected model before adding')
        if incoming_state['model_crop_stale']:
            raise ValueError('Source model is stale; redetect or restore its saved detection bounds before adding')
        if state['model_crop_stale']:
            raise ValueError('Restore or redetect the target bounds before adding another project')
        token=request['job_id']
        with generation_stage(target_path,state['project_id'],token) as stage:
            data=deepcopy(incoming_state['model']);copies={}
            def copy_records(value):
                if isinstance(value,dict):
                    relative=value.get('path')
                    if isinstance(relative,str) and relative.startswith('generations/') and relative.endswith('.npy'):
                        if relative not in copies:
                            name=f'imported-evidence/records-{len(copies)+1}.npy'
                            source=safe_path(assets_for(source_path),relative)
                            destination=safe_path(stage,name);destination.parent.mkdir(parents=True,exist_ok=True)
                            shutil.copyfile(source,destination)
                            copies[relative]=f'generations/{token}/{name}'
                        value['path']=copies[relative]
                    for child in value.values():copy_records(child)
                elif isinstance(value,list):
                    for child in value:copy_records(child)
            progress(20,'Preserving source evidence');copy_records(data)
            existing=BuildingModel.from_dict(state['model']);incoming=BuildingModel.from_dict(data)
            progress(60,'Aligning and reconciling model results')
            combined,report=merge_models(existing,incoming,namespace='project-'+token[:8],
                alignment_matrix=request.get('alignment_matrix'),
                confirm_shared_frame=request.get('confirm_shared_source_frame') is True)
            combined.metadata['project_id']=state['project_id']
            combined.metadata['reconstruction_options']=state['reconstruction_options']
            report['evidence_files_copied']=len(copies)
            state['model']=combined.to_dict();state['revision']=uuid.uuid4().hex
            state['generations']=list(dict.fromkeys([*state['generations'],token]))
            publish_generation(target_path,token,stage);atomic_json(target_path,state)
            progress(100,'Combined model ready for review');return state


def draft_model(state, data):
    model = BuildingModel.from_dict(deepcopy(data))
    if model.metadata.get("project_id") != state["project_id"]:
        raise ValueError("Model identity differs from the opened project")
    return model


def apply_draft_context(state, request):
    result = deepcopy(state)
    result['reconstruction_options']=validate_detection_options(request.get('reconstruction_options',result.get('reconstruction_options')))
    result["crop"] = validate_crop(request.get("crop", result["crop"]))
    result["model_crop"] = validate_crop(request.get("model_crop", result["model_crop"]))
    result["model_crop_stale"] = model_input_stale(result)
    return result


def model_input_stale(state):
    model=state.get('model')
    return bool(model is not None and (state['crop']!=state['model_crop'] or
        validate_detection_options(state.get('reconstruction_options'))!=
        validate_detection_options(model.get('metadata',{}).get('reconstruction_options'))))


def edit_model(state, data, element_id, changes):
    model = draft_model(state, data)
    element = next((obj for obj in (model.walls + model.facade_panels + model.slabs + model.storeys
                                    + model.openings + model.stairs + model.landings + model.slab_openings)
                    if obj.id == element_id), None)
    if element is None:
        raise ValueError("Select a supported element")
    allowed = ({"start", "end", "base", "height", "thickness", "classification", "review_state"} if element in model.walls+model.facade_panels
               else {"base", "thickness", "review_state"} if element in model.slabs
               else {"host_wall_id", "kind", "offset", "sill", "width", "height", "review_state"} if element in model.openings
               else {"start", "end", "base", "width", "rise", "going", "steps", "tread_thickness", "review_state"} if element in model.stairs
               else {"base", "thickness", "review_state"} if element in model.landings
               else {"host_slab_id", "start", "end", "width", "review_state", "ifc_cut_approved"} if element in model.slab_openings
               else {"name", "elevation", "ceiling"})
    if not isinstance(changes, dict) or not changes or set(changes)-allowed:
        raise ValueError("Unsupported element correction")
    if "ifc_cut_approved" in changes and not isinstance(changes["ifc_cut_approved"], bool):
        raise ValueError("Slab cut approval must be a boolean")
    old = deepcopy(element.__dict__)
    for field, value in changes.items():
        if field == "name" and (not isinstance(value, str) or not value.strip()):
            raise ValueError("Storey name cannot be empty")
        if field in {"host_wall_id", "host_slab_id", "kind"} and (not isinstance(value, str) or not value):
            raise ValueError("Element classifications and host IDs must be nonempty strings")
        if field in {"base", "height", "thickness", "elevation", "ceiling", "offset", "sill", "width", "rise", "going", "steps", "tread_thickness"} and (isinstance(value, bool) or not isinstance(value, (float, int))):
            raise ValueError("Dimensions must be numbers in metres")
        setattr(element, field, value)
        if field not in {"name", "review_state", "ifc_cut_approved"}:
            element.provenance[field] = "user_supplied"
    if element in model.openings and element.evidence.get('facade_system') and set(changes)-{"review_state"}:
        element.evidence["facade_geometry_stale"] = True
    if element in model.walls and set(changes)&{'start','end','base','height'}:
        element.profile_xz=[]
    if element in model.slab_openings:
        if set(changes)-{"review_state", "ifc_cut_approved"}:
            element.ifc_cut_approved = False
            element.evidence["validation_state"] = "review_required"
            # The edited frame replaces the previous observed polygon.
            element.footprint = None
        if changes.get("ifc_cut_approved") is True:
            element.ifc_cut_approved = True
            element.review_state = "reviewed"
            element.evidence["user_cut_approval"] = "explicit_geometry_approval"
    if element in model.stairs:
        import numpy as np
        direction = np.asarray(old["end"], dtype=float)-np.asarray(old["start"], dtype=float)
        direction /= np.linalg.norm(direction)
        if "end" in changes or "start" in changes:
            element.going = float(np.linalg.norm(np.asarray(element.end)-element.start))/element.steps
            element.provenance["going"] = "user_supplied"
        elif "going" in changes or "steps" in changes:
            element.end = tuple(np.asarray(element.start)+direction*element.going*element.steps)
            element.provenance["end"] = "user_supplied"
        if set(changes)-{"review_state"}:
            element.evidence["source_geometry_changed"] = True
            for opening in model.slab_openings:
                if opening.source_stair_id == element.id or (element.system_id and opening.source_system_id == element.system_id):
                    opening.ifc_cut_approved = False
                    opening.review_state = "flagged"
                    opening.evidence["source_geometry_changed"] = True
            for landing in model.landings:
                if element.id in landing.connected_stair_ids:
                    landing.review_state = "flagged"
                    landing.evidence["source_geometry_changed"] = True
    if element in model.landings and set(changes)-{"review_state"}:
        element.evidence["source_geometry_changed"] = True
        if element.evidence.get("floor_integrated"):
            element.evidence["floor_integrated"] = False
            element.evidence["floor_integration_stale"] = True
            element.evidence.pop("source_floor_id", None)
            element.review_state = "flagged"
        for opening in model.slab_openings:
            if element.system_id and opening.source_system_id == element.system_id:
                opening.ifc_cut_approved = False
                opening.review_state = "flagged"
                opening.evidence["source_geometry_changed"] = True
    if element in model.slabs and set(changes)-{"review_state"}:
        for opening in model.slab_openings:
            if opening.host_slab_id == element.id:
                opening.ifc_cut_approved = False
                opening.review_state = "flagged"
                opening.evidence["host_geometry_changed"] = True
    if element in model.storeys:
        shift = element.elevation-old["elevation"]
        height_shift = (element.ceiling-element.elevation)-(old["ceiling"]-old["elevation"])
        for obj in model.walls + model.spaces:
            if obj.storey_id == element.id:
                obj.base += shift
                obj.height += height_shift
                obj.provenance.update(base="user_supplied", height="user_supplied")
        for slab in model.slabs:
            if slab.storey_id == element.id:
                slab.base += element.ceiling-old["ceiling"] if slab.id == "top-slab" else shift
                slab.provenance["base"] = "user_supplied"
        for stair in model.stairs:
            if stair.storey_id == element.id:
                stair.base += shift
                stair.provenance["base"] = "user_supplied"
        for landing in model.landings:
            if landing.storey_id == element.id:
                landing.base += shift
                landing.provenance["base"] = "user_supplied"
        levels = sorted(model.storeys, key=lambda obj: obj.elevation)
        if any(a.ceiling > b.elevation+1e-8 for a, b in zip(levels, levels[1:])):
            raise ValueError("Edited storey intervals overlap")
    if element in model.storeys and set(changes)-{"name"}:
        for opening in model.slab_openings:
            opening.ifc_cut_approved = False
            opening.review_state = "flagged"
            opening.evidence["host_geometry_changed"] = True
    geometry = set(changes)-{"review_state", "classification", "name"}
    if geometry or changes.get("review_state") == "rejected":
        model.metadata["geometry_edited"] = True
    model.metadata.setdefault("edit_history", []).append({"element_id": element_id, "changes": deepcopy(changes),
                            "quality_scope": "Observed faces and evidence describe the original fit, not the corrected geometry"})
    model.validate()
    return model.to_dict()


def _new_id(model, stem):
    existing = {obj.id for obj in (model.storeys + model.walls + model.slabs + model.spaces
                                    + model.openings + model.stairs + model.landings + model.slab_openings + model.facade_panels)}
    index = 1
    while f"{stem}-{index}" in existing:
        index += 1
    return f"{stem}-{index}"


def add_candidate(state, data, kind, host_id):
    """Add explicit user-supplied review geometry without changing the saved project."""
    from math import ceil, dist
    from shapely.geometry import Polygon
    from .features import _opening_frame
    model = draft_model(state, data)
    if kind in {"door", "window", "unknown"}:
        host = next((wall for wall in model.walls if wall.id == host_id), None)
        if host is None:
            raise ValueError("Select a host wall before adding an opening")
        length = dist(host.start, host.end)
        width = min(.9 if kind == "door" else 1.2, length*.6)
        sill = 0.0 if kind == "door" else .9
        height = min(2.1 if kind == "door" else 1.2, host.height-sill)
        model.openings.append(Opening(_new_id(model, f"{host.id}-{kind}"), host.id, kind,
                                      (length-width)/2, sill, width, height,
                                      {"dimensions": "user_supplied", "kind": "user_supplied",
                                       "filling": "unknown"}, evidence={
                                           "method": "manual_candidate",
                                           "scope": "User-supplied opening; verify dimensions and host against the point cloud"}))
    elif kind == "stair":
        storey = next((item for item in model.storeys if item.id == host_id), None)
        if storey is None:
            raise ValueError("Select a storey before adding a stair")
        centre = np.asarray(Polygon(storey.footprint).representative_point().coords[0])
        steps = max(4, min(100, int(ceil((storey.ceiling-storey.elevation)/.18))))
        rise, going = (storey.ceiling-storey.elevation)/steps, .28
        start, end = centre-np.array([steps*going/2, 0]), centre+np.array([steps*going/2, 0])
        identifier = _new_id(model, f"{storey.id}-stair")
        model.stairs.append(Stair(identifier, storey.id, tuple(start), tuple(end), storey.elevation,
                                  .9, rise, going, steps, provenance={
                                      "treads": "user_supplied", "run": "user_supplied",
                                      "structure": "unknown"}, system_id=identifier, flight_index=1,
                                  evidence={"method": "manual_candidate",
                                            "scope": "User-supplied stair flight; verify every dimension against the point cloud"}))
    elif kind == "landing":
        stair = next((item for item in model.stairs if item.id == host_id), None)
        if stair is None:
            raise ValueError("Select a stair flight before adding a landing")
        start, end = np.asarray(stair.start), np.asarray(stair.end)
        direction = (end-start)/np.linalg.norm(end-start)
        side = np.array([-direction[1], direction[0]])*stair.width/2
        depth = stair.width
        footprint = [tuple(end-side), tuple(end+direction*depth-side),
                     tuple(end+direction*depth+side), tuple(end+side)]
        identifier = _new_id(model, f"{stair.storey_id}-landing")
        model.landings.append(Landing(identifier, stair.storey_id, footprint,
                                      stair.base+stair.steps*stair.rise-.06, .12,
                                      stair.system_id or stair.id, [stair.id],
                                      {"footprint": "user_supplied", "base": "user_supplied",
                                       "thickness": "user_supplied"}, evidence={
                                           "method": "manual_candidate",
                                           "scope": "User-supplied landing; verify footprint and flight connections"}))
    elif kind == "slab_opening":
        slab = next((item for item in model.slabs if item.id == host_id), None)
        if slab is None:
            raise ValueError("Select a host slab before adding a slab opening")
        host = Polygon(slab.footprint)
        centre = np.asarray(host.representative_point().coords[0])
        rectangle = Polygon([centre+[-.8, -.5], centre+[.8, -.5], centre+[.8, .5], centre+[-.8, .5]])
        geometry = rectangle.intersection(host).buffer(0)
        if not isinstance(geometry, Polygon) or geometry.area < .05:
            raise ValueError("The selected slab has no safe default opening footprint")
        footprint = [tuple(map(float, point)) for point in list(geometry.exterior.coords)[:-1]]
        start, end, width = _opening_frame(geometry)
        model.slab_openings.append(SlabOpening(_new_id(model, f"{slab.id}-opening"), slab.id,
                                                start, end, width, provenance={
                                                    "footprint": "user_supplied", "host_slab_id": "user_supplied"},
                                                evidence={"method": "manual_candidate",
                                                          "scope": "User-supplied slab opening; verify structural trimming"},
                                                footprint=footprint))
    else:
        raise ValueError("Unsupported candidate type")
    model.metadata["geometry_edited"] = True
    model.metadata.setdefault("edit_history", []).append({"operation": "add_candidate", "kind": kind, "host_id": host_id})
    model.validate()
    return model.to_dict()


def delete_candidate(state, data, element_id):
    model = draft_model(state, data)
    collections = [model.openings, model.stairs, model.landings, model.slab_openings, model.facade_panels]
    target = next((obj for values in collections for obj in values if obj.id == element_id), None)
    if target is None:
        raise ValueError("Only opening, stair, landing and slab-opening candidates can be deleted")
    if target in model.stairs:
        model.stairs.remove(target)
        model.slab_openings = [opening for opening in model.slab_openings if opening.source_stair_id != target.id]
        for opening in model.slab_openings:
            if target.system_id and opening.source_system_id == target.system_id:
                opening.ifc_cut_approved = False
                opening.review_state = "flagged"
                opening.evidence["source_flight_deleted"] = target.id
        for landing in list(model.landings):
            landing.connected_stair_ids = [value for value in landing.connected_stair_ids if value != target.id]
            if not landing.connected_stair_ids:
                model.landings.remove(landing)
    else:
        for values in collections:
            if target in values:
                values.remove(target)
                break
    model.metadata["geometry_edited"] = True
    model.metadata.setdefault("edit_history", []).append({"operation": "delete_candidate", "element_id": element_id})
    model.validate()
    return model.to_dict()


def merge_model_walls(state, data, wall_ids):
    """Apply an explicit draft-only wall merge and preserve hosted openings."""
    model = draft_model(state, data)
    return merge_walls(model, wall_ids).to_dict()


def split_model_wall(state, data, wall_id, offset):
    """Split one draft wall at a measured local offset from its start point."""
    model = draft_model(state, data)
    return split_wall(model, wall_id, offset).to_dict()


def edit_crop(state, crop):
    result = deepcopy(state)
    updated = validate_crop(crop)
    if updated != result["crop"]:
        result["crop"] = updated
        result["model_crop_stale"] = result.get("model") is not None and updated != result["model_crop"]
    return result


def save_project(path, request):
    with project_lock(path):
        state = load_project(path)
        check_revision(state, request["expected_revision"])
        model = draft_model(state, request["model"]) if request.get("model") is not None else None
        name = request.get("name", state["name"])
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Project name cannot be empty")
        state["name"] = name
        state['reconstruction_options']=validate_detection_options(request.get('reconstruction_options',state.get('reconstruction_options')))
        if model is not None:
            model.name = name
            state["model"] = model.to_dict()
        state["crop"] = validate_crop(request.get("crop", state["crop"]))
        state["model_crop"] = validate_crop(request.get("model_crop", state["model_crop"]))
        state["model_crop_stale"] = model_input_stale(state)
        state["revision"] = uuid.uuid4().hex
        atomic_json(path, state)
        return state


def save_copy(path, destination, request):
    destination = project_path(destination)
    if destination == project_path(path):
        return save_project(path, request) if request.get("model") else load_project(path)
    with project_lock(path), project_lock(destination):
        state = load_project(path)
        check_revision(state, request["expected_revision"])
        state['reconstruction_options']=validate_detection_options(request.get('reconstruction_options',state.get('reconstruction_options')))
        if destination.exists():
            raise ValueError("Choose a new filename for the project copy")
        if request.get("model"):
            state["model"] = draft_model(state, request["model"]).to_dict()
        state["crop"] = validate_crop(request.get("crop", state["crop"]))
        state["model_crop"] = validate_crop(request.get("model_crop", state["model_crop"]))
        state["model_crop_stale"] = model_input_stale(state)
        root = ensure_assets(destination, state["project_id"])
        try:
            for token in state["generations"]:
                target = root / "generations" / token
                if target.is_symlink():
                    raise ValueError("Project copy cannot overwrite a linked generation")
                safe_path(root, f"generations/{token}")
                shutil.copytree(safe_path(assets_for(path), f"generations/{token}"), target, dirs_exist_ok=True)
            state["assets_directory"] = root.name
            state["revision"] = uuid.uuid4().hex
            atomic_json(destination, state)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise
        return state


def export_project(path, request, progress=lambda *_: None):
    with project_lock(path):
        state = load_project(path)
        check_revision(state, request["expected_revision"])
        requested_crop = validate_crop(request.get("crop", state["crop"]))
        requested_model_crop = validate_crop(request.get("model_crop", state["model_crop"]))
        if state["model_crop_stale"] or requested_crop != requested_model_crop:
            raise ValueError("The crop or level settings changed after detection; run Detect elements again before IFC conversion")
        model = draft_model(state, request.get("model") or state["model"])
        rejected = {w.id for w in model.walls if w.review_state == "rejected"}
        rejected_slabs = {s.id for s in model.slabs if s.review_state == "rejected"}
        rejected_stairs = {s.id for s in model.stairs if s.review_state == "rejected"}
        rejected_landings = {landing.id for landing in model.landings if landing.review_state == "rejected"}
        model.walls = [w for w in model.walls if w.id not in rejected]
        model.facade_panels = [p for p in model.facade_panels if p.review_state != 'rejected']
        model.slabs = [s for s in model.slabs if s.id not in rejected_slabs]
        model.openings = [o for o in model.openings if o.host_wall_id not in rejected and o.review_state != "rejected"]
        model.stairs = [s for s in model.stairs if s.id not in rejected_stairs]
        model.landings = [landing for landing in model.landings if landing.id not in rejected_landings
                          and any(stair_id not in rejected_stairs for stair_id in landing.connected_stair_ids)]
        for landing in model.landings:
            landing.connected_stair_ids = [stair_id for stair_id in landing.connected_stair_ids
                                           if stair_id not in rejected_stairs]
        initial_slab_openings = len(model.slab_openings)
        review_only_slab_opening_ids = [o.id for o in model.slab_openings
            if o.review_state != "rejected" and not slab_opening_is_validated(o, model.stairs, model.landings)]
        model.slab_openings = [o for o in model.slab_openings
                               if slab_opening_is_validated(o, model.stairs, model.landings)
                               and o.host_slab_id not in rejected_slabs
                               and (o.source_stair_id is None or o.source_stair_id not in rejected_stairs)]
        unresolved = sum(obj.review_state in {"unreviewed", "flagged"}
                         for obj in model.walls + model.slabs + model.openings
                         + model.stairs + model.landings + model.slab_openings + model.facade_panels)
        if unresolved:
            model.warnings.append(f"Export includes {unresolved} unreviewed or flagged elements; review state does not establish acceptance.")
        if model.metadata.get("geometry_edited"):
            model.spaces = []
            model.warnings.append("Derived spaces omitted after geometry corrections; room boundaries require regeneration.")
        target = Path(request["output"]).resolve()
        if target.suffix.lower() != ".ifc" or target.is_relative_to(assets_for(path)) or target == project_path(path):
            raise ValueError("Export requires an IFC file outside the project cache")
        progress(20, "Creating and validating IFC4")
        report = write_ifc(model, target)
        if any(item["status"] == "review_required" for item in report.get("stairwell_verification", [])):
            model.warnings.append("Exported candidate retains stair/slab or headroom conflicts; inspect stairwell verification before accepting it.")
        progress(100, "IFC export complete")
        return {"output": str(target), "validation": report, "warnings": model.warnings,
                "excluded_rejected_walls": len(rejected),
                "excluded_rejected_landings": len(rejected_landings),
                "excluded_slab_openings": initial_slab_openings-len(model.slab_openings),
                "review_only_slab_opening_ids": review_only_slab_opening_ids,
                "spaces_omitted_after_edits": bool(model.metadata.get("geometry_edited"))}


def cleanup_project(path):
    """Delete only owned unused generations, after acquiring the project lock."""
    with project_lock(path):
        state = load_project(path)
        root = ensure_assets(path, state["project_id"])
        removed = []
        for area in ["staging", "generations"]:
            directory = root / area
            if not directory.exists():
                continue
            for child in directory.iterdir():
                if area == "generations" and child.name in state["generations"]:
                    continue
                try:
                    uuid.UUID(hex=child.name)
                except ValueError:
                    continue
                safe_path(root, f"{area}/{child.name}")
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                    removed.append(f"{area}/{child.name}")
        return {"removed": removed}

