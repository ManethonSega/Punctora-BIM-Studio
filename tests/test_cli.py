import json
import numpy as np
import pytest

from punctora_core.cli import main
from punctora_core.cloud_io import write_xyz
from punctora_core.fixtures import demo_cloud


def test_xyz_cli_converts_millimetres_and_writes_validated_model(tmp_path, capsys):
    cloud = demo_cloud()
    cloud.points *= 1000
    source = tmp_path / "floor.xyz"
    write_xyz(cloud, source)
    original = source.read_bytes()
    output = tmp_path / "result"
    assert main(["convert-xyz", str(source), "--units", "mm", "--output-dir", str(output)]) == 0
    model = json.loads((output / "elements.json").read_text())
    assert model["units"] == "metres"
    assert model["storeys"][0]["ceiling"] == pytest.approx(3)
    assert json.loads((output / "validation.json").read_text())["valid"]
    assert source.read_bytes() == original
    assert json.loads(capsys.readouterr().out)["walls"] == 5


def test_cli_refuses_to_overwrite_input_with_model_output(tmp_path):
    source = tmp_path / "elements.json"
    write_xyz(demo_cloud(), source)
    original = source.read_bytes()
    with pytest.raises(SystemExit) as exc:
        main(["convert-xyz", str(source), "--units", "m", "--output-dir", str(tmp_path)])
    assert exc.value.code == 2
    assert source.read_bytes() == original
    assert not (tmp_path / "model.ifc").exists()
