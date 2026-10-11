"""Large desktop payloads must not travel through bounded control lines."""
import io
import json
import uuid
from pathlib import Path

import pytest
from punctora_core import worker


def exchange(tmp_path, request):
    job_id = uuid.uuid4().hex
    directory = tmp_path / f"punctora-worker-{job_id}"
    directory.mkdir()
    request.update(protocol_version=1, job_id=job_id)
    request_file, result_file = directory / "request.json", directory / "result.json"
    request_file.write_text(json.dumps(request), encoding="utf-8")
    return {"protocol_version": 1, "job_id": job_id,
            "request_file": str(request_file), "result_file": str(result_file)}


def run(monkeypatch, control, capsys):
    monkeypatch.setattr(worker.sys, "stdin", io.StringIO(json.dumps(control)+"\n"))
    status = worker.main()
    return status, [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_large_request_and_result_preserve_original_payload(tmp_path, monkeypatch, capsys):
    payload = {"model": {"evidence": "scan\u00e9" * (4 * 1024 * 1024),
                         "coordinate": 125.123456789, "record_id": 2**53+17}}
    control = exchange(tmp_path, payload)
    assert Path(control["request_file"]).stat().st_size > 16*1024*1024
    def dispatch(request, progress):
        progress(100, "Complete")
        return request["model"]
    monkeypatch.setattr(worker, "dispatch", dispatch)
    status, messages = run(monkeypatch, control, capsys)
    assert status == 0 and [m["type"] for m in messages] == ["progress", "result_file"]
    assert max(len(json.dumps(m)) for m in messages) < 1024
    result_file = Path(control["result_file"])
    assert result_file.stat().st_size > 16*1024*1024
    result = json.loads(result_file.read_text(encoding="utf-8"))
    assert result == {"protocol_version": 1, "job_id": control["job_id"], "result": payload["model"]}
    assert not result_file.with_suffix(".tmp").exists()


def test_exchange_rejects_mismatched_job_identity(tmp_path, monkeypatch, capsys):
    control = exchange(tmp_path, {})
    request_file = Path(control["request_file"])
    data = json.loads(request_file.read_text())
    data["job_id"] = uuid.uuid4().hex
    request_file.write_text(json.dumps(data))
    status, messages = run(monkeypatch, control, capsys)
    assert status == 1 and messages[-1]["type"] == "error"
    assert "identity" in messages[-1]["message"]
    assert not Path(control["result_file"]).exists()


def test_failed_result_serialization_does_not_publish_partial_file(tmp_path, monkeypatch, capsys):
    control = exchange(tmp_path, {})
    monkeypatch.setattr(worker, "dispatch", lambda *_: {"invalid": float("nan")})
    status, messages = run(monkeypatch, control, capsys)
    assert status == 1 and messages[-1]["type"] == "error"
    assert not Path(control["result_file"]).exists()
    assert not Path(control["result_file"]).with_suffix(".tmp").exists()


def test_inline_protocol_remains_compatible(monkeypatch, capsys):
    control = {"job_id": uuid.uuid4().hex, "protocol_version": 1}
    monkeypatch.setattr(worker, "dispatch", lambda *_: {"ok": True})
    status, messages = run(monkeypatch, control, capsys)
    assert status == 0 and messages[-1]["result"] == {"ok": True}
