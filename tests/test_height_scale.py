"""Display scale uses complete original f64 bounds, independent of sampling."""
import numpy as np
from punctora_core import projects
from punctora_core.cloud_io import CloudData


def test_unsampled_height_extremes_are_saved_and_preview_is_display_only(tmp_path,monkeypatch):
    points=np.array([[0.,0.,-4.123456789],[0.,0.,1.],[1.,1.,2.],[2.,2.,12.987654321]])
    cloud=CloudData(points)
    monkeypatch.setattr(projects,'spatial_preview_indices',lambda p,count:np.array([1,2]))
    monkeypatch.setattr(projects,'PREVIEW_LIMIT',2)
    preview=projects.write_preview(cloud,tmp_path,'generation')
    assert preview['height_scale']['minimum_z_m']==points[0,2]
    assert preview['height_scale']['maximum_z_m']==points[-1,2]
    assert np.fromfile(tmp_path/'preview.bin',dtype='<f4').reshape(-1,6)[:,2].tolist()==[1.,2.]
    np.testing.assert_array_equal(cloud.points,points)


def test_import_bounds_reused_without_an_extra_full_cloud_reduction(tmp_path,monkeypatch):
    cloud=CloudData(np.array([[0.,0.,1.],[1.,1.,2.]]))
    bounds={'minimum':[0.,0.,-5.123456789],'maximum':[1.,1.,15.987654321]}
    preview=projects.write_preview(cloud,tmp_path,'generation',bounds)
    assert preview['height_scale']['minimum_z_m']==bounds['minimum'][2]
    assert preview['height_scale']['maximum_z_m']==bounds['maximum'][2]
