"""One isolated desktop job per process, versioned line-delimited JSON protocol.

The desktop cancels by terminating this process tree and waiting for its exit.
Staged generations are never the saved project; OS locks release on termination.
"""
import json
import sys
import traceback
import uuid
from . import projects


def dispatch(request, progress):
    command, path = request["command"], request["project"]
    if command == "demo":
        return projects.create_project(path, request["job_id"], two_storeys=request.get("two_storeys", False), progress=progress)
    if command == "import":
        return projects.create_project(path, request["job_id"], source=request["input"], progress=progress)
    if command == "open":
        return projects.load_project(path)
    if command == "reconstruct":
        return projects.reconstruct_project(path, request, progress)
    if command == "edit":
        state = projects.load_project(path)
        projects.check_revision(state, request["expected_revision"])
        state["model"] = projects.edit_model(state, request["model"], request["element_id"], request["changes"])
        return state
    if command == "merge_walls":
        state = projects.load_project(path)
        projects.check_revision(state, request["expected_revision"])
        state["model"] = projects.merge_model_walls(state, request["model"], request["wall_ids"])
        return state
    if command == "split_wall":
        state = projects.load_project(path)
        projects.check_revision(state, request["expected_revision"])
        state["model"] = projects.split_model_wall(state, request["model"], request["wall_id"], request["offset"])
        return state
    if command == "save":
        return projects.save_project(path, request)
    if command == "save_copy":
        return projects.save_copy(path, request["destination"], request)
    if command == "export":
        return projects.export_project(path, request, progress)
    if command == "cleanup":
        return projects.cleanup_project(path)
    raise ValueError("Unknown desktop command")


def main():
    job_id = None
    def emit(kind, **data):
        print(json.dumps({"protocol_version": 1, "job_id": job_id, "type": kind, **data}, allow_nan=False), flush=True)
    try:
        line = sys.stdin.readline(16 * 1024 * 1024 + 1)
        if not line.endswith("\n") or len(line) > 16 * 1024 * 1024:
            raise ValueError("Worker request is missing or exceeds the message budget")
        request = json.loads(line, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite request")))
        job_id = request["job_id"]
        uuid.UUID(hex=job_id)
        if request.get("protocol_version") != 1:
            raise ValueError("Unsupported worker protocol version")
        result = dispatch(request, lambda percent, phase: emit("progress", percent=percent, phase=phase))
        emit("result", result=result)
        return 0
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit("error", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
