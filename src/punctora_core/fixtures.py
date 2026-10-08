"""Generated building examples, never customer scans or pretrained data."""
import numpy as np
from .cloud_io import CloudData


def room_cloud(width=6.0, depth=4.0, floor=0.0, ceiling=3.0, offset=(0.0, 0.0), partition=True) -> CloudData:
    step = 0.05
    x = np.linspace(0, width, int(width/step)+1)
    y = np.linspace(0, depth, int(depth/step)+1)
    z = np.linspace(floor, ceiling, int((ceiling-floor)/step)+1)
    xx, yy = np.meshgrid(x, y)
    planes = [np.column_stack([xx.ravel(), yy.ravel(), np.full(xx.size, level)]) for level in [floor, ceiling]]
    xx, zz = np.meshgrid(x, z)
    planes.extend(np.column_stack([xx.ravel(), np.full(xx.size, edge), zz.ravel()]) for edge in [0, depth])
    yy, zz = np.meshgrid(y, z)
    planes.extend(np.column_stack([np.full(yy.size, edge), yy.ravel(), zz.ravel()]) for edge in [0, width])
    if partition:
        for face in [width/2-0.1, width/2+0.1]:
            planes.append(np.column_stack([np.full(yy.size, face), yy.ravel(), zz.ravel()]))
    points = np.unique(np.concatenate(planes), axis=0)
    points[:, :2] += offset
    return CloudData(points)


def demo_cloud(two_storeys=False) -> CloudData:
    first = room_cloud()
    if not two_storeys:
        return first
    # Different plan extents make leaked first-storey rooms easy to identify.
    second = room_cloud(width=4.0, depth=3.0, floor=3.2, ceiling=6.2, offset=(10.0, 0.0), partition=False)
    return CloudData(np.concatenate([first.points, second.points]))
