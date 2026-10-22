"""Fail-closed validation for Run 4 specialist artifacts."""
import numpy as np

from ..annotation_io import file_digest, read_json, sha256
from .contracts import safe_artifact_path
from .specialist_pack import (MODEL_PACK_MANIFEST, SPECIALIST_PROVIDER_ID,
                              SPECIALIST_PROVIDER_VERSION, validate_model_pack_contract)


def _finite_points(values, dimensions=2):
    array = np.asarray(values, dtype=np.float64)
    return array.ndim == 2 and array.shape[1] == dimensions and len(array) >= 1 and np.isfinite(array).all()


def validate_specialist_artifacts(manifest, directory, verify_arrays=True, cancelled=lambda: False):
    extension = manifest["extensions"]["specialist_v1"]
    if (extension.get("schema_version") != 1
            or extension.get("provider_id") != SPECIALIST_PROVIDER_ID
            or extension.get("provider_version") != SPECIALIST_PROVIDER_VERSION
            or extension.get("geometry_authority") != "review_only"):
        raise ValueError("Unsupported specialist artifact contract")
    if manifest["requested_provider"].get("id") != SPECIALIST_PROVIDER_ID:
        raise ValueError("Specialist artifacts require a truthful requested provider")
    sha256(extension.get("model_pack_manifest_sha256"), "specialist model-pack manifest digest")
    branches = extension.get("branches")
    if not isinstance(branches, dict) or set(branches) != set("ABCDEFGHIJ"):
        raise ValueError("Specialist artifacts must report every A through J branch")
    for name, branch in branches.items():
        if branch.get("status") not in {"active", "missing", "failed"}:
            raise ValueError("Specialist branch status is not truthful/recognized")
        if branch.get("task", {}).get("branch") != name:
            raise ValueError("Specialist branch task identity changed")
        if branch["status"] == "active":
            sha256(branch.get("graph_sha256"), f"specialist {name} graph digest")
        if branch["status"] == "failed" and not isinstance(branch.get("failure"), str):
            raise ValueError("Failed specialist branch requires a visible reason")
    runtime = extension.get("runtime")
    if (not isinstance(runtime, dict) or runtime.get("id") != "onnxruntime"
            or runtime.get("actual_provider") != "CPUExecutionProvider"):
        raise ValueError("Specialist runtime/backend identity is missing")
    for field in ("original_source_population", "point_model_view_population"):
        value = extension.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Invalid specialist population counter")
    if extension["original_source_population"] != manifest["source_point_count"]:
        raise ValueError("Specialist original population differs from ProposalSet source")
    if any(extension.get(field) != 0 for field in ("accepted_geometry_changes", "accepted_cuts", "ifc_objects_written")):
        raise ValueError("Run 4 specialist artifacts cannot accept geometry, cuts or IFC")
    artifacts = extension.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Specialist artifacts require content-bound files")
    paths = []
    for artifact in artifacts:
        path = artifact.get("path")
        if not isinstance(path, str) or not path.startswith("specialist/"):
            raise ValueError("Specialist artifact path must remain inside its generation")
        paths.append(path)
        sha256(artifact.get("sha256"), "specialist artifact digest")
        resolved = safe_artifact_path(directory, path)
        if verify_arrays and file_digest(resolved, cancelled=cancelled) != artifact["sha256"]:
            raise ValueError("Specialist artifact digest changed")
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate specialist artifact path")
    for required in (extension.get("views_path"), extension.get("proposals_path"),
                     extension.get("support_index_path"), extension.get("support_rows", {}).get("path"),
                     "specialist/model-pack-v1.json", "specialist/runtime-v1.json"):
        if required not in paths:
            raise ValueError("Specialist generation is missing a required artifact")
    model_pack = read_json(safe_artifact_path(directory, "specialist/model-pack-v1.json"))
    validate_model_pack_contract(model_pack)
    if model_pack != MODEL_PACK_MANIFEST or model_pack["manifest_sha256"] != extension["model_pack_manifest_sha256"]:
        raise ValueError("Specialist artifact uses an unreviewed model-pack contract")
    if manifest["requested_provider"].get("model_pack_manifest_sha256") != model_pack["manifest_sha256"]:
        raise ValueError("Requested specialist provider/model-pack identity differs from its artifacts")
    for name, branch in branches.items():
        if branch["status"] == "active" and branch.get("graph_sha256") != model_pack["branches"][name]["graph_sha256"]:
            raise ValueError("Active specialist branch graph differs from the model-pack contract")
    runtime_artifact = read_json(safe_artifact_path(directory, "specialist/runtime-v1.json"))
    if runtime_artifact.get("status") != "complete" or runtime_artifact.get("runtime") != runtime:
        raise ValueError("Specialist runtime artifact differs from the published backend")
    views = read_json(safe_artifact_path(directory, extension["views_path"]))
    if views.get("schema_version") != 1 or views.get("coordinate_authority") != "original f64 source mapping":
        raise ValueError("Specialist view manifest lost its coordinate authority")
    if not isinstance(views.get("views"), list):
        raise ValueError("Specialist views must be a list")
    for view in views["views"]:
        if view.get("branch") not in set("ABCDEFGHJ") or not isinstance(view.get("frame"), dict):
            raise ValueError("Malformed specialist view identity/frame")
        frame = view["frame"]
        if not isinstance(frame.get("frame_id"), str) or not frame["frame_id"]:
            raise ValueError("Specialist view requires a stable frame ID")
        if frame.get("row_direction") not in {"row_zero_is_positive_v", "row_zero_is_positive_z"}:
            raise ValueError("Specialist frame row convention changed")
    proposals = read_json(safe_artifact_path(directory, extension["proposals_path"]))
    if proposals.get("schema_version") != 1 or proposals.get("geometry_authority") != "review_only":
        raise ValueError("Specialist proposals cannot become geometry authority")
    if not isinstance(proposals.get("proposals"), list):
        raise ValueError("Specialist proposals must be a list")
    ids = set()
    for proposal in proposals["proposals"]:
        if proposal.get("status") != "proposed" or proposal.get("geometry_authority") != "review_only":
            raise ValueError("Specialist proposal was promoted without geometry validation")
        identifier = proposal.get("id")
        if identifier is not None:
            if not isinstance(identifier, str) or not identifier or identifier in ids:
                raise ValueError("Specialist proposal IDs must be unique")
            ids.add(identifier)
        if "polygon_xy_m" in proposal and not _finite_points(proposal["polygon_xy_m"]):
            raise ValueError("Specialist proposal polygon is malformed")
        if "polygon_xy_m" in proposal:
            from shapely.geometry import Polygon
            shape = Polygon(proposal["polygon_xy_m"])
            if not shape.is_valid or shape.is_empty or shape.area <= 0:
                raise ValueError("Specialist proposal polygon has no valid area")
            z = np.asarray([proposal.get("z_min_m"), proposal.get("z_max_m")], dtype=np.float64)
            if not np.isfinite(z).all() or z[1] <= z[0]:
                raise ValueError("Specialist proposal vertical interval is malformed")
        if "world" in proposal:
            world = proposal["world"]
            if not _finite_points([world.get("start"), world.get("end")]):
                raise ValueError("Specialist section mapping is malformed")
        if proposal.get("source_support") != {"kind": "specialist_support_index", "key": identifier}:
            raise ValueError("Specialist proposal lost its original-source support key")
    instances = manifest.get("instances")
    if not isinstance(instances, list):
        raise ValueError("Specialist instances must be a list")
    instance_ids = set()
    for instance in instances:
        identifier = instance.get("id")
        if (not isinstance(identifier, str) or not identifier or identifier in ids
                or identifier in instance_ids):
            raise ValueError("Specialist instance IDs must be unique")
        instance_ids.add(identifier)
        if instance.get("source_support") != {"kind": "specialist_support_index", "key": identifier}:
            raise ValueError("Specialist instance lost its original-source support key")
    tta = extension.get("tta_diagnostics")
    if not isinstance(tta, list):
        raise ValueError("Specialist TTA diagnostics must be a list")
    for item in tta:
        if (not isinstance(item, dict) or item.get("branch") not in set("DEFGH")
                or isinstance(item.get("candidate_points"), bool)
                or not isinstance(item.get("candidate_points"), int)
                or item["candidate_points"] < 0
                or isinstance(item.get("selected_foreground_points"), bool)
                or not isinstance(item.get("selected_foreground_points"), int)
                or not 0 <= item["selected_foreground_points"] <= item["candidate_points"]):
            raise ValueError("Malformed specialist TTA diagnostic")
        for field in ("foreground_vote_histogram", "selected_native_subclass_counts"):
            counts = item.get(field)
            if (not isinstance(counts, list) or not counts
                    or any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts)):
                raise ValueError("Malformed specialist TTA vote counts")
    support = extension.get("support_rows", {})
    if (support.get("dtype") != "<u8" or not isinstance(support.get("shape"), list)
            or len(support["shape"]) != 1 or support["shape"][0] < 0):
        raise ValueError("Malformed specialist source-support array descriptor")
    sha256(support.get("sha256"), "specialist support array digest")
    if support.get("path") not in paths or next(item["sha256"] for item in artifacts
                                                if item["path"] == support["path"]) != support["sha256"]:
        raise ValueError("Specialist source-support array is not content-bound")
    support_index = read_json(safe_artifact_path(directory, extension["support_index_path"]))
    if (support_index.get("schema_version") != 1
            or support_index.get("coordinate_authority") != "ProposalSet source-array row indices"
            or not isinstance(support_index.get("entries"), list)):
        raise ValueError("Malformed specialist source-support index")
    expected_ids = ids | instance_ids
    entries = support_index["entries"]
    if [item.get("id") for item in entries] != sorted(expected_ids):
        raise ValueError("Specialist source-support index does not cover every proposal")
    offset = 0
    for entry in entries:
        if (entry.get("offset") != offset or isinstance(entry.get("count"), bool)
                or not isinstance(entry.get("count"), int) or entry["count"] < 0):
            raise ValueError("Specialist source-support offsets are not contiguous")
        offset += entry["count"]
    if offset != support["shape"][0]:
        raise ValueError("Specialist source-support count differs from its index")
    if verify_arrays:
        rows = np.load(safe_artifact_path(directory, support["path"]), mmap_mode="r", allow_pickle=False)
        try:
            if rows.dtype.str != "<u8" or list(rows.shape) != support["shape"]:
                raise ValueError("Specialist source-support storage disagrees with its descriptor")
            if len(rows) and int(rows.max()) >= manifest["source_point_count"]:
                raise ValueError("Specialist source-support row escapes the ProposalSet source")
            for entry in entries:
                part = rows[entry["offset"]:entry["offset"] + entry["count"]]
                if len(part) > 1 and np.any(part[1:] <= part[:-1]):
                    raise ValueError("Specialist source-support rows must be sorted and unique")
        finally:
            rows._mmap.close()
    expected_arrays = {"agreement": "|u1", "vote_count": "<u4", "margin": "<f4"}
    arrays = extension.get("point_arrays", {})
    if set(arrays) not in (set(), set(expected_arrays)):
        raise ValueError("Specialist point diagnostics must be complete or absent")
    for name, expected in expected_arrays.items():
        if name not in arrays:
            continue
        descriptor = arrays[name]
        if descriptor.get("dtype") != expected or descriptor.get("shape") != [manifest["source_point_count"]]:
            raise ValueError("Malformed specialist point diagnostic array")
        sha256(descriptor.get("sha256"), "specialist point-array digest")
        if descriptor.get("path") not in paths:
            raise ValueError("Specialist point-array descriptor is not content-bound")
        if verify_arrays:
            value = np.load(safe_artifact_path(directory, descriptor["path"]), mmap_mode="r", allow_pickle=False)
            try:
                if value.dtype.str != expected or list(value.shape) != descriptor["shape"]:
                    raise ValueError("Specialist point-array storage disagrees with its descriptor")
                if name == "margin" and not np.isfinite(value).all():
                    raise ValueError("Specialist margins must be finite")
            finally:
                value._mmap.close()
    return extension
