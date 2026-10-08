# Adapted Cloud2BIM generate_ifc.py geometry primitives.
# Copyright (c) 2025 Václav Nežerka. MIT licence; full notice in third_party/licenses/Cloud2BIM-MIT.txt.
# Upstream: cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e.
# Punctora changes: only pure placement/extrusion/representation helpers retained.

class IFCGeometry:
    def __init__(self, ifc_file):
        self.ifc_file = ifc_file

    def create_local_placement(self, coordinates, axis=None, ref_direction=None, relative_to=None):
            """
            Creates an IfcLocalPlacement using a generic IfcAxis2Placement3D.
            :param coordinates: Tuple (x, y, z) for the location.
            :param axis: Optional IfcDirection entity for the axis.
            :param ref_direction: Optional IfcDirection entity for the reference direction.
            :param relative_to: Optional IfcLocalPlacement to relate to.
            """
            axis_placement = self.ifc_file.create_entity(
                "IfcAxis2Placement3D",
                Location=self.ifc_file.create_entity("IfcCartesianPoint", Coordinates=coordinates),
                Axis=axis,
                RefDirection=ref_direction
            )
            if relative_to:
                return self.ifc_file.create_entity("IfcLocalPlacement", RelativePlacement=axis_placement, PlacementRelTo=relative_to)
            else:
                return self.ifc_file.create_entity("IfcLocalPlacement", RelativePlacement=axis_placement)

    def create_extruded_solid(self, swept_area, position, extrusion_direction, depth):
            """
            Creates an IfcExtrudedAreaSolid entity.
            :param swept_area: The area profile to be extruded.
            :param position: The placement for the extrusion.
            :param extrusion_direction: The extrusion direction (IfcDirection).
            :param depth: The extrusion depth.
            """
            return self.ifc_file.create_entity(
                "IfcExtrudedAreaSolid",
                SweptArea=swept_area,
                Position=position,
                ExtrudedDirection=extrusion_direction,
                Depth=depth
            )

    def create_shape_representation(self, context, rep_id, rep_type, items):
            """
            Wraps geometry items into an IfcShapeRepresentation.
            :param context: The geometric representation context.
            :param rep_id: Representation Identifier (e.g., "Body", "Axis").
            :param rep_type: Representation type (e.g., "SweptSolid").
            :param items: List of geometry items.
            """
            return self.ifc_file.create_entity(
                "IfcShapeRepresentation",
                ContextOfItems=context,
                RepresentationIdentifier=rep_id,
                RepresentationType=rep_type,
                Items=items
            )
