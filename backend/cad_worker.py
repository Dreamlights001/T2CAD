"""Run cadgen model source; all final formats share the same native geometry."""
import json
import os
from pathlib import Path
import resource
import subprocess
import sys

from backend.cadgen_job import model_source


def main():
    folder = Path(sys.argv[1]).resolve()
    process = None
    try:
        limit = int(os.getenv("T2CAD_CAD_MEMORY_MB", "6144"))*1024**2
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
        design = json.loads((folder / "design.json").read_text())
        source = folder / "model.py"
        source.write_text(model_source(design))
        process = subprocess.Popen([sys.executable, str(source), "--force", "--verbose"], cwd=folder,
                                   stdout=subprocess.PIPE, stderr=sys.stderr, text=True)
        for line in process.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "feature":
                print(json.dumps(event, ensure_ascii=False), flush=True)
        if process.wait() != 0 or not (folder / "model.result.json").is_file():
            log = folder / "worker.log"
            detail = log.read_text(errors="replace") if log.exists() else "请查看 worker.log"
            for line in reversed(detail.splitlines()):
                if "CADFailure: " in line:
                    detail = line.split("CADFailure: ", 1)[1]
                    break
            raise ValueError("cadgen 构建失败：" + detail[-5000:])
        result = json.loads((folder / "model.result.json").read_text())
        import trimesh
        mesh = trimesh.load(str(folder / "model.stl"), force="mesh")
        result["mesh"] = {"watertight": bool(mesh.is_watertight), "vertices": len(mesh.vertices), "faces": len(mesh.faces)}
        if not mesh.is_watertight:
            raise ValueError("cadgen STL 不是封闭网格")
        command = os.getenv("FREECAD_CMD", str(Path.home() / ".local/opt/freecad/squashfs-root/usr/bin/freecadcmd"))
        if Path(command).is_file():
            conversion = folder / "export_fcstd.py"
            conversion.write_text("import FreeCAD as App\nimport Part\ndoc=App.newDocument('Model')\nobj=doc.addObject('Part::Feature','Result')\nobj.Shape=Part.read(" + repr(str(folder / "model.step")) + ")\ndoc.recompute()\ndoc.saveAs(" + repr(str(folder / "model.FCStd")) + ")\n")
            with (folder / "freecad-export.log").open("w") as log:
                try:
                    subprocess.run([command, str(conversion)], stdout=log, stderr=log, timeout=30)
                except subprocess.TimeoutExpired:
                    pass
            if (folder / "model.FCStd").exists():
                result["exports"].append("FCStd")
        (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps({"type": "complete", "data": result}, ensure_ascii=False), flush=True)
    except Exception as exc:
        print(json.dumps({"type": "error", "data": {"message": str(exc)}}, ensure_ascii=False), flush=True)
        sys.exit(1)
    finally:
        if process and process.poll() is None:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
