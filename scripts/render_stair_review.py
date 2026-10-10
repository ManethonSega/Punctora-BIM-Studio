"""Headless before/after geometry plates, not desktop screenshots or ground truth."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from punctora_core.model import BuildingModel, slab_opening_footprint


def render(model, output):
    levels = sorted(model.storeys, key=lambda s:s.elevation)
    image = np.full((540*((len(levels)+1)//2), 1200, 3), (30,25,20), np.uint8)
    for index, level in enumerate(levels):
        x0,y0 = (index%2)*600,(index//2)*540
        coordinates = np.array(level.footprint)
        low,high = coordinates.min(axis=0)-.4,coordinates.max(axis=0)+.4
        scale = min(530/(high[0]-low[0]),430/(high[1]-low[1]))
        def pixels(coords):
            xy = (np.array(coords)-low)*scale
            return np.column_stack([x0+35+xy[:,0],y0+495-xy[:,1]]).astype(np.int32)
        cv2.putText(image,level.name,(x0+25,y0+30),cv2.FONT_HERSHEY_SIMPLEX,.6,(240,240,240),1)
        cv2.putText(image,'Plan of ceiling slab, walls and flights',(x0+25,y0+55),
                    cv2.FONT_HERSHEY_SIMPLEX,.4,(170,170,170),1)
        for slab in model.slabs:
            if abs(slab.base-level.ceiling) > .4:
                continue
            holes = [Polygon(slab_opening_footprint(o)) for o in model.slab_openings
                     if o.host_slab_id == slab.id and o.review_state != 'rejected']
            body = Polygon(slab.footprint).difference(unary_union(holes))
            pieces = [body] if isinstance(body,Polygon) else list(body.geoms)
            for piece in pieces:
                if piece.is_empty:
                    continue
                cv2.fillPoly(image,[pixels(piece.exterior.coords)],(80,70,55))
                for ring in piece.interiors:
                    cv2.fillPoly(image,[pixels(ring.coords)],(30,25,20))
        for wall in model.walls:
            if wall.storey_id == level.id:
                polygon = LineString([wall.start,wall.end]).buffer(wall.thickness/2,cap_style=2)
                cv2.polylines(image,[pixels(polygon.exterior.coords)],True,(180,180,180),1)
        for flight in model.stairs:
            if flight.base >= level.ceiling or flight.base+flight.steps*flight.rise <= level.elevation:
                continue
            start,end = np.array(flight.start),np.array(flight.end)
            for step in range(flight.steps):
                z = flight.base+(step+1)*flight.rise
                if not level.elevation-.05 <= z <= level.ceiling+.3:
                    continue
                a,b = start+(end-start)*step/flight.steps,start+(end-start)*(step+1)/flight.steps
                polygon = LineString([a,b]).buffer(flight.width/2,cap_style=2)
                inferred = step in flight.evidence.get('inferred_missing_step_indices',[])
                cv2.polylines(image,[pixels(polygon.exterior.coords)],True,
                              (80,170,245) if inferred else (220,180,60),2)
        for landing in model.landings:
            if level.elevation-.1 <= landing.base+landing.thickness <= level.ceiling+.3:
                cv2.polylines(image,[pixels(landing.footprint)],True,(90,230,130),2)
        cv2.putText(image,'Blue: treads | Orange: inferred | Green: landings',
                    (x0+25,y0+525),cv2.FONT_HERSHEY_SIMPLEX,.36,(210,210,210),1)
    output.parent.mkdir(parents=True,exist_ok=True)
    if not cv2.imwrite(str(output),image):
        raise OSError('Could not write review image')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args()
    render(BuildingModel.from_dict(json.loads(args.model.read_text(encoding='utf-8'))),args.output)
