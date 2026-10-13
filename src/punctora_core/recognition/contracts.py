"""ProposalSet v1, source identities and provider-native scores."""
from pathlib import Path
import numpy as np

from ..annotation_io import (CLASSES, content_digest, file_digest, identifier, number,
                             read_json, sha256, validate_identity, validate_geometry)

TAXONOMY = (*CLASSES, "beam", "furnishing", "flow_controller", "flow_terminal", "energy_conversion_device")
UNSUPPORTED_BUILDING_CLASSES = list(TAXONOMY[len(CLASSES):])
UNKNOWN_LABEL = -1
PROTOCOL_VERSION = 1
ARRAY_TYPES = {"working_rows": "<u8", "scan_ids": "<u8", "record_ids": "<u8",
               "labels": "<i2", "scores": "<f4", "selected": "|b1"}


class ProviderUnavailable(RuntimeError):
    """Missing assets/device/operators, not permission to invent a result."""


def safe_artifact_path(root, value):
    path = Path(value)
    root = Path(root).resolve()
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Proposal arrays require contained relative paths")
    result = (root / path).resolve()
    if not result.is_relative_to(root):
        raise ValueError("Proposal artifact escapes its generation")
    return result


def validate_labels(labels, scores, count):
    if (labels.shape != (count,) or labels.dtype != np.dtype("<i2")
            or scores.shape != (count,) or scores.dtype != np.dtype("<f4")):
        raise ValueError("Provider output must be int16 labels and float32 native scores, one per input row")
    if np.any(labels < -1) or np.any(labels >= len(TAXONOMY)) or not np.isfinite(scores).all():
        raise ValueError("Provider emitted nonfinite scores or an unknown taxonomy index")


def array_descriptor(path, relative, array, cancelled=lambda: False):
    return {"path": relative, "dtype": array.dtype.str, "shape": list(array.shape),
            "sha256": file_digest(path, cancelled=cancelled)}


def validate_proposal_set(manifest, directory, verify_arrays=True, cancelled=lambda: False):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("ProposalSet requires schema version 1")
    validate_identity(manifest["identity"])
    if manifest.get("status") != "complete" or manifest.get("geometry_authority") != "review_only":
        raise ValueError("Only complete review-only ProposalSets are supported")
    if manifest.get("taxonomy") != list(TAXONOMY) or manifest.get("taxonomy_version") != "punctora-building-v1":
        raise ValueError("Unsupported recognition taxonomy")
    sha256(manifest.get("cache_key"), "cache key")
    provider = manifest.get("provider", {})
    for field in ("id", "version", "score_kind", "backend"):
        identifier(provider.get(field), "provider " + field)
    sha256(provider.get("fingerprint"), "provider fingerprint")
    requested = manifest.get("requested_provider", {})
    for descriptor in (provider, requested):
        if descriptor.get("fingerprint") != content_digest({k: v for k, v in descriptor.items() if k != "fingerprint"}):
            raise ValueError("Provider descriptor fingerprint changed")
    sha256(manifest.get("implementation_sha256"), "implementation digest")
    if not isinstance(manifest.get("settings"), dict) or not isinstance(manifest.get("input_digests"), dict):
        raise ValueError("ProposalSet requires fingerprinted input and settings")
    if set(manifest["input_digests"]) != {"points", "scan_ids", "record_ids", "working_rows"}:
        raise ValueError("ProposalSet requires all original input-array digests")
    for digest in manifest["input_digests"].values():
        sha256(digest, "input digest")
    expected_key = content_digest({"contract": 1, "identity": manifest["identity"],
                                  "input_digests": manifest["input_digests"],
                                  "provider": {"requested": requested, "used": provider,
                                               "implementation_sha256": manifest["implementation_sha256"]},
                                  "settings": manifest["settings"]})
    if manifest["cache_key"] != expected_key:
        raise ValueError("ProposalSet manifest changed without a new content-addressed generation")
    if manifest.get("proposal_sha256") != content_digest({k: v for k, v in manifest.items() if k != "proposal_sha256"}):
        raise ValueError("ProposalSet manifest digest changed")
    if manifest.get("overlap_rule") != "majority_count_then_lowest_taxonomy_id; score=max_native_winner_score":
        raise ValueError("Unknown deterministic overlap rule")
    count = manifest.get("source_point_count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("Source point count must be a positive integer")
    selected_count = manifest.get("selected_point_count")
    if isinstance(selected_count, bool) or not isinstance(selected_count, int) or not 0 <= selected_count <= count:
        raise ValueError("Selected point count is invalid")
    arrays = manifest.get("arrays", {})
    if set(arrays) != set(ARRAY_TYPES):
        raise ValueError("ProposalSet lacks exact source identity/label arrays")
    for name, expected in ARRAY_TYPES.items():
        descriptor = arrays[name]
        if descriptor.get("dtype") != expected or descriptor.get("shape") != [count]:
            raise ValueError("Malformed ProposalSet array descriptor")
        sha256(descriptor.get("sha256"), "array digest")
        path = safe_artifact_path(directory, descriptor["path"])
        if verify_arrays:
            if file_digest(path, cancelled=cancelled) != descriptor["sha256"]:
                raise ValueError("ProposalSet array digest changed")
            array = np.load(path, mmap_mode="r", allow_pickle=False)
            try:
                if array.shape != (count,) or array.dtype.str != expected:
                    raise ValueError("ProposalSet array layout disagrees with descriptor")
                if name in {"labels", "scores", "selected"}:
                    selected_actual = 0
                    for begin in range(0, count, 65536):
                        if cancelled():
                            raise InterruptedError("Recognition cancelled")
                        values = array[begin:begin + 65536]
                        if name == "scores" and not np.isfinite(values).all():
                            raise ValueError("Nonfinite provider scores")
                        if name == "labels" and (np.any(values < -1) or np.any(values >= len(TAXONOMY))):
                            raise ValueError("Invalid point label")
                        if name == "selected":
                            selected_actual += int(values.sum())
                    if name == "selected" and selected_actual != selected_count:
                        raise ValueError("Selected count disagrees with source mask")
            finally:
                array._mmap.close()
    if verify_arrays:
        maps = {}
        try:
            for name in ("selected", "labels", "scores", "scan_ids", "record_ids", "working_rows"):
                maps[name] = np.load(safe_artifact_path(directory, arrays[name]["path"]), mmap_mode="r", allow_pickle=False)
            import hashlib
            digests = {name: hashlib.sha256() for name in ("scan_ids", "record_ids", "working_rows")}
            for begin in range(0, count, 65536):
                if cancelled():
                    raise InterruptedError("Recognition cancelled")
                labels = maps["labels"][begin:begin + 65536]
                selected = maps["selected"][begin:begin + 65536]
                scores = maps["scores"][begin:begin + 65536]
                if np.any(labels[~selected] != -1) or np.any(scores[labels < 0] != 0):
                    raise ValueError("Unselected/unknown source rows cannot carry model labels/scores")
                for name, digest in digests.items():
                    digest.update(maps[name][begin:begin + 65536].tobytes())
            if any(digest.hexdigest() != manifest["input_digests"][name] for name, digest in digests.items()):
                raise ValueError("Proposal source IDs no longer round-trip original input")
        finally:
            for array in maps.values():
                array._mmap.close()
    instances = manifest.get("instances", [])
    ids = set()
    for instance in instances:
        identifier(instance.get("id"), "instance ID")
        if instance["id"] in ids or instance.get("class") not in CLASSES:
            raise ValueError("Duplicate instance ID or unsupported class")
        ids.add(instance["id"])
        if instance.get("status") != "proposed":
            raise ValueError("A provider cannot accept final geometry")
        identifier(instance.get("native_score_kind"), "instance native score kind")
        if instance.get("native_score") is not None:
            number(instance["native_score"], "instance native score")
        geometry = instance.get("geometry")
        if geometry is None:
            if (instance["class"] != "column" or instance.get("geometry_state") != "insufficient_for_parametric_geometry"
                    or not instance.get("evidence_ids") or "hybrid_v1" not in manifest.get("extensions", {})):
                raise ValueError("Only an evidence-backed hybrid column may retain unresolved geometry")
        else:
            validate_geometry(geometry)
        expected_type = {"floor": "surface", "slab": "surface", "ceiling": "surface", "roof": "surface",
                         "landing": "surface", "door": "opening", "window": "opening", "opening": "opening"}.get(instance["class"], instance["class"])
        if geometry is not None and geometry["type"] != expected_type:
            raise ValueError("Proposal instance class and geometry disagree")
        bounds = np.asarray(instance.get("bounds_m"), dtype=np.float64)
        if bounds.shape != (2, 3) or not np.isfinite(bounds).all() or np.any(bounds[1] < bounds[0]):
            raise ValueError("Instance requires finite bounds")
        if instance.get("support_reference") != "ProposalSet source arrays, independently revalidate before acceptance":
            raise ValueError("Instance must retain an explicit source-evidence scope")
    for instance in instances:
        if instance.get("host_id") is not None and instance["host_id"] not in ids:
            raise ValueError("Proposal instance references a missing host")
        if instance.get("host_id") is not None:
            host = next(item for item in instances if item["id"] == instance["host_id"])
            if instance["class"] not in {"door", "window", "opening"} or host["class"] != "wall":
                raise ValueError("Opening proposal hosts must be walls, never cyclic or self references")
    tile_ids = [t.get("id") for t in manifest.get("tiles", [])]
    if len(set(tile_ids)) != len(tile_ids) or any(not isinstance(i, str) or not i for i in tile_ids):
        raise ValueError("Tile definitions require unique stable IDs")
    if not isinstance(manifest.get("warnings"), list) or any(not isinstance(w, str) for w in manifest["warnings"]):
        raise ValueError("Proposal warnings must be strings")
    extensions = manifest.get("extensions", {})
    if not isinstance(extensions, dict) or set(extensions) - {"hybrid_v1"}:
        raise ValueError("Unknown ProposalSet extension")
    if "hybrid_v1" in extensions:
        from .element_graph import validate_hybrid_artifacts
        validate_hybrid_artifacts(manifest, directory, verify_arrays, cancelled)
    return manifest


def load_proposal_set(directory, **kwargs):
    return validate_proposal_set(read_json(Path(directory) / "proposals-v1.json"), directory, **kwargs)
