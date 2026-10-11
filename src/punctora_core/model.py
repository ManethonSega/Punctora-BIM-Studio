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
    confidence: float | None = None
    evidence: dict = field(default_factory=dict)
    preview_geometry: dict = field(default_factory=dict)


@dataclass
class SlabOpening:
    id: str
    host_slab_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    width: float
    source_stair_id: str | None = None
    provenance: dict[str, str] = field(default_factory=dict)
    review_state: str = "unreviewed"
    confidence: float | None = None
    evidence: dict = field(default_factory=dict)
    footprint: list[tuple[float, float]] | None = None
    source_system_id: str | None = None
    preview_geometry: dict = field(default_factory=dict)
    ifc_cut_approved: bool = False


def confirmed_stair_geometry(stair) -> bool:
    """Require explicit acceptance or independently fitted tread observations."""
    if stair.review_state in {"rejected", "flagged"}:
        return False
    if stair.review_state == "reviewed":
        return True
    if stair.evidence.get("source_geometry_changed"):
        return False
    return (stair.evidence.get("method") == "global_tread_riser_lattice"
            and len(stair.evidence.get("observed_step_indices", [])) >= 3
            and sum(count > 0 for count in stair.evidence.get("tread_support_counts", [])) >= 3)


def confirmed_landing_geometry(landing) -> bool:
    if landing.review_state in {"rejected", "flagged"}:
        return False
    if landing.review_state == "reviewed":
        return True
    return (not landing.evidence.get("source_geometry_changed")
            and landing.evidence.get("method") == "horizontal_patch_at_flight_endpoint"
            and landing.evidence.get("support_points", 0) >= 20)


def slab_opening_is_validated(opening, stairs=(), landings=()) -> bool:
    """One fail-closed policy for legacy projects, preview and IFC geometry."""
    if opening.review_state == "rejected":
        return False
    if opening.ifc_cut_approved:
        return True
    if (opening.review_state == "flagged" or opening.evidence.get("source_geometry_changed")
            or opening.evidence.get("host_geometry_changed")):
        return False
    if opening.evidence.get("validation_state") != "validated":
        return False
    basis = opening.evidence.get("validation_basis")
    if basis == "confirmed_stair_geometry":
        ids = opening.evidence.get("source_stair_ids", [])
        sources = {stair.id: stair for stair in stairs}
        landing_ids = opening.evidence.get("source_landing_ids", [])
        landing_sources = {landing.id: landing for landing in landings}
        return (bool(ids) and all(i in sources and confirmed_stair_geometry(sources[i]) for i in ids)
                and all(i in landing_sources and confirmed_landing_geometry(landing_sources[i]) for i in landing_ids))
    return basis in {"matching_faces", "vertical_reveals", "confirmed_shaft_geometry"}


def slab_opening_footprint(opening: SlabOpening) -> list[tuple[float, float]]:
    if opening.footprint is not None:
        return opening.footprint
    length = dist(opening.start, opening.end)
    positive(length, "Slab opening length")
    dx = (opening.end[0]-opening.start[0])/length
    dy = (opening.end[1]-opening.start[1])/length
    side_x, side_y = -dy*opening.width/2, dx*opening.width/2
    return [(opening.start[0]-side_x, opening.start[1]-side_y),
            (opening.end[0]-side_x, opening.end[1]-side_y),
            (opening.end[0]+side_x, opening.end[1]+side_y),
            (opening.start[0]+side_x, opening.start[1]+side_y)]


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
    kind: Literal["door", "window", "unknown"]
    offset: float
    sill: float
    width: float
    height: float
    provenance: dict[str, str] = field(default_factory=dict)
    review_state: str = "unreviewed"
    confidence: float | None = None
    evidence: dict = field(default_factory=dict)


@dataclass
class Stair:
    id: str
    storey_id: str
    start: tuple[float, float]
    end: tuple[float, float]
    base: float
    width: float
    rise: float
    going: float
    steps: int
    tread_thickness: float = 0.06
    provenance: dict[str, str] = field(default_factory=dict)
    review_state: str = "unreviewed"
    confidence: float | None = None
    evidence: dict = field(default_factory=dict)
    system_id: str | None = None
    flight_index: int = 0


@dataclass
class Landing:
    id: str
    storey_id: str
    footprint: list[tuple[float, float]]
    base: float
    thickness: float = 0.12
    system_id: str | None = None
    connected_stair_ids: list[str] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)
    review_state: str = "unreviewed"
    confidence: float | None = None
    evidence: dict = field(default_factory=dict)
    preview_geometry: dict = field(default_factory=dict)


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
    stairs: list[Stair] = field(default_factory=list)
    landings: list[Landing] = field(default_factory=list)
    slab_openings: list[SlabOpening] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "BuildingModel":
        """Load the supported data schema, never executable scene scripts."""
        if not isinstance(data, dict) or data.get("schema_version") != 2 or data.get("units") != "metres":
            raise ValueError("Unsupported element schema; schema 2 in metres is required")
        allowed = {f.name for f in fields(cls)} | {"schema_version", "units"}
        if set(data) - allowed:
            raise ValueError("Unknown element-model fields")
        parts = {}
        for key, kind in [("storeys", Storey), ("walls", Wall), ("slabs", Slab),
                          ("spaces", Space), ("openings", Opening), ("stairs", Stair),
                          ("landings", Landing),
                          ("slab_openings", SlabOpening)]:
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
        objects = (self.storeys + self.walls + self.slabs + self.spaces + self.openings
                   + self.stairs + self.landings + self.slab_openings)
        ids = [obj.id for obj in objects]
        if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
            raise ValueError("Element IDs must be nonempty and unique")
        storeys = {s.id: s for s in self.storeys}
        walls = {w.id: w for w in self.walls}
        slabs = {s.id: s for s in self.slabs}
        stairs = {s.id: s for s in self.stairs}
        if not storeys:
            raise ValueError("A building needs at least one storey")
        for s in self.storeys:
            if not isfinite(s.elevation) or not isfinite(s.ceiling):
                raise ValueError("Storey levels must be finite")
            positive(s.ceiling - s.elevation, "Storey clear height")
            polygon_check(s.footprint)
        for obj in self.walls + self.slabs + self.spaces + self.landings:
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
            elif isinstance(obj, (Slab, Space)):
                polygon_check(obj.footprint)
                positive(obj.thickness if isinstance(obj, Slab) else obj.height, "Extrusion depth")
            else:
                polygon_check(obj.footprint)
                positive(obj.thickness, "Landing thickness")
                if obj.system_id is not None and (not isinstance(obj.system_id, str) or not obj.system_id):
                    raise ValueError("Landing system ID must be a nonempty string")
                if (not isinstance(obj.connected_stair_ids, list)
                        or any(not isinstance(value, str) or not value for value in obj.connected_stair_ids)):
                    raise ValueError("Landing connections must be stair IDs")
        for opening in self.openings:
            if opening.host_wall_id not in walls or opening.kind not in {"door", "window", "unknown"}:
                raise ValueError("Opening requires a known host wall and door/window/unknown kind")
            host = walls[opening.host_wall_id]
            positive(opening.width, "Opening width")
            positive(opening.height, "Opening height")
            if not isfinite(opening.offset) or not isfinite(opening.sill) or opening.offset < 0 or opening.sill < 0:
                raise ValueError("Opening offset and sill must be finite and nonnegative")
            if opening.offset + opening.width > dist(host.start, host.end) + 1e-8 or opening.sill + opening.height > host.height + 1e-8:
                raise ValueError("Opening exceeds its host wall")
        for stair in self.stairs:
            if stair.storey_id not in storeys or not isfinite(stair.base):
                raise ValueError("Stair requires a known storey and finite base")
            if len(stair.start) != 2 or len(stair.end) != 2 or not all(isfinite(x) for x in (*stair.start, *stair.end)):
                raise ValueError("Stair endpoints must be finite 2D points")
            positive(dist(stair.start, stair.end), "Stair length")
            for key in ["width", "rise", "going", "tread_thickness"]:
                positive(getattr(stair, key), "Stair " + key)
            if not isinstance(stair.steps, int) or isinstance(stair.steps, bool) or not 2 <= stair.steps <= 100:
                raise ValueError("Stair steps must be an integer between 2 and 100")
            if abs(dist(stair.start, stair.end)-stair.going*stair.steps) > 1e-6:
                raise ValueError("Stair run must equal steps times going")
            if stair.system_id is not None and (not isinstance(stair.system_id, str) or not stair.system_id):
                raise ValueError("Stair system ID must be a nonempty string")
            if not isinstance(stair.flight_index, int) or isinstance(stair.flight_index, bool) or stair.flight_index < 0:
                raise ValueError("Stair flight index must be a nonnegative integer")
        for landing in self.landings:
            if any(stair_id not in stairs for stair_id in landing.connected_stair_ids):
                raise ValueError("Landing references an unknown stair flight")
            if (landing.system_id is not None and any(
                    stairs[stair_id].system_id not in {None, landing.system_id}
                    for stair_id in landing.connected_stair_ids)):
                raise ValueError("Landing and connected flights require one stair system")
        for opening in self.slab_openings:
            if not isinstance(opening.ifc_cut_approved, bool):
                raise ValueError("Slab cut approval must be a boolean")
            if opening.host_slab_id not in slabs:
                raise ValueError("Slab opening requires a known host slab")
            if opening.source_stair_id is not None and opening.source_stair_id not in stairs:
                raise ValueError("Slab opening source stair is unknown")
            if opening.source_system_id is not None and (not isinstance(opening.source_system_id, str)
                                                         or not opening.source_system_id):
                raise ValueError("Slab opening source system must be a nonempty string")
            if (len(opening.start) != 2 or len(opening.end) != 2
                    or not all(isfinite(x) for x in (*opening.start, *opening.end))):
                raise ValueError("Slab opening endpoints must be finite 2D points")
            positive(dist(opening.start, opening.end), "Slab opening length")
            positive(opening.width, "Slab opening width")
            footprint = slab_opening_footprint(opening)
            polygon_check(footprint)
            from shapely.geometry import Polygon
            if not Polygon(slabs[opening.host_slab_id].footprint).buffer(1e-8).covers(Polygon(footprint)):
                raise ValueError("Slab opening must lie inside its host slab footprint")
        for obj in objects:
            if hasattr(obj, "preview_geometry"):
                if not isinstance(obj.preview_geometry, dict):
                    raise ValueError("Preview geometry must be an object")
                for key in ("surface_triangles_xy", "boundary_rings_xy"):
                    for ring in obj.preview_geometry.get(key, []):
                        if (not isinstance(ring, (list, tuple)) or len(ring) < 3
                                or (key == "surface_triangles_xy" and len(ring) != 3)
                                or not all(len(p) == 2 and all(isfinite(x) for x in p) for p in ring)):
                            raise ValueError("Preview requires finite polygon/triangle coordinates")
            if hasattr(obj, "confidence") and obj.confidence is not None and (not isfinite(obj.confidence) or not 0 <= obj.confidence <= 1):
                raise ValueError("Candidate confidence must lie between zero and one")
            if hasattr(obj, "evidence") and not isinstance(obj.evidence, dict):
                raise ValueError("Element evidence must be an object")
            if hasattr(obj, "review_state") and obj.review_state not in {"unreviewed", "reviewed", "flagged", "rejected"}:
                raise ValueError("Unknown review state")
            if any(state not in PROVENANCE_STATES for state in obj.provenance.values()):
                raise ValueError("Unknown provenance state")

    def to_dict(self) -> dict:
        self.validate()
        result = {"schema_version": 2, "units": "metres", **asdict(self)}
        # Derived mesh, rebuilt on every serialization so editing/removing a
        # void cannot leave a stale solid in the desktop. Never used for IFC.
        from shapely import constrained_delaunay_triangles
        from shapely.geometry import Polygon
        from shapely.ops import unary_union
        def preview_mesh(shape, scope):
            pieces = [] if shape.is_empty else ([shape] if isinstance(shape, Polygon) else list(shape.geoms))
            # Desktop-only contours. Keep the exact mesh and model footprint
            # for evidence and export; never simplify the IFC geometry.
            render_shape = shape.simplify(.002, preserve_topology=True)
            if (not render_shape.is_valid or render_shape.is_empty
                    or shape.symmetric_difference(render_shape).area > max(1e-6, shape.area * .001)):
                render_shape = shape
            render_pieces = [] if render_shape.is_empty else ([render_shape] if isinstance(render_shape, Polygon) else list(render_shape.geoms))
            return {
                "surface_triangles_xy": [list(t.exterior.coords)[:-1]
                    for t in constrained_delaunay_triangles(shape).geoms],
                "boundary_rings_xy": [list(r.coords)[:-1] for p in pieces
                    for r in [p.exterior, *p.interiors]],
                "render_surface_triangles_xy": [list(t.exterior.coords)[:-1]
                    for t in constrained_delaunay_triangles(render_shape).geoms],
                "render_boundary_rings_xy": [list(r.coords)[:-1] for p in render_pieces
                    for r in [p.exterior, *p.interiors]],
                "render_simplification_tolerance_m": .002,
                "scope": scope}
        for slab in result["slabs"]:
            holes = [Polygon(slab_opening_footprint(o)) for o in self.slab_openings
                     if o.host_slab_id == slab["id"] and slab_opening_is_validated(o, self.stairs, self.landings)]
            shape = Polygon(slab["footprint"]).difference(unary_union(holes))
            slab["preview_geometry"] = preview_mesh(shape, "derived current footprint minus validated slab cuts")
        for landing in result["landings"]:
            landing["preview_geometry"] = preview_mesh(Polygon(landing["footprint"]), "derived current landing footprint")
        for opening, source in zip(result["slab_openings"], self.slab_openings):
            opening["preview_geometry"] = preview_mesh(Polygon(slab_opening_footprint(source)), "derived current slab opening footprint")
            eligible = slab_opening_is_validated(source, self.stairs, self.landings)
            opening["preview_geometry"]["ifc_cut_eligible"] = eligible
            if not eligible:
                # A thin horizontal ribbon stays visible in a top-down view;
                # the desktop places it above the filled slab, independently
                # of the exact candidate polygon retained for review.
                ribbon = Polygon(slab_opening_footprint(source)).boundary.buffer(.015, join_style=2)
                marker = preview_mesh(ribbon, "review outline only; never an IFC solid")
                opening["preview_geometry"]["review_surface_triangles_xy"] = marker["render_surface_triangles_xy"]
                opening["preview_geometry"]["review_boundary_rings_xy"] = marker["render_boundary_rings_xy"]
        return result
