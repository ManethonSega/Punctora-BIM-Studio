"""Repeated, independently supported façade bays in observed-face coordinates.

Uses the existing local original-point raster, with no additional cloud scan.
Glass material, suspension and detailed frame profiles remain unverified.
"""
import cv2
import numpy as np
from .model import Opening


def frame_bays(wall, face, returns, depth, signed, reference, cell, settings, padding=0):
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
        if min(edges) < settings.opening_minimum_edge_support:
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
                doorway_evidence={'supported':False,'reason':'supported sill and repeated façade frame'},
                scope=frame['scope'])
            result.append(Opening('',wall.id,'window',bay['offset'],sill,bay['width'],height,
                          {'dimensions':'measured','kind':'inferred','material':'unknown'},
                          confidence=min(.95,min(bay['edges'])),evidence=evidence))
    return result


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
