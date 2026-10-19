"""Original-point validation between review-only providers and model candidates.

Provider artifacts remain immutable. This layer may add unreviewed geometry,
never user acceptance, slab cuts or unsupported dimensions.
"""
import numpy as np
from shapely import contains_xy
from shapely.geometry import LineString, Polygon, box

from ..annotation_io import content_digest, read_json
from ..model import Wall, Opening, Slab
from ..opening_bounds import fit_generated_opening
from .contracts import TAXONOMY, safe_artifact_path
from .streaming_views import SourceBox


def fit_vertical_plane(source, polygon, seeds, labels=None, class_name='wall'):
    """Two bounded passes over original points, no dimensions from the model box."""
    if len(seeds)<6:
        return None
    anchor=np.mean(seeds[:,:2],axis=0)
    _, vectors=np.linalg.eigh((seeds[:,:2]-anchor).T@(seeds[:,:2]-anchor))
    axis=vectors[:,-1]
    if axis[0]<0 or (axis[0]==0 and axis[1]<0):axis=-axis
    normal=np.array([-axis[1],axis[0]])
    shape=Polygon(polygon).buffer(.08)
    class_id=TAXONOMY.index(class_name)
    count=0;sums=np.zeros(2);products=np.zeros((2,2));zlow=np.inf;zhigh=-np.inf
    examples=[]
    def selected(rows,points,origin,n):
        keep=contains_xy(shape,points[:,0],points[:,1])
        keep &= np.abs((points[:,:2]-origin)@n)<=.08
        if labels is not None:keep &= labels[rows]==class_id
        return keep
    for rows,points in source.blocks():
        keep=selected(rows,points,anchor,normal);p=points[keep]
        if not len(p):continue
        xy=p[:,:2]-anchor;count+=len(p);sums+=xy.sum(axis=0);products+=xy.T@xy
        zlow=min(zlow,float(p[:,2].min()));zhigh=max(zhigh,float(p[:,2].max()))
        examples.extend(rows[keep][:max(0,32-len(examples))].tolist())
    if count<40 or zhigh-zlow<.55:return None
    centre=sums/count
    values,vectors=np.linalg.eigh(products/count-np.outer(centre,centre))
    if values[0]>.035**2 or values[1]<.02:return None
    direction=vectors[:,-1]
    if direction@axis<0:direction=-direction
    origin=anchor+centre;normal=np.array([-direction[1],direction[0]])
    low,high=np.inf,-np.inf;bands=np.zeros(12,dtype=np.int64);residual_count=0;residual_sum=0.
    for rows,points in source.blocks():
        keep=selected(rows,points,origin,normal);p=points[keep]
        if not len(p):continue
        u=(p[:,:2]-origin)@direction
        low=min(low,float(u.min()));high=max(high,float(u.max()))
        bands+=np.histogram(p[:,2],np.linspace(zlow,zhigh+1e-8,13))[0]
        residual=(p[:,:2]-origin)@normal
        residual_count+=len(p);residual_sum+=float(residual@residual)
    if high-low<.5 or np.count_nonzero(bands>=3)<8:return None
    return {'start':origin+direction*low,'end':origin+direction*high,'base':zlow,'height':zhigh-zlow,
        'axis':direction,'normal':normal,'origin':origin,'u_min':low,'u_max':high,
        'rmse':float(np.sqrt(residual_sum/max(1,residual_count))),'count':residual_count,
        'z_band_counts':bands.tolist(),'source_row_examples':examples}


def frame_support(source, plane, labels, class_name='window'):
    """Window labels alone cannot establish a frame or permit a wall cut."""
    length=plane['u_max']-plane['u_min'];height=plane['height']
    bins=[np.zeros(20,bool) for _ in range(4)]
    class_id=TAXONOMY.index(class_name)
    for rows,points in source.blocks():
        delta=points[:,:2]-plane['start']
        u=delta@plane['axis'];z=points[:,2]-plane['base'];v=delta@plane['normal']
        independent=(labels[rows]!=class_id)&(np.abs(v)<=.20)
        edges=[independent&(np.abs(u)<=.10)&(z>=0)&(z<=height),
               independent&(np.abs(u-length)<=.10)&(z>=0)&(z<=height),
               independent&(np.abs(z)<=.10)&(u>=0)&(u<=length),
               independent&(np.abs(z-height)<=.10)&(u>=0)&(u<=length)]
        for i,keep in enumerate(edges):
            position=(z[keep]/height if i<2 else u[keep]/length)
            bins[i][np.clip((position*20).astype(int),0,19)]=True
    fractions=[float(v.mean()) for v in bins]
    return min(fractions)>=.65,fractions


def _wall_match(model,plane):
    line=LineString([plane['start'],plane['end']]);length=line.length
    for wall in sorted(model.walls,key=lambda w:w.id):
        d=np.asarray(wall.end)-wall.start;d/=np.linalg.norm(d)
        if (abs(d@plane['axis'])>=np.cos(np.deg2rad(3))
                and line.intersection(LineString([wall.start,wall.end]).buffer(max(.08,wall.thickness/2))).length>=length*.70
                and min(wall.base+wall.height,plane['base']+plane['height'])>max(wall.base,plane['base'])):
            return wall
    return None


def fuse_horizontal_patch(cloud,model,proposal,labels,source,settings,report,manifest):
    """A semantic surface still needs a dominant original horizontal plane."""
    from .preprocessing import original_normals
    from ..slab_zones import occupancy_geometry, _polygons, coverage_evidence
    class_id=TAXONOMY.index(proposal['class']) if labels is not None else None
    shape=Polygon(proposal['polygon_xy_m']);histogram={}
    for rows,points in source.blocks():
        keep=contains_xy(shape.buffer(.02),points[:,0],points[:,1])
        if labels is not None:keep &= labels[rows]==class_id
        bins,counts=np.unique(np.floor(points[keep,2]/.05+1e-8).astype(np.int64),return_counts=True)
        for key,count in zip(bins,counts):histogram[int(key)]=histogram.get(int(key),0)+int(count)
    if not histogram:return
    modes=sorted(histogram,key=lambda k:(-histogram[k],k))
    used=[]
    for key in modes:
        if len(used)>=3:break
        if any(abs(key-k)<3 for k in used) or histogram[key]<max(40,sum(histogram.values())*.15):continue
        used.append(key);seeds=[];cells=set();total=0;zsum=0.
        origin=np.floor(np.asarray(shape.bounds[:2])/.08)*.08
        for rows,points in source.blocks():
            keep=np.abs(points[:,2]-(key+.5)*.05)<=.05
            if labels is not None:keep &= labels[rows]==class_id
            keep &= contains_xy(shape.buffer(.02),points[:,0],points[:,1])
            p=points[keep]
            if not len(p):continue
            seeds.extend(p[:max(0,4096-len(seeds))].tolist());total+=len(p);zsum+=float(p[:,2].sum())
            cells.update(map(tuple,np.floor((p[:,:2]-origin)/.08+1e-8).astype(int).tolist()))
        if len(cells)<40 or len(cells)>settings.maximum_grid_cells:continue
        seed=np.asarray(seeds);normal,valid=original_normals(seed,np.arange(len(seed)),check=source.control.check)
        if not valid.any() or np.mean(np.abs(normal[valid,2])>=.97)<.8:continue
        elevation=zsum/total
        owner=min(model.storeys,key=lambda s:min(abs(s.elevation-elevation),abs(s.ceiling-elevation)))
        if min(abs(owner.elevation-elevation),abs(owner.ceiling-elevation))>.15:continue
        geometry,raw=occupancy_geometry(origin+(np.asarray(sorted(cells))+.5)*.08,.08,.16,settings.maximum_grid_cells)
        for number,piece in enumerate(sorted(_polygons(geometry),key=lambda p:p.bounds)):
            if piece.area<1.:continue
            existing=next((s for s in model.slabs if min(abs(s.base-elevation),abs(s.base+s.thickness-elevation))<.12
                and Polygon(s.footprint).intersection(piece).area>=piece.area*.7),None)
            proof={'specialist_proposal_id':proposal['id'],'proposal_cache_key':manifest['cache_key'],
                'original_horizontal_points':total,'observed_plane_m':elevation,
                'surface_role':'unknown; observed plane, not proof of structural slab or roof'}
            if existing:
                existing.evidence.setdefault('specialist_corroboration',[]).append(proof)
                report['corroborated_ids'].append(existing.id)
            from shapely.ops import unary_union
            prior=unary_union([Polygon(s.footprint) for s in model.slabs if
                min(abs(s.base-elevation),abs(s.base+s.thickness-elevation))<.12])
            # No overlapping slab solids when multiple specialists see a patch.
            remaining=piece.difference(prior)
            pieces=_polygons(remaining)
            if not pieces:continue
            # Keep disconnected remnants separate instead of spanning a void.
            for pi,part in enumerate(sorted(pieces,key=lambda p:p.bounds)):
                if part.area<.25:continue
                if part.interiors:
                    report['rejected_proposals'].append({'proposal_id':proposal['id'],
                        'reason':'surface_remnant_requires_holes; no overlapping_solid_or_learned_cut_created'})
                    continue
                footprint=Polygon(part.exterior)
                coverage=coverage_evidence(footprint,raw,raw.buffer(.08).intersection(footprint))
                identifier='specialist-fit-surface-'+content_digest([proposal['id'],key,number,pi])[:16]
                is_floor=abs(owner.elevation-elevation)<abs(owner.ceiling-elevation)
                slab=Slab(identifier,owner.id,list(footprint.exterior.coords)[:-1],
                    elevation-settings.assumed_slab_thickness_m if is_floor else elevation,
                    settings.assumed_slab_thickness_m,'FLOOR' if is_floor else 'NOTDEFINED',
                    provenance={'elevation':'measured','thickness':'inferred','footprint':'inferred','material':'unknown'},
                    review_state='flagged' if coverage['coverage_review_required'] else 'unreviewed',
                    evidence={**proof,**coverage,'scope':'original horizontal occupancy; no learned slab cut accepted'})
                model.slabs.append(slab);report['added_surface_ids'].append(identifier)


def fuse_geometry(cloud,model,manifest,directory,index,control,settings):
    extension=manifest.get('extensions',{}).get('specialist_v1')
    report={'schema_version':1,'authority':'original_point_geometry_validation',
            'added_wall_ids':[],'added_window_ids':[],'added_surface_ids':[], 'corroborated_ids':[],'rejected_proposals':[],
            'opening_decisions':[],
            'review_state':'unreviewed','accepted_cuts':0,'user_acceptance_changes':0}
    if extension is None:return report
    proposals=read_json(safe_artifact_path(directory,extension['proposals_path']))['proposals']
    for instance in manifest.get('instances',[]):
        if instance.get('class')!='wall' or instance.get('geometry',{}).get('type')!='wall':continue
        g=instance['geometry'];a,b=np.asarray(g['start']),np.asarray(g['end']);d=b-a
        if np.linalg.norm(d)<.5:continue
        n=np.array([-d[1],d[0]])/np.linalg.norm(d)*g['thickness']/2
        proposals.append({'id':instance['id'],'branch':'J','class':'wall',
            'polygon_xy_m':[(a-n).tolist(),(b-n).tolist(),(b+n).tolist(),(a+n).tolist()],
            'z_min_m':g['base'],'z_max_m':g['base']+g['height']})
    entries=read_json(safe_artifact_path(directory,extension['support_index_path']))['entries']
    entries={e['id']:e for e in entries}
    support=np.load(safe_artifact_path(directory,extension['support_rows']['path']),mmap_mode='r',allow_pickle=False)
    labels=np.load(safe_artifact_path(directory,manifest['arrays']['labels']['path']),mmap_mode='r',allow_pickle=False)
    try:
        for proposal in sorted(proposals,key=lambda p:(p['class']!='wall',p['id'])):
            control.check();kind=proposal['class']
            opening_decision = None
            if kind in {'window','door','opening'}:
                opening_decision = {'proposal_id':proposal['id'],'branch':proposal.get('branch'),
                    'class':kind,'status':'pending_original_point_validation',
                    'proposal_cache_key':manifest['cache_key'],'host_wall_id':None}
                report['opening_decisions'].append(opening_decision)
                if not settings.detect_openings_enabled:
                    opening_decision.update(status='not_evaluated',reason='opening_detection_disabled')
                    continue
            if kind not in {'wall','window','door','slab','ceiling','roof','stair','opening'}:
                # Sections/beam/column/stair masks remain proposals, not fake solids.
                continue
            e=entries[proposal['id']];rows=support[e['offset']:e['offset']+e['count']]
            seeds=np.asarray(cloud.points[rows.astype(np.int64)],dtype=np.float64)
            shape=Polygon(proposal['polygon_xy_m']);bounds=shape.buffer(.20).bounds
            source=SourceBox(cloud,index,[bounds[0],bounds[1],proposal['z_min_m']-.12],
                [bounds[2],bounds[3],proposal['z_max_m']+.12],control,1_500_000)
            semantic=labels if proposal.get('branch')=='I' else None
            if kind in {'slab','ceiling','roof'}:
                if model.metadata.get('reconstruction_scope','interior')!='exterior':
                    if semantic is not None:fuse_horizontal_patch(cloud,model,proposal,labels,source,settings,report,manifest)
                    elif proposal.get('branch')=='A':
                        centre=shape.centroid
                        owner=min(model.storeys,key=lambda s:Polygon(s.footprint).distance(centre))
                        search=Polygon(owner.footprint);bounds=search.bounds
                        surface_source=SourceBox(cloud,index,[bounds[0],bounds[1],proposal['z_min_m']-.04],
                            [bounds[2],bounds[3],proposal['z_max_m']+.04],control,1_500_000,search)
                        surface_proposal=dict(proposal,polygon_xy_m=list(search.exterior.coords)[:-1])
                        fuse_horizontal_patch(cloud,model,surface_proposal,None,surface_source,settings,report,manifest)
                continue
            if kind=='opening':
                # B/E guide local searches; original frame/void/recess rules
                # still determine bounds and whether a host cut is justified.
                affected=[w for w in model.walls if shape.distance(LineString([w.start,w.end]))<=.20
                    and min(w.base+w.height,proposal['z_max_m'])>max(w.base,proposal['z_min_m'])]
                for wall in affected:
                    wall.evidence.setdefault('specialist_opening_search_ids',[]).append(proposal['id'])
                opening_decision.update(status='deferred_original_frame_search',
                    affected_host_ids=[wall.id for wall in affected],
                    reason='plan_or_section_proposal_requires_original_frame_and_plane_support')
                continue
            if kind=='stair':
                for stair in model.stairs:
                    flight=LineString([stair.start,stair.end]).buffer(stair.width/2,cap_style=2)
                    if shape.intersection(flight).area>=flight.area*.5:
                        stair.evidence.setdefault('specialist_corroboration',[]).append({
                            'proposal_id':proposal['id'],'proposal_cache_key':manifest['cache_key'],
                            'scope':'plan/point support; tread/riser geometry and endpoint verification remain independent'})
                        report['corroborated_ids'].append(stair.id)
                continue
            plane=fit_vertical_plane(source,proposal['polygon_xy_m'],seeds,semantic,kind)
            if plane is None:
                report['rejected_proposals'].append({'proposal_id':proposal['id'],'reason':'original_vertical_plane_or_height_support_failed'})
                if opening_decision is not None:
                    opening_decision.update(status='rejected',reason='original_vertical_plane_or_height_support_failed',
                                            source_support_seed_count=len(seeds))
                continue
            owner=min(model.storeys,key=lambda s:abs(s.elevation-plane['base']))
            proof={'specialist_proposal_id':proposal['id'],'proposal_cache_key':manifest['cache_key'],
                'proposal_sha256':manifest['proposal_sha256'],'original_plane_rmse_m':plane['rmse'],
                'original_point_count':plane['count'],'original_z_band_counts':plane['z_band_counts'],
                'source_row_examples':plane['source_row_examples'],'source_rows_scope':'ProposalSet original source rows',
                'record_examples':[{'scan_index':int(cloud.scan_index[i]),
                    'source_record_index':int(cloud.source_record_index[i])} for i in plane['source_row_examples']],
                'geometry_validation':'original_point_plane_and_measured_extents','review_state':'unreviewed'}
            host=_wall_match(model,plane)
            if opening_decision is not None:
                opening_decision.update(original_plane_point_count=plane['count'],
                    original_plane_rmse_m=plane['rmse'],measured_width_m=plane['u_max']-plane['u_min'],
                    measured_height_m=plane['height'],host_wall_id=host.id if host else None)
            if kind=='wall':
                if host:
                    host.evidence.setdefault('specialist_corroboration',[]).append(proof)
                    report['corroborated_ids'].append(host.id);continue
                if plane['height']<1.2:continue
                identifier='specialist-fit-wall-'+content_digest({'proposal':proposal['id']})[:16]
                wall=Wall(identifier,owner.id,tuple(plane['start']),tuple(plane['end']),plane['base'],plane['height'],
                    settings.assumed_wall_thickness_m,classification='single_face_candidate',
                    provenance={'axis':'measured','height':'measured','thickness':'inferred','material':'unknown'},
                    detection_method='specialist_original_point_refit',observed_faces=[{
                        'start':plane['start'].tolist(),'end':plane['end'].tolist(),
                        'z_min':plane['base'],'z_max':plane['base']+plane['height']}],evidence=proof)
                from ..evidence import attach_evidence
                attach_evidence(cloud,[wall],min(control.chunk_points,65536),workers=1,spatial_index=index)
                if wall.evidence_count>=40:
                    model.walls.append(wall);report['added_wall_ids'].append(wall.id)
            else:
                framed,fractions=frame_support(source,plane,labels,kind)
                opening_decision['independent_frame_support_fractions']=fractions
                if not framed:
                    report['rejected_proposals'].append({'proposal_id':proposal['id'],'reason':'independent_frame_support_failed','edge_fractions':fractions})
                    opening_decision.update(status='rejected',reason='independent_frame_support_failed')
                    continue
                proof['independent_frame_support_fractions']=fractions
                if host:
                    axis=np.asarray(host.end)-host.start;axis/=np.linalg.norm(axis)
                    projected=sorted(float((p-host.start)@axis) for p in (plane['start'],plane['end']))
                    candidate=Opening('specialist-fit-opening-'+content_digest(proposal['id'])[:16],host.id,kind,
                        projected[0],max(0.,plane['base']-host.base),projected[1]-projected[0],plane['height'],
                        provenance={'dimensions':'measured','kind':'inferred','filling':'unknown'},evidence=proof)
                    candidate,boundary=fit_generated_opening(candidate,host)
                    if candidate is None:
                        report['rejected_proposals'].append({'proposal_id':proposal['id'],'reason':'host_containment_failed'})
                        opening_decision.update(status='rejected',reason='host_containment_failed')
                        continue
                    rectangle=box(candidate.offset,candidate.sill,candidate.offset+candidate.width,candidate.sill+candidate.height)
                    duplicate=next((o for o in model.openings if o.host_wall_id==host.id and
                        rectangle.intersection(box(o.offset,o.sill,o.offset+o.width,o.sill+o.height)).area
                        >.25*min(rectangle.area,o.width*o.height)),None)
                    if duplicate:
                        opening_decision.update(status='corroborated_existing_opening',element_id=duplicate.id)
                        duplicate.evidence.setdefault('specialist_corroboration',[]).append(proof)
                        report['corroborated_ids'].append(duplicate.id)
                        if duplicate.kind!=candidate.kind:
                            opening_decision.update(status='rejected',reason='conflicts_with_preserved_opening_kind')
                            report['rejected_proposals'].append({'proposal_id':proposal['id'],
                                'reason':'conflicts_with_preserved_opening_kind','element_id':duplicate.id})
                    else:
                        model.openings.append(candidate);report['added_window_ids'].append(candidate.id)
                        opening_decision.update(status='added_hosted_opening',element_id=candidate.id)
                elif kind=='window':
                    identifier='specialist-fit-facade-'+content_digest(proposal['id'])[:16]
                    panel=Wall(identifier,owner.id,tuple(plane['start']),tuple(plane['end']),plane['base'],plane['height'],.02,
                        classification='standalone_window_frame',provenance={'axis':'measured','height':'measured',
                            'thickness':'inferred','kind':'inferred','material':'unknown'},evidence_count=plane['count'],
                        fit_rmse_m=plane['rmse'],evidence=proof,detection_method='semantic_window_original_frame_plane')
                    if not any(LineString([p.start,p.end]).hausdorff_distance(LineString([panel.start,panel.end]))<.15
                               and abs(p.base-panel.base)<.15 and abs(p.height-panel.height)<.15 for p in model.facade_panels):
                        model.facade_panels.append(panel);report['added_window_ids'].append(panel.id)
                        opening_decision.update(status='added_standalone_window',element_id=panel.id)
                    else:
                        opening_decision.update(status='duplicate_standalone_window_preserved')
                else:
                    opening_decision.update(status='rejected',reason='door_requires_supported_host_wall')
        if settings.detect_openings_enabled:
            from ..features import detect_openings
            affected=[w for w in model.walls if w.id in report['added_wall_ids'] or w.evidence.get('specialist_opening_search_ids')]
            candidates=detect_openings(cloud,affected,settings,workers=1,spatial_index=index) if affected else []
            for opening in candidates:
                host=next(w for w in affected if w.id==opening.host_wall_id)
                opening.evidence['specialist_search_proposal_ids']=host.evidence.get('specialist_opening_search_ids',[])
                rectangle=box(opening.offset,opening.sill,opening.offset+opening.width,opening.sill+opening.height)
                if any(o.host_wall_id==opening.host_wall_id and rectangle.intersection(box(o.offset,o.sill,
                    o.offset+o.width,o.sill+o.height)).area>.25*min(rectangle.area,o.width*o.height) for o in model.openings):continue
                opening.id='specialist-search-opening-'+content_digest([opening.host_wall_id,opening.offset,opening.sill,opening.width,opening.height])[:16]
                model.openings.append(opening);report['added_window_ids'].append(opening.id)
        # All subsequent void generation remains the existing fail-closed policy.
        if report['added_surface_ids'] and model.stairs:
            revalidate_surface_dependencies(cloud,model,index,control,settings)
        model.validate()
    finally:
        support._mmap.close();labels._mmap.close()
    model.metadata['specialist_geometry_fusion']=report
    return report


def revalidate_surface_dependencies(cloud,model,index,control,settings):
    """New surfaces must not leave stale endpoint, collision or void results."""
    from ..slab_zones import occupancy_geometry
    from ..stair_connections import verify_stair_connections
    from ..features import derive_stair_slab_openings
    from ..stair_voids import reconcile_stair_voids
    surfaces=[]
    for stair in model.stairs:
        for xy,height in [(stair.start,stair.base),(stair.end,stair.base+stair.steps*stair.rise)]:
            radius=max(.2,stair.width*.4)
            source=SourceBox(cloud,index,[xy[0]-radius,xy[1]-radius,height-.025],
                [xy[0]+radius,xy[1]+radius,height+.025],control,1_500_000)
            cells=set();count=0
            for _,p in source.blocks():
                cells.update(map(tuple,np.floor(p[:,:2]/.04+1e-8).astype(int).tolist()));count+=len(p)
            if len(cells)<12 or count<20:continue
            geometry,_=occupancy_geometry((np.asarray(sorted(cells))+.5)*.04,.04,.04,100000)
            surfaces.append({'z':height,'geometry':geometry,'count':count})
    model.metadata['stair_connection_verification']=verify_stair_connections(model.stairs,model.slabs,model.landings,surfaces)
    # Only previously confirmed tread/riser/landing geometry can validate a cut.
    proposed,_=derive_stair_slab_openings(model.stairs,model.slabs,model.landings,
        margin_m=settings.stair_void_margin_m,headroom_m=settings.stair_headroom_m)
    model.slab_openings,validation=reconcile_stair_voids(model.slabs,model.slab_openings,proposed,
        model.stairs,model.landings,headroom_m=settings.stair_headroom_m)
    model.metadata['stairwell_verification']=validation
