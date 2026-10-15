"""Add supported model results with explicit alignment and immutable evidence origins."""
from copy import deepcopy
from dataclasses import asdict
from math import dist
import numpy as np
from shapely.geometry import Polygon,box
from .model import BuildingModel
from .opening_bounds import fit_generated_opening,proposal_record

COLLECTIONS=('storeys','walls','slabs','spaces','openings','stairs','landings','slab_openings','facade_panels')


def alignment_for(target,source,matrix=None,confirm_shared_frame=False):
    a,b=target.metadata,source.metadata
    same_source=(a.get('source',{}).get('sha256') is not None and
                 a['source']['sha256']==b.get('source',{}).get('sha256'))
    same_project=(a.get('project_id') is not None and a.get('project_id')==b.get('project_id')
                  and a.get('source',{}).get('sha256')==b.get('source',{}).get('sha256'))
    if matrix is not None:
        result=np.asarray(matrix,dtype=float)
        basis='explicit user-supplied alignment'
    else:
        am,bm=a.get('coordinate_mapping'),b.get('coordinate_mapping')
        ac,bc=a.get('e57',{}).get('coordinate_metadata'),b.get('e57',{}).get('coordinate_metadata')
        known_frame=bool(ac and ac==bc)
        if not (same_source or same_project or known_frame or confirm_shared_frame):
            raise ValueError('Different scans require confirmed shared source coordinates or explicit alignment')
        if am and bm:
            result=np.linalg.inv(np.asarray(am['working_to_source_matrix'],float))@np.asarray(bm['working_to_source_matrix'],float)
            basis='shared source frame, converted between local project origins'
        elif same_project or confirm_shared_frame:
            result=np.eye(4);basis='same project frame' if same_project else 'user-confirmed common local frame'
        else:raise ValueError('Source coordinate mappings are missing; provide explicit alignment')
    if (result.shape!=(4,4) or not np.isfinite(result).all()
            or not np.allclose(result[3],[0,0,0,1],atol=1e-9)
            or not np.allclose(result[:3,:3].T@result[:3,:3],np.eye(3),atol=1e-9)
            or not np.isclose(np.linalg.det(result[:3,:3]),1,atol=1e-9)
            or not np.allclose(result[2,:3],[0,0,1],atol=1e-9)):
        raise ValueError('Model alignment must be finite, rigid, metre-preserving and Z-up')
    return result,basis


def transform_model(model,matrix):
    result=BuildingModel.from_dict(model.to_dict());dz=float(matrix[2,3])
    def xy(p):return (matrix[:2,:2]@np.asarray(p)+matrix[:2,3]).tolist()
    for s in result.storeys:
        s.elevation+=dz;s.ceiling+=dz;s.footprint=[xy(p) for p in s.footprint]
    for w in result.walls+result.facade_panels:
        w.start,w.end=xy(w.start),xy(w.end);w.base+=dz
        for f in w.observed_faces:
            f['start'],f['end']=xy(f['start']),xy(f['end'])
            for key in ('z_min','z_max','observed_z_min_m','observed_z_max_m'):
                if key in f:f[key]+=dz
            for c in f.get('supported_extent_columns',[]):
                c['start_xy'],c['end_xy']=xy(c['start_xy']),xy(c['end_xy'])
                c['bottom_m']+=dz;c['top_m']+=dz
    for obj in result.slabs+result.spaces+result.landings:
        obj.base+=dz;obj.footprint=[xy(p) for p in obj.footprint]
    for obj in result.stairs+result.slab_openings:
        obj.start,obj.end=xy(obj.start),xy(obj.end)
        if hasattr(obj,'base'):obj.base+=dz
        if getattr(obj,'footprint',None):obj.footprint=[xy(p) for p in obj.footprint]
    return result


def _wall_shape(wall,frame):
    axis=(np.asarray(frame.end)-frame.start)/dist(frame.start,frame.end)
    own=(np.asarray(wall.end)-wall.start)/dist(wall.start,wall.end)
    ring=wall.profile_xz or [(0,0),(dist(wall.start,wall.end),0),(dist(wall.start,wall.end),wall.height),(0,wall.height)]
    return Polygon([(float((np.asarray(wall.start)+own*x-frame.start)@axis),wall.base+z-frame.base) for x,z in ring])


def _same_wall_plane(a,b):
    da=(np.asarray(a.end)-a.start)/dist(a.start,a.end)
    db=(np.asarray(b.end)-b.start)/dist(b.start,b.end)
    normal=np.array([-da[1],da[0]])
    return (abs(float(da@db))>=np.cos(np.deg2rad(1.))
            and (abs(a.thickness-b.thickness)<=.02 or a.provenance.get('thickness')=='user_supplied')
            and max(abs(float((np.asarray(p)-a.start)@normal)) for p in (b.start,b.end))<=.01)


def merge_models(existing,incoming,namespace='added',alignment_matrix=None,confirm_shared_frame=False):
    existing.validate();incoming.validate()
    matrix,basis=alignment_for(existing,incoming,alignment_matrix,confirm_shared_frame)
    result=BuildingModel.from_dict(existing.to_dict());source=transform_model(incoming,matrix)
    context={'project_id':incoming.metadata.get('project_id'),'source':deepcopy(incoming.metadata.get('source')),
        'coordinate_mapping':deepcopy(incoming.metadata.get('coordinate_mapping')),
        'to_project_matrix':matrix.tolist(),'alignment_basis':basis}
    ids={o.id for c in COLLECTIONS for o in getattr(result,c)};mapping={}
    for c in COLLECTIONS:
        for obj in getattr(source,c):
            candidate=namespace+'-'+obj.id;suffix=1
            while candidate in ids:suffix+=1;candidate=namespace+'-'+obj.id+'-'+str(suffix)
            mapping[obj.id]=candidate;ids.add(candidate)
    for c in COLLECTIONS:
        for obj in getattr(source,c):
            old=obj.id;obj.id=mapping[old]
            if hasattr(obj,'evidence'):
                obj.evidence['source_context']=deepcopy(context)
                obj.evidence['source_element_id']=old
            for name in ('storey_id','host_wall_id','host_slab_id','source_stair_id'):
                value=getattr(obj,name,None)
                if value in mapping:setattr(obj,name,mapping[value])
            if hasattr(obj,'connected_stair_ids'):obj.connected_stair_ids=[mapping[x] for x in obj.connected_stair_ids]
            for name in ('system_id','source_system_id'):
                value=getattr(obj,name,None)
                if value:setattr(obj,name,namespace+'-'+value)
            if hasattr(obj,'evidence'):
                obj.evidence.pop('facade_system',None)
    report={'alignment_basis':basis,'to_project_matrix':matrix.tolist(),'duplicates_removed':{},
            'added':{},'review_candidates':[],'source':context,
            'reconstruction_inputs':{k:deepcopy(incoming.metadata.get(k)) for k in
                ('reconstruction_options','reconstruction_scope','crop')}}
    def corroborate(target,other):
        if hasattr(target,'evidence'):
            target.evidence.setdefault('additional_sources',[]).append({'source_context':deepcopy(context),
                'element_id':other.evidence.get('source_element_id',other.id),
                'geometry':{k:v for k,v in asdict(other).items() if k not in ('evidence','preview_geometry')},
                'evidence':{k:deepcopy(v) for k,v in other.evidence.items() if k!='additional_sources'}})
            target.evidence['additional_sources'].extend(deepcopy(other.evidence.get('additional_sources',[])))
    level_map={}
    for level in source.storeys:
        duplicate=next((s for s in result.storeys if abs(s.elevation-level.elevation)<.01
            and abs(s.ceiling-level.ceiling)<.01 and s.provenance==level.provenance),None)
        if duplicate:level_map[level.id]=duplicate.id
        else:result.storeys.append(level);level_map[level.id]=level.id
    for c in COLLECTIONS[1:]:
        for obj in getattr(source,c):
            if hasattr(obj,'storey_id'):obj.storey_id=level_map[obj.storey_id]
    old_hosts={w.id:deepcopy(w) for w in source.walls}
    host_map={};removed_walls=0
    for wall in source.walls:
        duplicate=None
        for current in result.walls:
            if not _same_wall_plane(current,wall):continue
            a,b=_wall_shape(current,current),_wall_shape(wall,current)
            if a.buffer(.001).covers(b):duplicate=current;break
        if duplicate:
            host_map[wall.id]=duplicate.id;corroborate(duplicate,wall);removed_walls+=1
        else:result.walls.append(wall);host_map[wall.id]=wall.id
    for panel in source.facade_panels:
        duplicate=next((p for p in result.facade_panels if _same_wall_plane(p,panel)
            and _wall_shape(p,p).buffer(.001).covers(_wall_shape(panel,p))),None)
        if duplicate:corroborate(duplicate,panel)
        else:result.facade_panels.append(panel)
    slab_map={};removed_slabs=0
    for slab in source.slabs:
        duplicate=next((s for s in result.slabs if abs(s.base-slab.base)<.001
            and abs(s.thickness-slab.thickness)<.001 and Polygon(s.footprint).symmetric_difference(
                Polygon(slab.footprint)).area<=1e-6),None)
        if duplicate:slab_map[slab.id]=duplicate.id;corroborate(duplicate,slab);removed_slabs+=1
        else:result.slabs.append(slab);slab_map[slab.id]=slab.id
    hosts={w.id:w for w in result.walls};removed_openings=0
    for opening in source.openings:
        old=old_hosts[opening.host_wall_id];target=hosts[host_map[old.id]]
        direction=(np.asarray(old.end)-old.start)/dist(old.start,old.end)
        centre=np.asarray(old.start)+direction*(opening.offset+opening.width/2)
        axis=(np.asarray(target.end)-target.start)/dist(target.start,target.end)
        opening.host_wall_id=target.id
        opening.offset=float((centre-target.start)@axis)-opening.width/2
        opening.sill=old.base+opening.sill-target.base
        if direction@axis<0 and opening.evidence.get('signed_interior_depth_m') is not None:
            opening.evidence['signed_interior_depth_m']*=-1
        candidate,bounds=fit_generated_opening(opening,target)
        if candidate is None:report['review_candidates'].append(bounds);continue
        duplicate=next((o for o in result.openings if o.host_wall_id==candidate.host_wall_id
            and max(abs(getattr(o,k)-getattr(candidate,k)) for k in ('offset','sill','width','height'))<.01),None)
        if duplicate:corroborate(duplicate,candidate);removed_openings+=1
        else:result.openings.append(candidate)
    stair_map={};system_map={};removed_stairs=0;removed_landings=0
    for stair in source.stairs:
        duplicate=next((s for s in result.stairs if s.steps==stair.steps
            and np.allclose(s.start,stair.start,atol=.001,rtol=0)
            and np.allclose(s.end,stair.end,atol=.001,rtol=0)
            and max(abs(getattr(s,k)-getattr(stair,k)) for k in
                    ('base','width','rise','going','tread_thickness'))<.001),None)
        if duplicate:
            stair_map[stair.id]=duplicate.id
            if stair.system_id:system_map[stair.system_id]=duplicate.system_id
            corroborate(duplicate,stair);removed_stairs+=1
        else:result.stairs.append(stair);stair_map[stair.id]=stair.id
    for stair in result.stairs:
        if stair.system_id in system_map:stair.system_id=system_map[stair.system_id]
    for landing in source.landings:
        landing.connected_stair_ids=[stair_map[x] for x in landing.connected_stair_ids]
        if landing.system_id in system_map:landing.system_id=system_map[landing.system_id]
        duplicate=next((s for s in result.landings if abs(s.base-landing.base)<.001
            and abs(s.thickness-landing.thickness)<.001
            and Polygon(s.footprint).symmetric_difference(Polygon(landing.footprint)).area<1e-6),None)
        if duplicate:corroborate(duplicate,landing);removed_landings+=1
        else:result.landings.append(landing)
    for space in source.spaces:
        if not any(abs(s.base-space.base)<.001 and abs(s.height-space.height)<.001
            and Polygon(s.footprint).symmetric_difference(Polygon(space.footprint)).area<1e-6 for s in result.spaces):
            result.spaces.append(space)
    for opening in source.slab_openings:
        opening.host_slab_id=slab_map[opening.host_slab_id]
        if opening.source_stair_id:opening.source_stair_id=stair_map[opening.source_stair_id]
        if opening.source_system_id in system_map:opening.source_system_id=system_map[opening.source_system_id]
        if not any(o.host_slab_id==opening.host_slab_id and np.allclose(o.start,opening.start,atol=.001)
            and np.allclose(o.end,opening.end,atol=.001) and abs(o.width-opening.width)<.001 for o in result.slab_openings):
            result.slab_openings.append(opening)
    report['duplicates_removed']={'walls':removed_walls,'slabs':removed_slabs,'openings':removed_openings,
                                  'stairs':removed_stairs,'landings':removed_landings}
    report['added']={c:len(getattr(result,c))-len(getattr(existing,c)) for c in COLLECTIONS}
    result.metadata.setdefault('additive_runs',[]).append(report)
    result.metadata['reconstruction_scope']='combined'
    result.warnings=list(dict.fromkeys([*result.warnings,*source.warnings]))
    result.warnings.append('Additive reconstruction preserves prior edits and evidence. Shared-source alignment is not a new CRS or accuracy certification.')
    if report['review_candidates']:result.warnings.append(f"Additive merge: {len(report['review_candidates'])} opening proposals retained for review because the preserved host cannot contain them.")
    from .glazed_facades import refresh_repeated_window_groups
    refresh_repeated_window_groups(result.walls,result.openings)
    from .reproducibility import geometry_signature
    result.metadata['reproducibility']=geometry_signature(result)
    result.validate()
    return result,report
