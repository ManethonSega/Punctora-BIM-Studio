"""Repeated, independently supported façade bays in observed-face coordinates.

Uses the existing local original-point raster, with no additional cloud scan.
Glass material, suspension and detailed frame profiles remain unverified.
"""
import cv2
import numpy as np
from .model import Opening


def projected_bay_groups(instances, minimum_bays=3, maximum_pier_m=.6, tolerance_m=.1):
    """Record repeated proposed bays without asserting glass/curtain-wall type.

    Geometry and material acceptance stay in later runs. A measured opaque
    pier separates bays; grouping cannot collapse repeated holes into one.
    """
    groups = []
    for item in sorted(instances, key=lambda i: (i.get("host_id", ""), i.get("wall_local_bounds_m", [0, 0, 0, 0]))):
        if item["class"] not in {"opening", "window", "door"} or not item.get("wall_local_bounds_m"):
            continue
        bounds = item["wall_local_bounds_m"]
        group = next((g for g in groups if g[-1]["host_id"] == item["host_id"]
                      and abs(g[-1]["wall_local_bounds_m"][1] - bounds[1]) <= tolerance_m
                      and abs(g[-1]["wall_local_bounds_m"][3] - bounds[3]) <= tolerance_m
                      and 0 <= bounds[0] - g[-1]["wall_local_bounds_m"][2] <= maximum_pier_m), None)
        if group is None:
            groups.append([item])
        else:
            group.append(item)
    return [{"member_ids": [i["id"] for i in g], "host_id": g[0]["host_id"],
             "material": "unknown", "system_type": "unresolved", "status": "proposed"}
            for g in groups if len(g) >= minimum_bays]


def frame_bays(wall, face, returns, depth, signed, reference, cell, settings, padding=0, vertical_sill=None):
    nz, nx = face.shape
    count, labels, stats, _ = cv2.connectedComponentsWithStats(1-face, 8)
    bays = []
    for i in range(1, count):
        x,z,w,h,area = map(int, stats[i])
        if (w*cell < .5 or h*cell < .55 or x < 1 or z < 1
                or x+w > nx-1 or z+h > nz-1 or area/(w*h) < .85):
            continue
        strips = [face[z:z+h,max(0,x-2):x],face[z:z+h,x+w:min(nx,x+w+2)],
                  face[max(0,z-2):z,x:x+w],face[z+h:min(nz,z+h+2),x:x+w]]
        edges = [float(a.mean()) if a.size else 0. for a in strips]
        if z==1 and vertical_sill is not None:
            edges[2]=float(vertical_sill[x:x+w].mean())
        floor_height=(z<=1 and wall.height-(z+h)*cell<=.25)
        required_edges=edges[:2]+edges[3:] if floor_height else edges
        if min(required_edges) < settings.opening_minimum_edge_support:
            continue
        interior = returns[z:z+h,x:x+w] > 0
        occupancy = float(interior.mean())
        values = signed[z:z+h,x:x+w][interior]
        values = values[np.isfinite(values)]
        contrast = float(np.median(depth[z:z+h,x:x+w][interior])) if interior.any() else 0.
        consistency = float(max((values>0).mean(),(values<0).mean())) if len(values) else 0.
        if not (occupancy <= .15 or (occupancy >= .55
                and contrast >= settings.opening_recess_depth_m and consistency >= .8)):
            continue
        length=float(np.linalg.norm(np.asarray(wall.end)-wall.start))
        offset=max(0.,(x-padding)*cell)
        end=min(length,(x+w-padding)*cell)
        if end-offset<.5:
            continue
        bays.append(dict(x=x,z=z,w=w,h=h,offset=offset,width=end-offset,edges=edges,occupancy=occupancy,
                         signed_depth=float(np.median(values)) if len(values) else None,
                         depth_contrast=contrast))
    # Build horizontal sequences. Do not span unsupported masonry or assume
    # that every tall rectangle is a doorway or a façade system.
    groups = []
    for bay in sorted(bays, key=lambda b:(b['z'],b['h'],b['x'])):
        previous = next((g for g in groups if
            abs(g[-1]['z']-bay['z'])*cell <= max(.08,cell*2)
            and abs(g[-1]['h']-bay['h'])*cell <= max(.08,cell*2)
            and 0 <= (bay['x']-g[-1]['x']-g[-1]['w'])*cell <= .6), None)
        if previous is None:
            groups.append([bay])
        else:
            previous.append(bay)
    result = []
    for sequence in groups:
        a,b = sequence[0],sequence[-1]
        width = b['offset']+b['width']-a['offset']
        widths = np.array([p['w']*cell for p in sequence])
        if len(sequence)<2 or width<4.5 or np.std(widths)/np.mean(widths)>.25:
            continue
        gaps = [(q['x']-p['x']-p['w'])*cell for p,q in zip(sequence,sequence[1:])]
        z = max(p['z'] for p in sequence)
        top = min(p['z']+p['h'] for p in sequence)
        bottom_support = float(face[max(0,z-2):z,a['x']:b['x']+b['w']].mean())
        head_support = float(face[top:min(nz,top+2),a['x']:b['x']+b['w']].mean())
        aligned = len({(p['z'],p['h']) for p in sequence}) == 1
        continuous = (len(sequence)>=4 and aligned and max(gaps)<=.16
                      and min(p['edges'][2] for p in sequence)>=settings.opening_minimum_edge_support
                      and min(bottom_support,head_support)>=.75)
        identifier = f"{wall.id}-facade-{a['x']}-{z}"
        frame = dict(host_wall_id=wall.id,host_geometry=[*wall.start,*wall.end,wall.base,wall.height,wall.thickness],
                     system_id=identifier,representation='curtain_wall' if continuous else 'repeated_windows',
                     panel_count=len(sequence),offset=a['offset'],sill=z*cell,width=width,height=(top-z)*cell,
                     panel_intervals=[dict(offset=p['offset'],width=p['width']) for p in sequence],
                     mullions=[dict(offset=(p['x']+p['w']-padding)*cell,width=gap)
                               for p,gap in zip(sequence,gaps)],
                     repeated_spacing_m=np.diff([p['x']*cell for p in sequence]).tolist(),
                     pier_widths_m=gaps,rail_support_fractions=[bottom_support,head_support],
                     continuous_frame_supported=continuous,face_offset_from_axis_m=reference,
                     scope='Repeated observed frame geometry; glazing and nonbearing system classification inferred; suspension and structural role unverified')
        for bay in sequence:
            sill,height = bay['z']*cell,bay['h']*cell
            full_height = sill<=.2 and wall.height-sill-height<=.25
            evidence = dict(method='repeated_facade_frame_geometry',facade_system=frame,
                classification='floor_to_ceiling_glazing' if full_height else 'glazed_facade_bay',
                cell_size_m=cell,face_offset_from_axis_m=reference,
                edge_support=dict(zip(['left_jamb','right_jamb','sill','head'],bay['edges'])),
                edge_support_fractions=bay['edges'],jamb_positions_m=[(bay['x']-padding)*cell,(bay['x']+bay['w']-padding)*cell],
                host_clipping_m=[bay['offset']-(bay['x']-padding)*cell,
                                 (bay['x']+bay['w']-padding)*cell-bay['offset']-bay['width']],
                sill_elevation_m=wall.base+sill,head_elevation_m=wall.base+sill+height,
                interior_occupancy=bay['occupancy'],signed_interior_depth_m=bay['signed_depth'],
                interior_depth_contrast_m=bay['depth_contrast'],
                raster_frame=dict(along_origin_xy=list(wall.start),
                    along_direction_xy=((np.asarray(wall.end)-wall.start)/np.linalg.norm(np.asarray(wall.end)-wall.start)).tolist(),
                    z_origin_m=wall.base,face_offset_from_axis_m=reference,shape_rows_columns=[nz,nx],along_padding_m=padding*cell),
                doorway_evidence={'supported':False,'reason':'repeated façade frame with supported sill or ceiling-height head'},
                scope=frame['scope'])
            result.append(Opening('',wall.id,'window',bay['offset'],sill,bay['width'],height,
                          {'dimensions':'measured','kind':'inferred','material':'unknown'},
                          confidence=min(.95,min(bay['edges'])),evidence=evidence))
    return result


def tag_repeated_window_groups(wall, openings, maximum_pier_m=1.0):
    """Group independently accepted, aligned windows into façade zones.

    Real façades can have broad opaque piers, so their empty raster components
    do not always survive as one frame-bay sequence. This fallback changes no
    opening geometry or classification. It records the supported repeated zone
    and intentionally exports its bays as normal IfcWindow elements.
    """
    windows = sorted((opening for opening in openings
                      if opening.kind == "window"
                      and "facade_system" not in opening.evidence),
                     key=lambda opening: opening.offset)
    assigned = set()
    for seed_index, seed in enumerate(windows):
        if id(seed) in assigned:
            continue
        sequence = [seed]
        seed_head = seed.sill+seed.height
        seed_face = seed.evidence.get("face_offset_from_axis_m", 0.0)
        for candidate in windows[seed_index+1:]:
            gap = candidate.offset-(sequence[-1].offset+sequence[-1].width)
            if gap > maximum_pier_m:
                break
            if (gap >= 0 and abs(candidate.sill-seed.sill) <= .10
                    and abs(candidate.sill+candidate.height-seed_head) <= .10
                    and abs(candidate.evidence.get("face_offset_from_axis_m", 0.0)-seed_face) <= .06):
                sequence.append(candidate)
        if len(sequence) < 3:
            continue
        widths = np.asarray([opening.width for opening in sequence])
        zone_width = sequence[-1].offset+sequence[-1].width-sequence[0].offset
        gaps = [b.offset-(a.offset+a.width) for a, b in zip(sequence, sequence[1:])]
        if (zone_width < 4.5 or np.std(widths)/max(1e-12, np.mean(widths)) > .30
                or max(gaps, default=0.0) > maximum_pier_m):
            continue
        sill = float(np.median([opening.sill for opening in sequence]))
        head = float(np.median([opening.sill+opening.height for opening in sequence]))
        identifier = f"{wall.id}-facade-{int(round(sequence[0].offset*1000))}-{int(round(sill*1000))}"
        sill_support = [opening.evidence.get("edge_support", {}).get("sill", 0.0)
                        for opening in sequence]
        head_support = [opening.evidence.get("edge_support", {}).get("head", 0.0)
                        for opening in sequence]
        frame = dict(host_wall_id=wall.id,
            host_geometry=[*wall.start,*wall.end,wall.base,wall.height,wall.thickness],
            system_id=identifier, representation="repeated_windows",
            panel_count=len(sequence), offset=sequence[0].offset, sill=sill,
            width=zone_width, height=head-sill,
            panel_intervals=[dict(offset=opening.offset,width=opening.width)
                             for opening in sequence],
            mullions=[dict(offset=opening.offset+opening.width,width=gap)
                      for opening, gap in zip(sequence, gaps)],
            repeated_spacing_m=np.diff([opening.offset for opening in sequence]).tolist(),
            pier_widths_m=gaps,
            rail_support_fractions=[float(min(sill_support)), float(min(head_support))],
            continuous_frame_supported=False, face_offset_from_axis_m=float(seed_face),
            scope=("Aligned repeated window bays with independently supported jambs, sills and heads; "
                   "opaque piers retained and curtain-wall continuity unverified"))
        for opening in sequence:
            opening.evidence["facade_system"] = frame
            if opening.evidence.get("classification") != "floor_to_ceiling_glazing":
                opening.evidence["classification"] = "glazed_facade_bay"
            opening.evidence["doorway_evidence"] = {
                "supported": False,
                "reason": "aligned repeated window zone with supported sill and head"}
            assigned.add(id(opening))
    return openings


def refresh_repeated_window_groups(walls, openings, maximum_pier_m=1.0):
    """Rebuild repeated-window evidence after final wall reconciliation.

    A physical façade can cross a paired-wall span and its retained single-face
    tail.  Per-wall grouping is attempted first; remaining aligned windows are
    grouped in global coordinates across those adjacent final hosts.
    """
    wall_by_id = {wall.id: wall for wall in walls}
    for opening in openings:
        frame = opening.evidence.get("facade_system", {})
        if frame.get("representation") == "repeated_windows":
            opening.evidence.pop("facade_system", None)
    by_wall = {}
    for opening in openings:
        by_wall.setdefault(opening.host_wall_id, []).append(opening)
    for wall_id, local in by_wall.items():
        wall = wall_by_id.get(wall_id)
        if wall is not None:
            tag_repeated_window_groups(wall, local, maximum_pier_m)

    records = []
    for opening in openings:
        if opening.kind != "window" or "facade_system" in opening.evidence:
            continue
        wall = wall_by_id.get(opening.host_wall_id)
        if wall is None:
            continue
        start = np.asarray(wall.start, dtype=float)
        direction = np.asarray(wall.end, dtype=float)-start
        length = float(np.linalg.norm(direction))
        if length <= 1e-9:
            continue
        direction /= length
        centre = start+direction*(opening.offset+opening.width/2)
        canonical = direction.copy()
        if canonical[0] < -1e-12 or (abs(canonical[0]) <= 1e-12 and canonical[1] < 0):
            canonical *= -1
        normal = np.array([-canonical[1], canonical[0]])
        records.append(dict(opening=opening, wall=wall, direction=canonical,
                            centre=centre, scalar=float(centre@canonical),
                            plane=float(centre@normal)))

    assigned = set()
    cosine = np.cos(np.deg2rad(2.0))
    for seed in sorted(records, key=lambda item: (item["wall"].storey_id,
                                                   item["direction"][0], item["scalar"])):
        if id(seed["opening"]) in assigned:
            continue
        compatible = [item for item in records
            if id(item["opening"]) not in assigned
            and item["wall"].storey_id == seed["wall"].storey_id
            and float(item["direction"]@seed["direction"]) >= cosine
            and abs(item["plane"]-seed["plane"]) <= .35
            and abs(item["opening"].sill-seed["opening"].sill) <= .1
            and abs(item["opening"].sill+item["opening"].height
                    -seed["opening"].sill-seed["opening"].height) <= .1]
        compatible.sort(key=lambda item: item["scalar"])
        seed_index = next(index for index, item in enumerate(compatible)
                          if item is seed)
        sequence = [seed]
        for direction in (-1, 1):
            index, edge = seed_index+direction, seed
            while 0 <= index < len(compatible):
                candidate = compatible[index]
                if direction < 0:
                    gap = (edge["scalar"]-edge["opening"].width/2
                           -candidate["scalar"]-candidate["opening"].width/2)
                else:
                    gap = (candidate["scalar"]-candidate["opening"].width/2
                           -edge["scalar"]-edge["opening"].width/2)
                if gap < -.1 or gap > maximum_pier_m:
                    break
                sequence.append(candidate); edge = candidate; index += direction
        sequence.sort(key=lambda item: item["scalar"])
        widths = np.asarray([item["opening"].width for item in sequence])
        low = sequence[0]["scalar"]-widths[0]/2
        high = sequence[-1]["scalar"]+widths[-1]/2
        if (len(sequence) < 3 or high-low < 4.5
                or np.std(widths)/max(1e-12, np.mean(widths)) > .30):
            continue
        gaps = [(b["scalar"]-b["opening"].width/2)
                -(a["scalar"]+a["opening"].width/2)
                for a, b in zip(sequence, sequence[1:])]
        sill = float(np.median([item["opening"].sill for item in sequence]))
        head = float(np.median([item["opening"].sill+item["opening"].height
                                for item in sequence]))
        host_ids = sorted({item["opening"].host_wall_id for item in sequence})
        identifier = (f"{seed['wall'].storey_id}-facade-global-"
                      f"{int(round(low*1000))}-{int(round(sill*1000))}")
        sill_support = [item["opening"].evidence.get("edge_support", {}).get("sill", 0.)
                        for item in sequence]
        head_support = [item["opening"].evidence.get("edge_support", {}).get("head", 0.)
                        for item in sequence]
        frame = dict(host_wall_id=host_ids[0], host_wall_ids=host_ids,
            system_id=identifier, representation="repeated_windows",
            panel_count=len(sequence), offset=low, sill=sill, width=high-low,
            height=head-sill,
            panel_intervals=[dict(host_wall_id=item["opening"].host_wall_id,
                                  offset=item["opening"].offset,
                                  width=item["opening"].width)
                             for item in sequence],
            mullions=[dict(global_offset=a["scalar"]+a["opening"].width/2,
                            width=gap) for a, gap in zip(sequence, gaps)],
            repeated_spacing_m=np.diff([item["scalar"] for item in sequence]).tolist(),
            pier_widths_m=gaps,
            rail_support_fractions=[float(min(sill_support)), float(min(head_support))],
            continuous_frame_supported=False,
            scope=("Aligned repeated window bays on adjacent reconciled wall spans; "
                   "opaque piers retained and curtain-wall continuity unverified"))
        for item in sequence:
            opening = item["opening"]
            opening.evidence["facade_system"] = frame
            if opening.evidence.get("classification") != "floor_to_ceiling_glazing":
                opening.evidence["classification"] = "glazed_facade_bay"
            opening.evidence["doorway_evidence"] = {
                "supported": False,
                "reason": "aligned repeated window zone with supported sill and head"}
            assigned.add(id(opening))
    return openings


def supported_facade_groups(model):
    """Editing/rejecting a bay prevents a stale whole-zone cut at export."""
    grouped = {}
    walls = {w.id:w for w in model.walls}
    for opening in model.openings:
        frame = opening.evidence.get('facade_system', {})
        if frame.get('representation') == 'curtain_wall':
            grouped.setdefault(frame['system_id'], []).append(opening)
    result = {}
    for identifier, openings in grouped.items():
        frame = openings[0].evidence['facade_system']
        host = walls.get(openings[0].host_wall_id)
        if host is None:
            continue
        geometry = [*host.start,*host.end,host.base,host.height,host.thickness]
        intervals = sorted((o.offset,o.width,o.sill,o.height) for o in openings)
        original_intervals = sorted((p['offset'],p['width'],frame['sill'],frame['height']) for p in frame['panel_intervals'])
        if (len(openings) == frame['panel_count'] and intervals == original_intervals and geometry == frame['host_geometry']
                and all(o.kind=='window' and o.review_state not in {'rejected','flagged'}
                        and not o.evidence.get('facade_geometry_stale')
                        and o.host_wall_id == frame['host_wall_id'] for o in openings)):
            result[identifier] = openings
    return result
