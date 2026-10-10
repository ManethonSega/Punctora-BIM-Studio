"""Generate local evidence rasters from an E57 cache, without publishing scan data."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
from punctora_core.cloud_io import CloudData
from punctora_core.model import BuildingModel
from punctora_core.reconstruction import ReconstructionSettings,detect_walls
from punctora_core.sampling import voxel_sample
from punctora_core.features import detect_openings

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('manifest',type=Path)
p.add_argument('model',type=Path)
p.add_argument('--storey',type=int,default=2)
p.add_argument('--output-dir',type=Path,required=True)
args=p.parse_args()
manifest=json.loads(args.manifest.read_text())
d=manifest['cache']['files']['points']
points=np.memmap(args.manifest.parent/'working-cache'/d['path'],mode='r',dtype=d['dtype'],shape=tuple(d['shape']))
level=BuildingModel.from_dict(json.loads(args.model.read_text())).storeys[args.storey-1]
settings=ReconstructionSettings(cpu_workers=2)
sample=voxel_sample(points,.025,250000,100000,(level.elevation+.04,level.ceiling-.04),2)
walls=detect_walls(sample.points,level,settings,2)
openings=detect_openings(CloudData(sample.points),walls,settings,2)
args.output_dir.mkdir(parents=True,exist_ok=True)
for wall in walls:
 a=np.asarray(wall.start);v=np.asarray(wall.end)-a;length=np.linalg.norm(v);v/=length;n=np.array([-v[1],v[0]])
 offset=np.median([(np.mean([f['start'],f['end']],axis=0)-a)@n for f in wall.observed_faces])
 relative=sample.points[:,:2]-a;x=relative@v;depth=relative@n-offset;z=sample.points[:,2]-wall.base
 cell=.05;nx,nz=int(np.ceil(length/cell)),int(np.ceil(wall.height/cell))
 raster=np.zeros((nz,nx,3),np.uint8)
 keep=(x>=0)&(x<length)&(z>=0)&(z<wall.height)&(abs(depth)<.35)
 xx,zz=(x[keep]/cell).astype(int),(z[keep]/cell).astype(int)
 raster[zz,xx]=[150,100,30]
 keep&=abs(depth)<.025
 raster[(z[keep]/cell).astype(int),(x[keep]/cell).astype(int)]=[220,220,220]
 for o in openings:
  if o.host_wall_id==wall.id:
   cv2.rectangle(raster,(int(o.offset/cell),int(o.sill/cell)),(int((o.offset+o.width)/cell),int((o.sill+o.height)/cell)),(20,220,20),1)
 image=cv2.resize(raster[::-1],None,fx=5,fy=5,interpolation=cv2.INTER_NEAREST)
 image=cv2.copyMakeBorder(image,45,5,5,5,cv2.BORDER_CONSTANT)
 cv2.putText(image,wall.id,(5,25),cv2.FONT_HERSHEY_SIMPLEX,.55,(255,255,255),1)
 cv2.imwrite(str(args.output_dir/(wall.id+'.png')),image)
report={'sample_points':len(sample.points),'walls':[vars(w) for w in walls],'openings':[vars(o) for o in openings]}
(args.output_dir/'evidence.json').write_text(json.dumps(report,indent=2))
print(json.dumps({'walls':len(walls),'openings':[(o.host_wall_id,o.kind,o.offset,o.width) for o in openings]}))
