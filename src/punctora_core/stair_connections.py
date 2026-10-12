"""Separate measured endpoint connectivity from local collision clearance."""
from shapely.geometry import Point,Polygon
from .model import confirmed_landing_geometry


def verify_stair_connections(flights,slabs,landings,floor_surfaces=(),height_tolerance_m=.08):
    report=[]
    for flight in flights:
        ends={}
        for label,xy,height in [('lower',flight.start,flight.base),
            ('upper',flight.end,flight.base+flight.steps*flight.rise)]:
            region=Point(xy).buffer(max(.15,flight.width*.35))
            candidates=[]
            for slab in slabs:
                vertical=abs(slab.base+slab.thickness-height)
                area=region.intersection(Polygon(slab.footprint)).area/region.area
                if vertical<=height_tolerance_m+1e-9 and area>=.2:
                    observed=any(abs(surface['z']-height)<=height_tolerance_m+1e-9
                        and region.intersection(surface['geometry']).area/region.area>=.2
                        and surface.get('count',0)>=20 for surface in floor_surfaces)
                    candidates.append((not observed,vertical,slab.id,slab,observed,area))
            landing_matches=[]
            for landing in landings:
                vertical=abs(landing.base+landing.thickness-height)
                area=region.intersection(Polygon(landing.footprint)).area/region.area
                if (vertical<=height_tolerance_m+1e-9 and area>=.2
                        and flight.id in landing.connected_stair_ids
                        and confirmed_landing_geometry(landing)):
                    landing_matches.append((vertical,landing.id,landing,area))
            chosen=min(candidates,key=lambda x:x[:3]) if candidates else None
            landing=min(landing_matches,key=lambda x:x[:2]) if landing_matches else None
            verified=bool((chosen and chosen[4]) or landing)
            endpoint={'status':'observed_connection' if verified else 'unresolved',
                'slab_candidate_id':None if chosen is None else chosen[3].id,
                'verified_slab_id':chosen[3].id if chosen and chosen[4] else None,
                'landing_id':None if landing is None else landing[2].id,
                'height_difference_m':None if chosen is None else chosen[1],
                'horizontal_overlap_fraction':None if chosen is None else chosen[5],
                'scope':'endpoint height, spatial adjacency and observed horizontal support'}
            ends[label]=endpoint
            flight.evidence[f'{label}_slab_id']=endpoint['verified_slab_id']
            flight.evidence[f'{label}_landing_id']=endpoint['landing_id']
        status=('connected' if all(e['status']=='observed_connection' for e in ends.values())
                else 'partial' if any(e['status']=='observed_connection' for e in ends.values())
                else 'unresolved')
        flight.evidence['endpoint_verification']=ends
        flight.evidence['connection_status']=status
        observed=flight.evidence.get('observed_step_indices',[])
        inferred=flight.evidence.get('inferred_missing_step_indices',[])
        report.append({'stair_id':flight.id,'connection_status':status,'endpoints':ends,
                       'observed_tread_count':len(observed),'inferred_tread_count':len(inferred),
                       'scope':'connectivity only; physical and headroom collisions checked separately'})
    return report
