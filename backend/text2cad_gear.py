"""Compile the structured gear feature into an upstream Text2CAD FreeCAD job."""
import json
import math
from pathlib import Path


def gear_script(design: dict) -> str:
    params = {p["name"]: p["value"] for p in design["parameters"]}
    gear = next((f for f in design["features"] if f["op"] == "gear"), None)
    if not gear or len(design["features"]) != 1:
        raise ValueError("Text2CAD FreeCAD gear runner currently accepts one gear feature; add holes as a follow-up feature after this path is enabled.")
    args = gear["args"]
    module = float(params[args["module"]]) if isinstance(args["module"], str) else float(args["module"])
    teeth = int(params[args["teeth"]]) if isinstance(args["teeth"], str) else int(args["teeth"])
    height = float(params[args["height"]]) if isinstance(args["height"], str) else float(args["height"])
    pressure = float(args.get("pressure_angle", 20.0))
    if teeth < 4 or module <= 0 or height <= 0:
        raise ValueError("invalid gear parameters")
    payload = {"module": module, "teeth": teeth, "height": height, "pressure_angle": pressure}
    return f'''import FreeCAD as App
import Part
import os, json
import math

P = {json.dumps(payload)}
m = P["module"]
z = int(P["teeth"])
h = P["height"]
alpha = math.radians(P["pressure_angle"])
rp = m * z / 2.0
rb = rp * math.cos(alpha)
ra = rp + m
rf = max(rp - 1.25 * m, m)
pitch = 2.0 * math.pi / z
tp = math.sqrt((rp / rb) ** 2 - 1.0)
base_offset = math.pi / (2.0 * z) - (tp - math.atan(tp))
ta = math.sqrt((ra / rb) ** 2 - 1.0)
pts = []
samples = 14
for i in range(z):
    center = i * pitch
    if i == 0:
        pts.append(App.Vector(rf * math.cos(center - pitch / 2.0), rf * math.sin(center - pitch / 2.0), 0))
    for j in range(samples, -1, -1):
        t = ta * j / samples
        phi = t - math.atan(t)
        radius = rb * math.sqrt(1.0 + t * t)
        angle = center - (base_offset + phi)
        pts.append(App.Vector(radius * math.cos(angle), radius * math.sin(angle), 0))
    for j in range(samples + 1):
        t = ta * j / samples
        phi = t - math.atan(t)
        radius = rb * math.sqrt(1.0 + t * t)
        angle = center + (base_offset + phi)
        pts.append(App.Vector(radius * math.cos(angle), radius * math.sin(angle), 0))
    if i < z - 1:
        pts.append(App.Vector(rf * math.cos(center + pitch / 2.0), rf * math.sin(center + pitch / 2.0), 0))
wire = Part.makePolygon(pts + [pts[0]])
solid = Part.Face(wire).extrude(App.Vector(0, 0, h))
doc = App.newDocument("Model")
obj = doc.addObject("Part::Feature","Result"); obj.Shape = solid; doc.recompute()
out_path = os.path.join(os.getcwd(),"result.step")
obj.Shape.exportStep(out_path)
print(json.dumps({{"checks": {{"bbox": [obj.Shape.BoundBox.XMin,obj.Shape.BoundBox.YMin,obj.Shape.BoundBox.ZMin,obj.Shape.BoundBox.XMax,obj.Shape.BoundBox.YMax,obj.Shape.BoundBox.ZMax], "volume": float(obj.Shape.Volume)}}}}))
'''
