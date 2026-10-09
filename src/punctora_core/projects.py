"""Atomic desktop projects, bounded previews and immutable source generations."""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

import numpy as np

from .cloud_io import CloudData
from .e57_io import read_e57
from .evidence import write_wall_evidence
from .fixtures import demo_cloud
from .ifc_export import write_ifc
from .model import BuildingModel
from .reconstruction import ReconstructionSettings, reconstruct
from .wall_editing import merge_walls, split_wall

# The preview is a display-only sample. 500k points remains small compared with
# the immutable working cloud (12 MB on disk, 14 MB in the GPU vertex buffer)
# while giving large surveys enough visual density for element review.
PREVIEW_LIMIT = 500_000


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


def write_preview(cloud, directory, generation):
    count = min(PREVIEW_LIMIT, len(cloud.points))
    ids = np.linspace(0, len(cloud.points)-1, count, dtype=np.int64)
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
    return {"format": "xyzrgb-f32-le", "path": f"generations/{generation}/preview.bin",
            "point_count": count, "source_point_count": len(cloud.points),
            "sampling": "deterministic evenly spaced source rows; display only",
            "color_scaling": "sample-range normalization; original channels unchanged"}


def close_cloud(cloud):
    """Release cached file mappings before directory publication on Windows."""
    for name in ("points", "colors", "intensity", "color_valid", "intensity_valid", "scan_index", "source_record_index"):
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
        with generation_stage(path, project_id, job_id) as stage:
            progress(5, "Reading scan" if source else "Creating example")
            if source:
                imported = read_e57(source, stage / "working-cache", 200000)
                cloud, manifest = imported.cloud, imported.manifest
                kind = "E57"
            else:
                cloud, manifest, kind = demo_cloud(two_storeys), None, "fixture"
                np.save(stage / "points.npy", cloud.points, allow_pickle=False)
            progress(70, "Preparing preview")
            preview = write_preview(cloud, stage, job_id)
            model = None
            if not source:
                progress(80, "Reconstructing example")
                candidate = reconstruct(cloud, name=path.stem)
                candidate.metadata["project_id"] = project_id
                candidate.warnings = [w for w in candidate.warnings if "No desktop review" not in w]
                model = candidate.to_dict()
            state = {"schema_version": 1, "project_id": project_id, "revision": uuid.uuid4().hex,
                     "name": path.stem, "assets_directory": assets_for(path).name,
                     "generations": [job_id], "cloud": {"kind": kind, "generation": job_id},
                     "preview": preview, "import_manifest": manifest, "model": model,
                     "coordinate_confirmation": {"z_up": not bool(source), "crs": "unconfirmed", "vertical_datum": "unconfirmed"},
                     "warnings": manifest["warnings"] if manifest else ["Generated example, not a survey."],
                     "processing_backend": "CPU; no GPU compute backend implemented"}
            close_cloud(cloud)
            publish_generation(path, job_id, stage)
            # Cancellation before this replacement can only leave an unused generation.
            atomic_json(path, state)
            progress(100, "Project ready")
            return state


def reconstruct_project(path, request, progress=lambda *_: None):
    with project_lock(path):
        state = load_project(path)
        check_revision(state, request["expected_revision"])
        if not request.get("confirm_z_up"):
            raise ValueError("Confirm that the scan uses Z as the upward direction before reconstruction")
        token = request["job_id"]
        with generation_stage(path, state["project_id"], token) as stage:
            progress(5, "Opening working cloud")
            cloud = load_cloud(path, state)
            settings = ReconstructionSettings(**request.get("settings", {}))
            progress(20, "Finding surfaces and fitting elements")
            model = reconstruct(cloud, settings, name=state["name"])
            model.metadata["project_id"] = state["project_id"]
            if state["import_manifest"]:
                manifest = state["import_manifest"]
                model.metadata["source"] = manifest["source"]
                model.metadata["coordinate_mapping"] = manifest["coordinate_mapping"]
                model.metadata["e57"] = {"coordinate_metadata": manifest["coordinate_metadata"],
                                          "coordinate_metadata_status": manifest["coordinate_metadata_status"]}
                model.warnings.extend(manifest["warnings"])
            progress(80, "Retaining source evidence")
            evidence = stage / "evidence" / "records"
            evidence.parent.mkdir()
            write_wall_evidence(cloud, model.walls, evidence, settings.processing_chunk_points,
                                model.metadata.get("surface_proposals"))
            for wall in model.walls:
                record = wall.evidence.get("records")
                if record:
                    record["path"] = f"generations/{token}/{record['path']}"
            for proposal in model.metadata.get("surface_proposals", []):
                record = proposal.get("representative_cloud_records")
                if record:
                    record["path"] = f"generations/{token}/{record['path']}"
            model.warnings = [w for w in model.warnings if "No desktop review" not in w]
            model.warnings.append("Whole-cloud deviation reporting remains pending; review observed and inferred geometry separately.")
            state["model"] = model.to_dict()
            state["generations"] = list(dict.fromkeys([state["cloud"]["generation"], token]))
            state["coordinate_confirmation"]["z_up"] = True
            state["revision"] = uuid.uuid4().hex
            close_cloud(cloud)
            publish_generation(path, token, stage)
            atomic_json(path, state)
            progress(100, "Candidates ready for review")
            return state


def draft_model(state, data):
    model = BuildingModel.from_dict(deepcopy(data))
    if model.metadata.get("project_id") != state["project_id"]:
        raise ValueError("Model identity differs from the opened project")
    return model


def edit_model(state, data, element_id, changes):
    model = draft_model(state, data)
    element = next((obj for obj in model.walls + model.slabs + model.storeys + model.openings + model.stairs if obj.id == element_id), None)
    if element is None:
        raise ValueError("Select a supported element")
    allowed = ({"start", "end", "base", "height", "thickness", "classification", "review_state"} if element in model.walls
               else {"base", "thickness", "review_state"} if element in model.slabs
               else {"kind", "offset", "sill", "width", "height", "review_state"} if element in model.openings
               else {"start", "end", "base", "width", "rise", "going", "steps", "tread_thickness", "review_state"} if element in model.stairs
               else {"name", "elevation", "ceiling"})
    if not isinstance(changes, dict) or not changes or set(changes)-allowed:
        raise ValueError("Unsupported element correction")
    old = deepcopy(element.__dict__)
    for field, value in changes.items():
        if field == "name" and (not isinstance(value, str) or not value.strip()):
            raise ValueError("Storey name cannot be empty")
        if field in {"base", "height", "thickness", "elevation", "ceiling", "offset", "sill", "width", "rise", "going", "steps", "tread_thickness"} and (isinstance(value, bool) or not isinstance(value, (float, int))):
            raise ValueError("Dimensions must be numbers in metres")
        setattr(element, field, value)
        if field not in {"name", "review_state"}:
            element.provenance[field] = "user_supplied"
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
        levels = sorted(model.storeys, key=lambda obj: obj.elevation)
        if any(a.ceiling > b.elevation+1e-8 for a, b in zip(levels, levels[1:])):
            raise ValueError("Edited storey intervals overlap")
    geometry = set(changes)-{"review_state", "classification", "name"}
    if geometry or changes.get("review_state") == "rejected":
        model.metadata["geometry_edited"] = True
    model.metadata.setdefault("edit_history", []).append({"element_id": element_id, "changes": deepcopy(changes),
                            "quality_scope": "Observed faces and evidence describe the original fit, not the corrected geometry"})
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


def save_project(path, request):
    with project_lock(path):
        state = load_project(path)
        check_revision(state, request["expected_revision"])
        model = draft_model(state, request["model"])
        name = request.get("name", state["name"])
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Project name cannot be empty")
        model.name = state["name"] = name
        state["model"] = model.to_dict()
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
        if destination.exists():
            raise ValueError("Choose a new filename for the project copy")
        if request.get("model"):
            state["model"] = draft_model(state, request["model"]).to_dict()
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
        model = draft_model(state, request.get("model") or state["model"])
        rejected = {w.id for w in model.walls if w.review_state == "rejected"}
        model.walls = [w for w in model.walls if w.id not in rejected]
        model.slabs = [s for s in model.slabs if s.review_state != "rejected"]
        model.openings = [o for o in model.openings if o.host_wall_id not in rejected and o.review_state != "rejected"]
        model.stairs = [s for s in model.stairs if s.review_state != "rejected"]
        unresolved = sum(obj.review_state in {"unreviewed", "flagged"} for obj in model.walls + model.slabs + model.openings + model.stairs)
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
        progress(100, "IFC export complete")
        return {"output": str(target), "validation": report, "warnings": model.warnings,
                "excluded_rejected_walls": len(rejected), "spaces_omitted_after_edits": bool(model.metadata.get("geometry_edited"))}


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
