"""Fingerprint original typed input and export labels without exposing truth."""
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import numpy as np

from ..annotation_io import (CLASSES, content_digest, file_digest, read_json, record_key,
                             validate_annotations, validate_identity)
from ..cloud_io import CloudData
from ..quality_benchmark import write_report
from .contracts import TAXONOMY, load_proposal_set, safe_artifact_path, open_proposal_array


@contextmanager
def load_input(manifest_path):
    """Read-only f64 .npy source arrays, never preview/decimated coordinates."""
    path = Path(manifest_path)
    manifest = read_json(path)
    if set(manifest) != {"schema_version", "identity", "arrays", "source_scope"} or manifest.get("schema_version") != 1:
        raise ValueError("Recognition input requires schema 1, identity, typed arrays and source_scope")
    if manifest["source_scope"] != "complete_original_registered_cloud":
        raise ValueError("Recognition normals require the complete original registered cloud")
    validate_identity(manifest["identity"])
    arrays = manifest["arrays"]
    if (not {"points", "scan_ids", "record_ids", "working_rows"} <= set(arrays)
            or set(arrays) - {"points", "scan_ids", "record_ids", "working_rows", "colors", "color_valid"}):
        raise ValueError("Recognition input requires original points and all source-row identities")
    opened = {}
    try:
        for name, descriptor in arrays.items():
            artifact = safe_artifact_path(path.parent, descriptor["path"])
            if file_digest(artifact) != descriptor["sha256"]:
                raise ValueError("Recognition input-array digest mismatch: " + name)
            value = np.load(artifact, mmap_mode="r", allow_pickle=False)
            opened[name] = value
            dtype = "<f8" if name in {"points", "colors"} else "|b1" if name == "color_valid" else "<u8"
            if value.dtype.str != dtype or list(value.shape) != descriptor["shape"] or descriptor["dtype"] != dtype:
                raise ValueError("Recognition input must preserve f64 geometry and uint64 identity")
        count = len(opened["points"])
        if opened["points"].shape != (count, 3) or any(opened[n].shape != ((count, 3) if n == "colors" else (count,)) for n in arrays if n != "points"):
            raise ValueError("Recognition input arrays must have equal source lengths")
        cloud = CloudData(opened["points"], colors=opened.get("colors"), color_valid=opened.get("color_valid"),
                          scan_index=opened["scan_ids"], source_record_index=opened["record_ids"],
                          working_index=opened["working_rows"], metadata={"source_scope": manifest["source_scope"]})
        yield cloud, manifest["identity"]
    finally:
        for value in opened.values():
            value._mmap.close()


def export_semantic_samples(proposal_directory, sample_keys, output=None):
    """Export only explicitly requested source keys after inference completes.

    sample_keys contains IDs only, never label/truth/element/class-state fields.
    Evaluation truth stays in the separate Run 1 evaluator. Unsupported or
    unknown labels are omitted with visible diagnostics, not remapped.
    """
    directory = Path(proposal_directory)
    manifest = load_proposal_set(directory)
    if not isinstance(sample_keys, list) or len(sample_keys) > 100_000:
        raise ValueError("Semantic export requires at most 100000 independently selected ID-only keys")
    expected = {"source_sha256", "scan_index", "source_record_index"}
    keys = []
    for item in sample_keys:
        if not isinstance(item, dict) or set(item) != expected:
            raise ValueError("Semantic sample selection accepts source IDs only; no labels or annotations")
        key = record_key(item)
        if key[0] != manifest["identity"]["source_sha256"]:
            raise ValueError("Semantic sample source differs from recognition source")
        keys.append(key)
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate semantic sample key")
    requested = {(key[1], key[2]): key for key in keys}
    samples, missing, unsupported, outside = [], set(requested), 0, 0
    arrays = {}
    try:
        for name in ("scan_ids", "record_ids", "labels", "selected"):
            arrays[name] = open_proposal_array(directory, manifest['arrays'][name])
        for begin in range(0, manifest["source_point_count"], 65536):
            for offset, (scan, record) in enumerate(zip(arrays["scan_ids"][begin:begin + 65536], arrays["record_ids"][begin:begin + 65536])):
                pair = (int(scan), int(record))
                if pair not in requested:
                    continue
                missing.discard(pair)
                row = begin + offset
                label = int(arrays["labels"][row])
                if not arrays["selected"][row]:
                    outside += 1
                elif 0 <= label < len(CLASSES):
                    samples.append({"source_sha256": requested[pair][0], "scan_index": pair[0],
                                    "source_record_index": pair[1], "label": TAXONOMY[label]})
                else:
                    unsupported += 1
    finally:
        for value in arrays.values():
            value._mmap.close()
    samples.sort(key=record_key)
    result = {"schema_version": 1, "units": "metres", **deepcopy(manifest["identity"]),
              "elements": [], "semantic_samples": samples,
              "proposal_cache_key": manifest["cache_key"],
              "sample_selection_sha256": content_digest(sorted(sample_keys, key=record_key)),
              "export_diagnostics": {"requested": len(keys), "exported": len(samples), "missing_original_ids": len(missing),
                                     "unknown_or_unsupported_labels": unsupported, "outside_crop": outside}}
    validate_annotations(result, truth=False)
    if output is not None:
        destination = Path(output).resolve()
        if destination == directory.resolve() or destination.is_relative_to(directory.resolve()):
            raise ValueError("Semantic export cannot overwrite an immutable proposal generation")
        write_report(destination, result)
    return result
