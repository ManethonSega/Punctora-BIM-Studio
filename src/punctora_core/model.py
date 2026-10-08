"""Validated, serialisable element model with explicit parameter provenance."""
from dataclasses import asdict, dataclass, field, fields
from math import isfinite, dist
from typing import Literal

Provenance = Literal["measured", "inferred", "user_supplied", "unknown"]
PROVENANCE_STATES = {"measured", "inferred", "user_supplied", "unknown"}


def positive(value: float, name: str) -> None:
    if not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and greater than zero")


def polygon_check(vertices) -> None:
    from shapely.geometry import Polygon
    if len(vertices) < 3 or not all(len(v) == 2 and all(isfinite(x) for x in v) for v in vertices):
        raise ValueError("A footprint needs at least three finite 2D vertices")
    polygon = Polygon(vertices)
    if not polygon.is_valid or polygon.area <= 0:
        raise ValueError("Footprint must be a nondegenerate, non-self-intersecting polygon")


@dataclass
class Storey:
    id: str
    name: str
    elevation: float
    ceiling: float
    footprint: list[tuple[float, float]]
    provenance: dict[str, str] = field(default_factory=lambda: {
        "elevation": "user_supplied", "ceiling": "user_supplied", "footprint": "user_supplied"})


@dataclass
class Wall:
    id: str
    storey_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    base: float
    height: float
    thickness: float
    classification: str = "unclassified"
    provenance: dict[str, str] = field(default_factory=dict)
    evidence_count: int = 0
    fit_rmse_m: float | None = None
    review_state: str = "unreviewed"
    observed_faces: list[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    detection_method: str = "contour"


@dataclass
class Slab:
    id: str
    storey_id: str
    footprint: list[tuple[float, float]]
    base: float
    thickness: float
    kind: str = "FLOOR"
    provenance: dict[str, str] = field(default_factory=dict)
    review_state: str = "unreviewed"


@dataclass
class Space:
    id: str
    storey_id: str
    footprint: list[tuple[float, float]]
    base: float
    height: float
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass
class Opening:
    id: str
    host_wall_id: str
    kind: Literal["door", "window"]
    offset: float
    sill: float
    width: float
    height: float
    provenance: dict[str, str] = field(default_factory=dict)


@dataclass
class BuildingModel:
    name: str
    storeys: list[Storey] = field(default_factory=list)
    walls: list[Wall] = field(default_factory=list)
    slabs: list[Slab] = field(default_factory=list)
    spaces: list[Space] = field(default_factory=list)
    openings: list[Opening] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "BuildingModel":
        """Load the supported data schema, never executable scene scripts."""
        if not isinstance(data, dict) or data.get("schema_version") != 2 or data.get("units") != "metres":
            raise ValueError("Unsupported element schema; schema 2 in metres is required")
        allowed = {f.name for f in fields(cls)} | {"schema_version", "units"}
        if set(data) - allowed:
            raise ValueError("Unknown element-model fields")
        parts = {}
        for key, kind in [("storeys", Storey), ("walls", Wall), ("slabs", Slab), ("spaces", Space), ("openings", Opening)]:
            values = data.get(key, [])
            if not isinstance(values, list):
                raise ValueError(f"{key} must be a list")
            accepted = {f.name for f in fields(kind)}
            if any(not isinstance(v, dict) or set(v)-accepted for v in values):
                raise ValueError(f"Unknown fields in {key}")
            try:
                parts[key] = [kind(**v) for v in values]
            except TypeError as exc:
                raise ValueError(f"Incomplete {key} records") from exc
        model = cls(name=data.get("name", ""), warnings=data.get("warnings", []),
                    metadata=data.get("metadata", {}), **parts)
        try:
            model.validate()
        except (TypeError, AttributeError, KeyError) as exc:
            raise ValueError("Malformed element-model values") from exc
        return model

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip() or not isinstance(self.metadata, dict):
            raise ValueError("Model requires a name and metadata object")
        if not isinstance(self.warnings, list) or any(not isinstance(w, str) for w in self.warnings):
            raise ValueError("Warnings must be a list of strings")
        objects = self.storeys + self.walls + self.slabs + self.spaces + self.openings
        ids = [obj.id for obj in objects]
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("Element IDs must be nonempty and unique")
        storeys = {s.id: s for s in self.storeys}
        walls = {w.id: w for w in self.walls}
        if not storeys:
            raise ValueError("A building needs at least one storey")
        for s in self.storeys:
            if not isfinite(s.elevation) or not isfinite(s.ceiling):
                raise ValueError("Storey levels must be finite")
            positive(s.ceiling - s.elevation, "Storey clear height")
            polygon_check(s.footprint)
        for obj in self.walls + self.slabs + self.spaces:
            if obj.storey_id not in storeys:
                raise ValueError(f"Unknown storey for {obj.id}")
            if not isfinite(obj.base):
                raise ValueError("Element base must be finite")
            if isinstance(obj, Wall):
                if len(obj.start) != 2 or len(obj.end) != 2 or not all(isfinite(x) for x in (*obj.start, *obj.end)):
                    raise ValueError("Wall endpoints must be finite 2D points")
                positive(dist(obj.start, obj.end), "Wall length")
                positive(obj.thickness, "Wall thickness")
                positive(obj.height, "Wall height")
                if not isinstance(obj.evidence_count, int) or obj.evidence_count < 0:
                    raise ValueError("Wall evidence count must be nonnegative")
                if obj.fit_rmse_m is not None and (not isfinite(obj.fit_rmse_m) or obj.fit_rmse_m < 0):
                    raise ValueError("Wall fit RMSE must be finite and nonnegative")
                for face in obj.observed_faces:
                    if (not all(key in face for key in ["start", "end", "z_min", "z_max"])
                            or len(face["start"]) != 2 or len(face["end"]) != 2
                            or not all(isfinite(x) for x in [*face["start"], *face["end"], face["z_min"], face["z_max"]])
                            or dist(face["start"], face["end"]) <= 0 or face["z_min"] > face["z_max"]):
                        raise ValueError("Observed wall faces require finite nondegenerate geometry")
            else:
                polygon_check(obj.footprint)
                positive(obj.thickness if isinstance(obj, Slab) else obj.height, "Extrusion depth")
        for opening in self.openings:
            if opening.host_wall_id not in walls or opening.kind not in {"door", "window"}:
                raise ValueError("Opening requires a known host wall and door/window kind")
            host = walls[opening.host_wall_id]
            positive(opening.width, "Opening width")
            positive(opening.height, "Opening height")
            if not isfinite(opening.offset) or not isfinite(opening.sill) or opening.offset < 0 or opening.sill < 0:
                raise ValueError("Opening offset and sill must be finite and nonnegative")
            if opening.offset + opening.width > dist(host.start, host.end) + 1e-8 or opening.sill + opening.height > host.height + 1e-8:
                raise ValueError("Opening exceeds its host wall")
        for obj in self.storeys + self.walls + self.slabs + self.spaces + self.openings:
            if hasattr(obj, "review_state") and obj.review_state not in {"unreviewed", "reviewed", "flagged", "rejected"}:
                raise ValueError("Unknown review state")
            if any(state not in PROVENANCE_STATES for state in obj.provenance.values()):
                raise ValueError("Unknown provenance state")

    def to_dict(self) -> dict:
        self.validate()
        return {"schema_version": 2, "units": "metres", **asdict(self)}
