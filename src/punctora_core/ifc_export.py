"""IFC4 export, stable identities, spatial decomposition and deterministic checks."""
import json
import os
import tempfile
import uuid
from pathlib import Path
import numpy as np
import ifcopenshell
import ifcopenshell.api
import ifcopenshell.geom
import ifcopenshell.validate

from . import __version__
from .ifc_geometry import IFCGeometry
from .model import BuildingModel


def _guid(project, identifier):
    return ifcopenshell.guid.compress(uuid.uuid5(uuid.NAMESPACE_URL, f"punctora:{project}:{identifier}").hex)


def create_ifc(model: BuildingModel) -> ifcopenshell.file:
    model.validate()
    file = ifcopenshell.file(schema="IFC4")
    api = lambda command, **kwargs: ifcopenshell.api.run(command, file, **kwargs)
    geom = IFCGeometry(file)

    def root(ifc_class, identifier, name=None, predefined=None):
        entity = api("root.create_entity", ifc_class=ifc_class, name=name or identifier, predefined_type=predefined)
        entity.GlobalId = _guid(model.metadata.get("project_id", model.name), f"{ifc_class}:{identifier}")
        return entity

    project = root("IfcProject", "project", model.name)
    metre = api("unit.add_si_unit", unit_type="LENGTHUNIT")
    area = api("unit.add_si_unit", unit_type="AREAUNIT")
    volume = api("unit.add_si_unit", unit_type="VOLUMEUNIT")
    api("unit.assign_unit", units=[metre, area, volume])
    context = api("context.add_context", context_type="Model")
    body_context = api("context.add_context", context_type="Model", context_identifier="Body",
                       target_view="MODEL_VIEW", parent=context)
    coordinate_mapping = model.metadata.get("coordinate_mapping")
    if coordinate_mapping:
        origin = coordinate_mapping.get("working_to_source_translation_m")
        if not (isinstance(origin, list) and len(origin) == 3 and np.isfinite(origin).all()):
            raise ValueError("coordinate_mapping requires a finite three-value source translation")
        e57_metadata = model.metadata.get("e57", {}).get("coordinate_metadata")
        target = file.create_entity(
            "IfcProjectedCRS",
            Name="E57 source coordinate frame" if e57_metadata else "E57 source frame (CRS unspecified)",
            Description=e57_metadata or "No E57 coordinateMetadata was supplied; CRS and vertical datum require confirmation.",
            MapUnit=metre,
        )
        file.create_entity(
            "IfcMapConversion", SourceCRS=context, TargetCRS=target,
            Eastings=float(origin[0]), Northings=float(origin[1]), OrthogonalHeight=float(origin[2]),
            XAxisAbscissa=1.0, XAxisOrdinate=0.0, Scale=1.0,
        )
    site, building = root("IfcSite", "site"), root("IfcBuilding", "building", model.name)
    api("aggregate.assign_object", products=[site], relating_object=project)
    api("aggregate.assign_object", products=[building], relating_object=site)
    api("geometry.edit_object_placement", product=site, matrix=np.eye(4))
    api("geometry.edit_object_placement", product=building, matrix=np.eye(4))
    if coordinate_mapping:
        coordinate_pset = api("pset.add_pset", product=site, name="Punctora_CoordinateMapping")
        api("pset.edit_pset", pset=coordinate_pset, properties={
            "Mapping": "source_xyz_m = working_xyz_m + origin_m",
            "SourceOriginX_m": float(origin[0]), "SourceOriginY_m": float(origin[1]),
            "SourceOriginZ_m": float(origin[2]),
            "CRSStatus": model.metadata.get("e57", {}).get("coordinate_metadata_status", "unknown"),
        })
    storeys = {}
    for level in model.storeys:
        entity = root("IfcBuildingStorey", level.id, level.name)
        entity.Elevation = level.elevation
        api("aggregate.assign_object", products=[entity], relating_object=building)
        matrix = np.eye(4)
        matrix[2, 3] = level.elevation
        api("geometry.edit_object_placement", product=entity, matrix=matrix)
        storeys[level.id] = entity

    def provenance(product, identifier, states, extra=None):
        properties = {"ElementId": identifier, "ReviewState": "unreviewed", "EngineVersion": __version__}
        properties.update({f"{key}_provenance": value for key, value in states.items()})
        properties.update(extra or {})
        pset = api("pset.add_pset", product=product, name="Punctora_Reconstruction")
        api("pset.edit_pset", pset=pset, properties=properties)

    def solid(product, vertices, depth, matrix, append=False, local_z=0.0):
        # Explicit closed planar footprint and metre-valued extrusion.
        vertices = [tuple(map(float, point)) for point in vertices]
        if vertices[0] == vertices[-1]:
            vertices = vertices[:-1]
        points = [file.create_entity("IfcCartesianPoint", Coordinates=p) for p in vertices]
        curve = file.create_entity("IfcPolyline", Points=points+[points[0]])
        profile = file.create_entity("IfcArbitraryClosedProfileDef", ProfileType="AREA", OuterCurve=curve)
        position = file.create_entity("IfcAxis2Placement3D",
                                      Location=file.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, float(local_z))))
        extrusion = geom.create_extruded_solid(profile, position,
                    file.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)), float(depth))
        if append and product.Representation is not None:
            representation = product.Representation.Representations[0]
            representation.Items = tuple(representation.Items)+(extrusion,)
        else:
            representation = geom.create_shape_representation(body_context, "Body", "SweptSolid", [extrusion])
            api("geometry.assign_representation", product=product, representation=representation)
        api("geometry.edit_object_placement", product=product, matrix=matrix)

    def wall_frame(wall):
        start, end = np.array(wall.start), np.array(wall.end)
        length = float(np.linalg.norm(end-start))
        dx, dy = (end-start)/length
        frame = np.array([[dx, -dy, 0, start[0]], [dy, dx, 0, start[1]],
                          [0, 0, 1, wall.base], [0, 0, 0, 1]], dtype=float)
        return frame, length

    def rectangle(length, thickness):
        return [(0.0, -thickness/2), (length, -thickness/2), (length, thickness/2), (0.0, thickness/2)]

    wall_entities, wall_frames = {}, {}
    for wall in model.walls:
        entity = root("IfcWall", wall.id, predefined="NOTDEFINED")
        api("spatial.assign_container", products=[entity], relating_structure=storeys[wall.storey_id])
        frame, length = wall_frame(wall)
        solid(entity, rectangle(length, wall.thickness), wall.height, frame)
        provenance(entity, wall.id, wall.provenance,
                   {"EvidencePointCount": wall.evidence_count, "Classification": wall.classification,
                    "ObservedFaceFitRMSE_m": wall.fit_rmse_m, "ReviewState": wall.review_state,
                    "DetectionMethod": wall.detection_method,
                    "FitScope": wall.evidence.get("scope", "caller-supplied evidence scope unspecified")})
        wall_entities[wall.id], wall_frames[wall.id] = entity, frame

    for slab in model.slabs:
        entity = root("IfcSlab", slab.id, predefined=slab.kind)
        api("spatial.assign_container", products=[entity], relating_structure=storeys[slab.storey_id])
        matrix = np.eye(4)
        matrix[2, 3] = slab.base
        solid(entity, slab.footprint, slab.thickness, matrix)
        provenance(entity, slab.id, slab.provenance, {"ReviewState": slab.review_state})

    for space in model.spaces:
        entity = root("IfcSpace", space.id, predefined="NOTDEFINED")
        # Spaces are spatial decomposition, not contained physical products.
        api("aggregate.assign_object", products=[entity], relating_object=storeys[space.storey_id])
        matrix = np.eye(4)
        matrix[2, 3] = space.base
        solid(entity, space.footprint, space.height, matrix)
        provenance(entity, space.id, space.provenance)

    hosts = {wall.id: wall for wall in model.walls}
    for opening in model.openings:
        host, host_entity = hosts[opening.host_wall_id], wall_entities[opening.host_wall_id]
        frame = wall_frames[opening.host_wall_id].copy()
        frame[:3, 3] += frame[:3, 0]*opening.offset + np.array([0.0, 0.0, opening.sill])
        void = root("IfcOpeningElement", opening.id+"-void", predefined="OPENING")
        solid(void, rectangle(opening.width, host.thickness+0.02), opening.height, frame)
        api("feature.add_feature", feature=void, element=host_entity)
        provenance(void, opening.id+"-void", opening.provenance, {"ReviewState": opening.review_state})
        class_name = "IfcDoor" if opening.kind == "door" else "IfcWindow"
        filling = root(class_name, opening.id, predefined="NOTDEFINED")
        filling.OverallWidth, filling.OverallHeight = opening.width, opening.height
        api("spatial.assign_container", products=[filling], relating_structure=storeys[host.storey_id])
        # A simple filling envelope, not a measured sash/leaf construction.
        solid(filling, rectangle(opening.width, host.thickness/4), opening.height, frame)
        kind = root(class_name+"Type", opening.id+"-type", predefined="NOTDEFINED")
        if opening.kind == "window":
            kind.PartitioningType = "NOTDEFINED"
        else:
            kind.OperationType = "NOTDEFINED"
        kind.ParameterTakesPrecedence = False
        api("type.assign_type", related_objects=[filling], relating_type=kind)
        api("feature.add_filling", opening=void, element=filling)
        provenance(filling, opening.id, {**opening.provenance, "filling_depth": "inferred", "material": "unknown"},
                   {"RepresentationScope": "simple filling envelope; sash/leaf construction unknown",
                    "ReviewState": opening.review_state, "GeometricSupportScore": opening.confidence})

    for stair in model.stairs:
        parent = root("IfcStair", stair.id, predefined="STRAIGHT_RUN_STAIR")
        api("spatial.assign_container", products=[parent], relating_structure=storeys[stair.storey_id])
        flight = root("IfcStairFlight", stair.id+"-flight", predefined="STRAIGHT")
        api("aggregate.assign_object", products=[flight], relating_object=parent)
        flight.NumberOfRisers = stair.steps
        flight.NumberOfTreads = stair.steps
        flight.RiserHeight = stair.rise
        flight.TreadLength = stair.going
        direction = (np.asarray(stair.end)-np.asarray(stair.start))/(stair.steps*stair.going)
        dx, dy = direction
        frame = np.array([[dx, -dy, 0, stair.start[0]], [dy, dx, 0, stair.start[1]],
                          [0, 0, 1, stair.base], [0, 0, 0, 1]], dtype=float)
        for index in range(stair.steps):
            vertices = [(x+index*stair.going, y) for x, y in rectangle(stair.going, stair.width)]
            solid(flight, vertices, stair.tread_thickness, frame, append=True,
                  local_z=(index+1)*stair.rise-stair.tread_thickness)
        extra = {"ReviewState": stair.review_state, "GeometricSupportScore": stair.confidence,
                 "RepresentationScope": "observed tread envelopes; landings, railings and support structure unknown"}
        provenance(parent, stair.id, stair.provenance, extra)
        provenance(flight, stair.id+"-flight", stair.provenance, extra)

    file.header.file_name.originating_system = f"Punctora BIM Studio core {__version__}"
    file.header.file_name.preprocessor_version = f"IfcOpenShell {ifcopenshell.version}"
    file.header.file_description.description = ("Experimental reconstruction; review required",)
    return file


def validate_ifc(file: ifcopenshell.file) -> dict:
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(file, logger, express_rules=True)
    findings = [{"level": entry.get("level", "error"), "message": entry["message"],
                 "instance": str(entry.get("instance", "")), "attribute": str(entry.get("attribute", ""))}
                for entry in logger.statements]
    geometry_errors = []
    geometry_count = 0
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    for product in file.by_type("IfcProduct"):
        if product.Representation is None:
            continue
        try:
            shape = ifcopenshell.geom.create_shape(settings, product)
            vertices = np.asarray(shape.geometry.verts, dtype=float)
            if len(vertices) == 0 or not np.isfinite(vertices).all():
                raise ValueError("empty or nonfinite tessellation")
            geometry_count += 1
        except Exception as exc:
            geometry_errors.append({"element": product.GlobalId, "message": str(exc)})
    return {"schema": file.schema, "express_findings": findings, "geometry_errors": geometry_errors,
            "tessellated_products": geometry_count, "valid": not findings and not geometry_errors,
            "scope": "IFC schema/EXPRESS and tessellation only; no survey accuracy, coverage or project acceptance claim"}


def write_ifc(model: BuildingModel, path: str | Path) -> dict:
    """Validate a serialised candidate before atomically replacing the destination."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file = create_ifc(model)
    candidate = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".ifc", delete=False) as temp:
            candidate = Path(temp.name)
        file.header.file_name.name = path.name
        file.write(str(candidate))
        report = validate_ifc(ifcopenshell.open(str(candidate)))
        if not report["valid"]:
            raise ValueError("IFC validation failed: " + json.dumps(report, ensure_ascii=False))
        os.replace(candidate, path)
        return report
    finally:
        if candidate is not None:
            candidate.unlink(missing_ok=True)
