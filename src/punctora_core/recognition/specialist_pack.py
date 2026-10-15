"""Content-bound A through J specialist model-pack contract.

The weights stay outside the repository.  This module records the reviewed
interface and exact supplied asset identities so a same-named replacement can
never be treated as the reviewed model pack.
"""
from copy import deepcopy
from pathlib import Path

from ..annotation_io import content_digest, file_digest, identifier, sha256


SPECIALIST_PROVIDER_ID = "PunctoraSpecialistProvider"
SPECIALIST_PROVIDER_VERSION = "4.1"
MODEL_PACK_ID = "punctora-supplied-specialists-a-j"
MODEL_PACK_VERSION = "2"


def _branch(task, graph_sha256, inputs, outputs, renderer, decoder, *, companion=None):
    value = {
        "task": task,
        "graph": f"model_{task['branch']}.onnx",
        "graph_sha256": graph_sha256,
        "inputs": inputs,
        "outputs": outputs,
        "renderer": renderer,
        "decoder": decoder,
        "runtime": "onnxruntime-cpu-v2",
        "provider_version": SPECIALIST_PROVIDER_VERSION,
    }
    if companion:
        value["companion"] = f"model_{task['branch']}.onnx.data"
        value["companion_sha256"] = companion
    return value


MODEL_PACK_MANIFEST = {
    "schema_version": 1,
    "pack_id": MODEL_PACK_ID,
    "pack_version": MODEL_PACK_VERSION,
    "taxonomy_version": "punctora-building-v1",
    "runtime": {
        "id": "onnxruntime-cpu-v2",
        "execution_provider": "CPUExecutionProvider",
        "execution_mode": "sequential",
        "intra_op_threads": "explicit_job_runtime_plan",
        "inter_op_threads": 1,
        "allow_spinning": False,
        "requires_runtime_plan": True,
        "automatic_download": False,
    },
    "branches": {
        "A": _branch(
            {"branch": "A", "role": "slab_vertical_section_candidates"},
            "6de5aadeee16c9967649296992742da2e34e667fb09bc5a1edac06501d7d440d",
            [{"name": "input", "dtype": "float32", "shape": [1, 3, 560, 560]}],
            [{"name": "dets", "dtype": "float32", "shape": [1, 300, 4]},
             {"name": "labels", "dtype": "float32", "shape": [1, 300, 1]}],
            "vertical-section-physical-v1", "section-sigmoid-v1"),
        "B": _branch(
            {"branch": "B", "role": "opening_vertical_section_candidates"},
            "b1672b3665374fa57be2d328806d08bf4404e554c8e46939d4880fda68aaf375",
            [{"name": "input", "dtype": "float32", "shape": [1, 3, 560, 560]}],
            [{"name": "dets", "dtype": "float32", "shape": [1, 300, 4]},
             {"name": "labels", "dtype": "float32", "shape": [1, 300, 2]}],
            "wall-section-context-v1", "section-row-softmax-v1"),
        "C": _branch(
            {"branch": "C", "role": "beam_vertical_section_candidates"},
            "deb2d2cec23de1a1ce3c365912c0d1970315302a56c70a39e4e3a6666b7e717d",
            [{"name": "input", "dtype": "float32", "shape": [1, 3, 560, 560]}],
            [{"name": "dets", "dtype": "float32", "shape": [1, 300, 4]},
             {"name": "labels", "dtype": "float32", "shape": [1, 300, 1]}],
            "wall-section-physical-v1", "section-sigmoid-v1"),
        "D": _branch(
            {"branch": "D", "role": "wall_plan_semantic_masks"},
            "c8fb784866896b91bf22d9ca7cb440651bb32add4f7ae254cd7d250ff67fad14",
            [{"name": "input", "dtype": "float32", "shape": ["B", 1, "H", "W"]}],
            [{"name": "logits", "dtype": "float32", "shape": ["B", 3, "H", "W"]}],
            "upper-plan-six-view-v1", "mask-argmax-native-class-v1",
            companion="4758d242e870f7f6196094a5d4bc2df4ed1a533da8d5a83988dc15d61f3a5746"),
        "E": _branch(
            {"branch": "E", "role": "opening_plan_candidates"},
            "5e24a06ba2450a2548561465585d99916e1225fd33d0f8c81c735bb862719fc5",
            [{"name": "input", "dtype": "float32", "shape": ["B", 1, "H", "W"]}],
            [{"name": "logits", "dtype": "float32", "shape": ["B", 3, "H", "W"]}],
            "upper-plan-six-view-v1", "mask-argmax-and-foreground-v1"),
        "F": _branch(
            {"branch": "F", "role": "beam_plan_masks"},
            "9cfb5da2185c118dc247f88a3b3492d94be50e1c0267ed23384a497297d86dcb",
            [{"name": "input", "dtype": "float32", "shape": ["B", 1, "H", "W"]}],
            [{"name": "logits", "dtype": "float32", "shape": ["B", 2, "H", "W"]}],
            "upper-plan-six-view-v1", "mask-argmax-v1",
            companion="66b3be136f23da2b1625f2d1885865bc7218a987a24c560c8c8c73582f792399"),
        "G": _branch(
            {"branch": "G", "role": "column_plan_masks"},
            "4f4a7c2fee3b2b5d8b32fb72644f27c4dfe8f9a7c8e65b2289081596e31e158c",
            [{"name": "input", "dtype": "float32", "shape": ["B", 1, "H", "W"]}],
            [{"name": "logits", "dtype": "float32", "shape": ["B", 2, "H", "W"]}],
            "upper-plan-six-view-v1", "mask-argmax-v1",
            companion="a813fa61316d56ef17f6867853c4e3cc2aff03d6ea5538fdc37371627af0bb25"),
        "H": _branch(
            {"branch": "H", "role": "stair_plan_candidates"},
            "780623abd4b788e6fd141ed149f7670b35273ed3474d05b0ec782f54551d2a1f",
            [{"name": "input", "dtype": "float32", "shape": ["B", 1, "H", "W"]}],
            [{"name": "logits", "dtype": "float32", "shape": ["B", 2, "H", "W"]}],
            "middle-plan-six-view-v1", "mask-argmax-v1",
            companion="5bdd8e9cd6ce885a4540670a727b509b2ff63e8f8402150c0ada7651acff91ed"),
        "I": _branch(
            {"branch": "I", "role": "ptv3_point_semantic_labels"},
            "775ca536bfd691979c6a45fae388f161b3f80ba332c6bb308257b937fd08f680",
            [{"name": "feat", "dtype": "float32", "shape": ["N0", 3]},
             {"name": "39 validated index arrays", "dtype": "int64", "shape": ["dynamic"]}],
            [{"name": "seg_logits", "dtype": "float32", "shape": ["N0", 12]}],
            "stable-source-key-ptv3-grid-0.06m-v1", "point-native-logit-v1"),
        "J": _branch(
            {"branch": "J", "role": "oriented_wall_boxes"},
            "0bea57f4ecb412fbc46e96ca6fb57c4241bcfee5797ddf12897327cf081f5f1d",
            [{"name": "input", "dtype": "float32", "shape": [1, 3, 576, 576]}],
            [{"name": "dets", "dtype": "float32", "shape": [1, 300, 4]},
             {"name": "labels", "dtype": "float32", "shape": [1, 300, 3]},
             {"name": "angles", "dtype": "float32", "shape": [1, 300, 1]}],
            "wall-plan-overlay-bgr-v1", "obb-query-angle-v1"),
    },
}
_CLASS_MAPS = {
    "A": {"classifier_columns": {"0": "slab_candidate_logit"}, "emitted_local_class": 1},
    "B": {"classifier_columns": {"0": "unresolved_opening_subtype_0", "1": "unresolved_opening_subtype_1"},
          "physical_class_authority": "none"},
    "C": {"classifier_columns": {"0": "beam_candidate_logit"}, "emitted_local_class": 1},
    "D": {"0": "background", "1": "wall_foreground_unresolved_1", "2": "wall_foreground_unresolved_2"},
    "E": {"0": "background", "1": "opening_foreground_unresolved_1", "2": "opening_foreground_unresolved_2"},
    "F": {"0": "background", "1": "beam_candidate"},
    "G": {"0": "background", "1": "column_candidate"},
    "H": {"0": "background", "1": "stair_candidate"},
    "I": {"0": "wall", "1": "slab", "2": "window", "3": "column", "4": "roof", "5": "beam",
          "6": "stair", "7": "door", "8": "furnishing", "9": "flow_controller",
          "10": "flow_terminal", "11": "energy_conversion_device"},
    "J": {"0": "wall_candidate_unresolved_0", "1": "wall_candidate_unresolved_1",
          "2": "wall_candidate_unresolved_2", "physical_class_authority": "none"},
}
_PREPROCESSING = {
    "A": {"resize": "opencv_linear_560_square", "value_scale": "uint8_div_255", "channels": 3,
          "section_pixel_m_requested": .01},
    "B": {"resize": "opencv_linear_560_square", "value_scale": "uint8_div_255", "channels": 3,
          "section_pixel_m_requested": .01, "vertical_context_m": .15},
    "C": {"resize": "opencv_linear_560_square", "value_scale": "uint8_div_255", "channels": 3,
          "section_pixel_m_requested": .01},
    "D": {"resize": "opencv_linear_512_square", "normalization": "mean_0.5_std_0.5",
          "native_side_m": 10.24, "native_pixels": 1024, "dot_radius_pixels": 2},
    "E": {"resize": "opencv_linear_512_square", "normalization": "mean_0.5_std_0.5",
          "native_side_m": 10.24, "native_pixels": 1024, "dot_radius_pixels": 2},
    "F": {"resize": "opencv_linear_512_square", "normalization": "mean_0.5_std_0.5",
          "native_side_m": 10.24, "native_pixels": 1024, "dot_radius_pixels": 2},
    "G": {"resize": "opencv_linear_512_square", "normalization": "mean_0.5_std_0.5",
          "native_side_m": 10.24, "native_pixels": 1024, "dot_radius_pixels": 2},
    "H": {"resize": "opencv_linear_512_square", "normalization": "mean_0.5_std_0.5",
          "native_side_m": 20.48, "native_pixels": 2048, "dot_radius_pixels": 2},
    "I": {"feature": "original_neighbour_normal", "grid_m": .06, "maximum_patch": 128,
          "source_order": "scan_id_record_id_working_row"},
    "J": {"resize": "pillow_bilinear_576_square", "channel_order": "BGR_no_swap",
          "normalization": "imagenet_constants_applied_to_B_G_R_positions", "overlay_alpha": .5,
          "overlay_palette_bgr": {"1": [0, 0, 255], "2": [0, 255, 0]}},
}
for _name, _contract in MODEL_PACK_MANIFEST["branches"].items():
    _contract["class_map"] = _CLASS_MAPS[_name]
    _contract["preprocessing"] = _PREPROCESSING[_name]
MODEL_PACK_MANIFEST["manifest_sha256"] = content_digest(MODEL_PACK_MANIFEST)


def manifest_without_digest():
    value = deepcopy(MODEL_PACK_MANIFEST)
    value.pop("manifest_sha256")
    return value


def validate_model_pack_contract(manifest):
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Specialist model pack requires schema version 1")
    if manifest.get("pack_id") != MODEL_PACK_ID or manifest.get("pack_version") != MODEL_PACK_VERSION:
        raise ValueError("Unsupported specialist model-pack identity")
    if manifest.get("manifest_sha256") != content_digest({k: v for k, v in manifest.items() if k != "manifest_sha256"}):
        raise ValueError("Specialist model-pack manifest digest changed")
    if set(manifest.get("branches", {})) != set("ABCDEFGHIJ"):
        raise ValueError("Specialist model pack must bind all branches A through J")
    for name, branch in manifest["branches"].items():
        if branch.get("task", {}).get("branch") != name:
            raise ValueError("Specialist branch/task identity mismatch")
        for key in ("graph", "renderer", "decoder", "runtime", "provider_version"):
            identifier(branch.get(key), f"specialist {name} {key}")
        sha256(branch.get("graph_sha256"), f"specialist {name} graph digest")
        if (not isinstance(branch.get("inputs"), list) or not isinstance(branch.get("outputs"), list)
                or not isinstance(branch.get("class_map"), dict)
                or not isinstance(branch.get("preprocessing"), dict)):
            raise ValueError("Specialist branches require tensor, class and preprocessing contracts")
        if "companion" in branch:
            sha256(branch.get("companion_sha256"), f"specialist {name} companion digest")
    return manifest


def resolve_model_pack(root, cancelled=lambda: False):
    """Return actual content identity without exposing local asset paths."""
    root = Path(root)
    manifest = validate_model_pack_contract(deepcopy(MODEL_PACK_MANIFEST))
    result, missing = {}, []
    for name, branch in manifest["branches"].items():
        graph = root / branch["graph"]
        companion = root / branch["companion"] if branch.get("companion") else None
        if not graph.is_file() or (companion is not None and not companion.is_file()):
            missing.append(name)
            result[name] = {"status": "missing", "graph_sha256": None, "companion_sha256": None}
            continue
        graph_digest = file_digest(graph, cancelled=cancelled)
        if graph_digest != branch["graph_sha256"]:
            raise ValueError(f"Specialist branch {name} graph digest mismatch")
        companion_digest = file_digest(companion, cancelled=cancelled) if companion else None
        if companion and companion_digest != branch["companion_sha256"]:
            raise ValueError(f"Specialist branch {name} companion digest mismatch")
        result[name] = {"status": "available", "graph_sha256": graph_digest,
                        "companion_sha256": companion_digest,
                        "graph_bytes": graph.stat().st_size,
                        "companion_bytes": companion.stat().st_size if companion else 0}
    return manifest, result, missing
