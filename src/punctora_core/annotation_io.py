"""Versioned independent truth and prediction contracts, never reconstruction input."""
from copy import deepcopy
import hashlib
import json
from math import dist, isfinite
from pathlib import Path

from shapely.geometry import Polygon

CLASSES = ("wall", "door", "window", "opening", "floor", "slab", "ceiling",
           "roof", "stair", "landing", "ramp", "column")
CLASS_STATES = {"present", "absent", "uncertain", "out_of_scope"}
SUPPORT_STATES = {"measured", "justified_completion", "inferred", "unsupported", "unknown"}
MATCHING = {
    "position_m": .10, "angle_deg": 5., "minimum_iou": .25,
    "boundary_m": .05, "duplicate_iou": .95, "signature_m": 1e-6,
}


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def content_digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_digest(path, chunk_bytes=8 * 1024 * 1024, cancelled=lambda: False):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(chunk_bytes):
            if cancelled():
                raise InterruptedError("Quality evaluation cancelled")
            digest.update(block)
    return digest.hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    def reject(value):
        raise ValueError(f"Non-finite JSON constant: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=_unique_object, parse_constant=reject)


def number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def identifier(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")
    return value


def sha256(value, name):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def point(value, name, dimensions=2):
    if not isinstance(value, (list, tuple)) or len(value) != dimensions:
        raise ValueError(f"{name} must have {dimensions} coordinates")
    return [number(v, name) for v in value]


def polygon(geometry):
    shape = Polygon(geometry["footprint"], geometry.get("holes", []))
    if not shape.is_valid or shape.is_empty or shape.area <= 0:
        raise ValueError("Annotation polygon must be valid with positive area")
    return shape


def record_key(record):
    sha256(record.get("source_sha256"), "record source_sha256")
    for field in ("scan_index", "source_record_index"):
        value = record.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**64:
            raise ValueError(f"{field} must be an unsigned 64-bit integer, never a float")
    return (record["source_sha256"], record["scan_index"], record["source_record_index"])


def validate_identity(data):
    identifier(data.get("case_id"), "case_id")
    sha256(data.get("source_sha256"), "source_sha256")
    mapping = data.get("coordinate_mapping")
    if not isinstance(mapping, dict) or set(mapping) != {"translation_m", "yaw_degrees"}:
        raise ValueError("coordinate_mapping requires translation_m and yaw_degrees")
    point(mapping["translation_m"], "translation_m", 3)
    number(mapping["yaw_degrees"], "yaw_degrees")
    crop = data.get("crop")
    if crop is not None:
        from .cropping import validate_crop, crop_active
        if not isinstance(crop, dict) or set(crop) != {"polygon", "z_min", "z_max"}:
            raise ValueError("crop requires polygon, z_min and z_max in the Punctora crop contract")
        validate_crop(crop)
        if not crop_active(crop):
            raise ValueError("Use null for an inactive crop")


def identity(data):
    return {key: deepcopy(data[key]) for key in
            ("case_id", "source_sha256", "coordinate_mapping", "crop")}


def validate_geometry(geometry):
    if not isinstance(geometry, dict):
        raise ValueError("Element geometry must be an object")
    kind = geometry.get("type")
    number(geometry.get("base"), "base")
    if kind in {"wall", "opening", "stair", "ramp", "column"}:
        start, end = point(geometry.get("start"), "start"), point(geometry.get("end"), "end")
        if dist(start, end) <= 0:
            raise ValueError("Element axis must be nondegenerate")
        for field in ({"wall": ("height", "thickness"), "opening": ("height",),
                       "stair": ("width", "rise", "going"), "ramp": ("width", "rise"),
                       "column": ("width", "height")}[kind]):
            number(geometry.get(field), field, True)
        if kind == "wall" and geometry.get("profile_xz"):
            profile = Polygon(geometry["profile_xz"])
            if (not profile.is_valid or profile.area <= 0
                    or not all(0 <= x <= dist(start, end) and 0 <= z <= geometry["height"]
                               for x, z in geometry["profile_xz"])):
                raise ValueError("Wall profile must be valid and inside its envelope")
        if kind == "stair":
            steps = geometry.get("steps")
            if isinstance(steps, bool) or not isinstance(steps, int) or not 2 <= steps <= 100:
                raise ValueError("steps must be an integer between 2 and 100")
            if abs(dist(start, end) - steps * geometry["going"]) > 1e-6:
                raise ValueError("Stair run must equal steps times going")
    elif kind == "surface":
        for ring in [geometry.get("footprint", []), *geometry.get("holes", [])]:
            if len(ring) < 3:
                raise ValueError("Surface rings require at least three vertices")
            for vertex in ring:
                point(vertex, "surface vertex")
        polygon(geometry)
        point(geometry.get("plane", [0, 0, geometry["base"]]), "plane", 3)
        if "thickness" in geometry:
            number(geometry["thickness"], "thickness", True)
    else:
        raise ValueError(f"Unknown annotation geometry type: {kind}")


def validate_annotations(data, truth=True):
    data = deepcopy(data)
    if (not isinstance(data, dict) or data.get("schema_version") != 1
            or data.get("units") != "metres"):
        raise ValueError("Quality annotations require schema 1 in metres")
    validate_identity(data)
    if truth:
        identifier(data.get("truth_revision"), "truth_revision")
        if set(data.get("class_states", {})) != set(CLASSES):
            raise ValueError("Truth must declare a state for every required class")
        if any(state not in CLASS_STATES for state in data["class_states"].values()):
            raise ValueError("Unknown class truth state")
    elements = data.get("elements")
    if not isinstance(elements, list):
        raise ValueError("elements must be a list")
    ids = set()
    for element in elements:
        value = identifier(element.get("id"), "element id")
        if value in ids:
            raise ValueError("Element annotation IDs must be unique")
        ids.add(value)
        if element.get("class") not in CLASSES:
            raise ValueError("Unknown element class")
        if truth and data["class_states"][element["class"]] != "present":
            raise ValueError("Truth elements require class state present")
        if element.get("support_state", "unknown") not in SUPPORT_STATES:
            raise ValueError("Unknown support state")
        validate_geometry(element.get("geometry"))
        expected = {"wall": "wall", "door": "opening", "window": "opening", "opening": "opening",
                    "stair": "stair", "ramp": "ramp", "column": "column"}.get(element["class"], "surface")
        if element["geometry"]["type"] != expected:
            raise ValueError("Element class and geometry type disagree")
        for record in element.get("source_records", []):
            record_key(record)
        for face in element.get("observed_faces", []):
            start, end = point(face.get("start"), "face start"), point(face.get("end"), "face end")
            if (dist(start, end) == 0 or number(face.get("z_min"), "face z_min")
                    >= number(face.get("z_max"), "face z_max")):
                raise ValueError("Observed faces need a nondegenerate axis and height")
    for element in elements:
        if "host_id" in element and element["host_id"] not in ids:
            raise ValueError("Opening references a missing annotated host")
        for key in ("observed_treads", "inferred_treads"):
            values = element.get(key, [])
            if (not isinstance(values, list) or len(set(values)) != len(values)
                    or any(isinstance(v, bool) or not isinstance(v, int) or v < 0
                           or v >= element["geometry"].get("steps", 0) for v in values)):
                raise ValueError("Tread indices must be unique integers inside the flight")
        if set(element.get("observed_treads", [])) & set(element.get("inferred_treads", [])):
            raise ValueError("A tread cannot be both observed and inferred")
        connections = element.get("connections", {})
        if not isinstance(connections, dict) or set(connections) - {"lower", "upper"}:
            raise ValueError("Endpoint connections require lower/upper IDs")
        if any(v is not None and v not in ids for v in connections.values()):
            raise ValueError("Connection references a missing element")
        if any(v not in ids for v in element.get("connected_ids", [])):
            raise ValueError("Landing references a missing flight")
    samples = data.get("semantic_samples", [])
    keys = set()
    for sample in samples:
        key = record_key(sample)
        if key in keys:
            raise ValueError("Duplicate semantic source identity")
        keys.add(key)
        if sample.get("label") not in CLASSES:
            raise ValueError("Unknown semantic label")
        if "boundary" in sample and not isinstance(sample["boundary"], bool):
            raise ValueError("boundary must be a boolean")
        if truth and data["class_states"][sample["label"]] != "present":
            raise ValueError("Semantic truth requires class state present")
    if truth:
        for name, state in data["class_states"].items():
            if state == "present" and not any(e["class"] == name for e in elements):
                raise ValueError(f"Present class {name} needs at least one independent element")
        for exclusion in data.get("exclusions", []):
            identifier(exclusion.get("reason"), "exclusion reason")
            polygon(exclusion)
            if number(exclusion.get("z_min"), "z_min") >= number(exclusion.get("z_max"), "z_max"):
                raise ValueError("Exclusion vertical interval is empty")
    for cut in data.get("cuts", []):
        identifier(cut.get("id"), "cut id")
        identifier(cut.get("host_id"), "cut host")
        if not isinstance(cut.get("applied"), bool):
            raise ValueError("Cut applied flag must be boolean")
        polygon({"footprint": cut.get("footprint", [])})
    return data


def load_annotations(path, truth=True):
    return validate_annotations(read_json(path), truth)
