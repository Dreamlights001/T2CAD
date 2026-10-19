"""Standalone deterministic CAD compiler; also embedded in exported Python scripts."""
import ast
import math
import operator

import cadquery as cq
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box


class CADFailure(ValueError):
    pass


def number(value, parameters, used=None):
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        result = float(value)
    elif isinstance(value, str) and len(value) <= 160:
        ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
               ast.Div: operator.truediv}

        def visit(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                return float(node.value)
            if isinstance(node, ast.Name) and node.id in parameters:
                if used is not None:
                    used.add(node.id)
                return parameters[node.id]
            if isinstance(node, ast.BinOp) and type(node.op) in ops:
                return ops[type(node.op)](visit(node.left), visit(node.right))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
                return (-1 if isinstance(node.op, ast.USub) else 1) * visit(node.operand)
            raise CADFailure("只允许参数名、数字和 + - * / 算术表达式")

        result = visit(ast.parse(value, mode="eval").body)
    else:
        raise CADFailure(f"无效的数值: {value!r}")
    if not math.isfinite(result) or abs(result) > 100000:
        raise CADFailure("数值必须有限且绝对值不超过 100000")
    return result


def build(design):
    params = {p["name"]: p["value"] for p in design["parameters"]}
    used = set()
    n = lambda v: number(v, params, used)
    objects = {}
    current = None
    for feature in design["features"]:
        fid, op, a = feature["id"], feature["op"], feature.get("args", {})
        try:
            def positive(key, default=None):
                value = n(a[key] if key in a else default)
                if value <= 0:
                    raise CADFailure(f"{key} 必须大于零")
                return value

            def vec(value):
                if not isinstance(value, list) or len(value) != 3:
                    raise CADFailure("向量必须包含三个坐标")
                return tuple(n(x) for x in value)

            def base():
                if "target" in a:
                    if a["target"] not in objects:
                        raise CADFailure(f"找不到 target: {a['target']}")
                    return objects[a["target"]]
                if current is None:
                    raise CADFailure("操作需要已有实体")
                return current

            def plane():
                label = a.get("plane", "XY")
                if label not in ("XY", "XZ", "YZ"):
                    raise CADFailure("plane 必须为 XY/XZ/YZ")
                return cq.Workplane(label, origin=vec(a.get("origin", [0, 0, 0])))

            def profile():
                w = plane()
                p = a.get("profile", {"type": "rect", "width": a.get("width"), "height": a.get("height")})
                kind = p.get("type")
                if kind == "rect":
                    width, height = n(p["width"]), n(p["height"])
                    if min(width, height) <= 0:
                        raise CADFailure("草图宽高必须大于零")
                    return w.rect(width, height)
                if kind == "circle":
                    r = n(p["radius"])
                    if r <= 0:
                        raise CADFailure("半径必须大于零")
                    return w.circle(r)
                if kind == "polygon":
                    points = p["points"]
                    if not 3 <= len(points) <= 100:
                        raise CADFailure("多边形需要 3 至 100 个点")
                    return w.polyline([(n(x), n(y)) for x, y in points]).close()
                raise CADFailure("profile.type 必须为 rect/circle/polygon")

            if op == "box":
                obj = plane().box(positive("width"), positive("depth"), positive("height"), centered=(True, True, False))
            elif op == "cylinder":
                obj = plane().circle(positive("radius")).extrude(positive("height"))
            elif op == "gear":
                module = positive("module")
                teeth = n(a.get("teeth"))
                height = positive("height")
                pressure_angle = n(a.get("pressure_angle", 20.0))
                if teeth != int(teeth) or not 4 <= teeth <= 200:
                    raise CADFailure("齿数必须是 4 至 200 的整数")
                if not 14 <= pressure_angle <= 30:
                    raise CADFailure("压力角必须在 14 至 30 度之间")
                teeth = int(teeth)
                pitch_radius = module * teeth / 2
                base_radius = pitch_radius * math.cos(math.radians(pressure_angle))
                root_radius = max(module * (teeth - 2.5) / 2, module)
                outer_radius = pitch_radius + module
                if root_radius >= outer_radius or base_radius <= 0:
                    raise CADFailure("模数和齿数不能生成有效齿轮轮廓")
                points = []
                tooth_pitch = 2 * math.pi / teeth
                half_tooth_angle = math.pi / (2 * teeth)
                pitch_t = math.sqrt((pitch_radius / base_radius) ** 2 - 1)
                base_offset = half_tooth_angle - (pitch_t - math.atan(pitch_t))
                outer_t = math.sqrt((outer_radius / base_radius) ** 2 - 1)
                samples = 10
                for i in range(teeth):
                    center = i * tooth_pitch
                    # The two flanks are mirror images of the involute from base circle to addendum circle.
                    if i == 0:
                        points.append((root_radius * math.cos(center - tooth_pitch / 2),
                                       root_radius * math.sin(center - tooth_pitch / 2)))
                    for j in range(samples, -1, -1):
                        t = outer_t * j / samples
                        phi = t - math.atan(t)
                        radius = base_radius * math.sqrt(1 + t * t)
                        angle = center - (base_offset + phi)
                        points.append((radius * math.cos(angle), radius * math.sin(angle)))
                    for j in range(samples + 1):
                        t = outer_t * j / samples
                        phi = t - math.atan(t)
                        radius = base_radius * math.sqrt(1 + t * t)
                        angle = center + (base_offset + phi)
                        points.append((radius * math.cos(angle), radius * math.sin(angle)))
                    if i < teeth - 1:
                        points.append((root_radius * math.cos(center + tooth_pitch / 2),
                                       root_radius * math.sin(center + tooth_pitch / 2)))
                obj = plane().polyline(points).close().extrude(height)
            elif op in ("extrude", "cut_extrude"):
                depth = n(a["distance"])
                if abs(depth) < 1e-6:
                    raise CADFailure("拉伸距离不能为零")
                tool = profile().extrude(depth)
                obj = base().cut(tool) if op == "cut_extrude" else tool
            elif op == "revolve":
                obj = profile().revolve(positive("angle", 360), tuple(n(v) for v in a.get("axis_start", [0, 0])),
                                        tuple(n(v) for v in a.get("axis_end", [0, 1])))
            elif op == "hole":
                target = base()
                diameter = positive("diameter")
                selected = target.faces(a.get("face", ">Z"))
                if selected.size() != 1:
                    raise CADFailure("钻孔面必须唯一，请使用更明确的面选择条件")
                w = selected.workplane(centerOption="CenterOfBoundBox")
                face_box = Bnd_Box()
                BRepBndLib.AddOptimal_s(selected.val().wrapped, face_box, False, False)
                fb = face_box.Get()
                corners = [w.plane.toLocalCoords(cq.Vector(x, y, z)) for x in (fb[0], fb[3]) for y in (fb[1], fb[4]) for z in (fb[2], fb[5])]
                extent = [min(v.x for v in corners), max(v.x for v in corners), min(v.y for v in corners), max(v.y for v in corners)]
                layout = a.get("layout")
                if layout:
                    if "points" in a:
                        raise CADFailure("钻孔的 layout 和 points 只能选择一种")
                    if layout["type"] == "rect_corners":
                        mx, my = n(layout["margin_x"]), n(layout["margin_y"])
                        if mx < diameter/2 or my < diameter/2 or mx >= (extent[1]-extent[0])/2 or my >= (extent[3]-extent[2])/2:
                            raise CADFailure("四角孔边距必须不小于孔半径，且小于对应半边长")
                        points = [[x, y] for x in (extent[0]+mx, extent[1]-mx) for y in (extent[2]+my, extent[3]-my)]
                    elif layout["type"] == "bolt_circle":
                        radius, count = n(layout["radius"]), n(layout["count"])
                        if radius <= 0 or count != int(count) or not 1 <= count <= 32:
                            raise CADFailure("分布圆半径必须为正，孔数必须为1至32的整数")
                        angle = n(layout.get("start_angle", 0))
                        points = [[radius*math.cos(math.radians(angle+i*360/count)), radius*math.sin(math.radians(angle+i*360/count))] for i in range(int(count))]
                    else:
                        raise CADFailure("layout.type 仅支持 rect_corners 或 bolt_circle")
                else:
                    points = a.get("points", [[0, 0]])
                if not 1 <= len(points) <= 100:
                    raise CADFailure("一次钻孔需要 1 至 100 个孔位")
                w = w.pushPoints([(n(x), n(y)) for x, y in points])
                obj = w.hole(diameter, positive("depth") if a.get("depth") is not None else None)
                if abs(obj.val().Volume() - target.val().Volume()) < 1e-6:
                    raise CADFailure(f"钻孔未移除材料。孔位以面中心为原点，工作平面范围 u=[{extent[0]:g},{extent[1]:g}], v=[{extent[2]:g},{extent[3]:g}]。当前孔位={points}；请用正负半宽/半长减边距定位，并让连续钻孔 target 引用前一步。")
            elif op in ("union", "cut", "intersect"):
                tool = objects[a["tool"]]
                obj = getattr(base(), op)(tool)
            elif op in ("fillet", "chamfer"):
                obj = getattr(base().edges(a.get("edges", "|Z")), op)(positive("radius" if op == "fillet" else "distance"))
            elif op in ("linear_pattern", "polar_pattern"):
                source = objects[a["source"]]
                count = n(a["count"])
                if count != int(count) or not 1 <= count <= 32:
                    raise CADFailure("阵列数量必须是 1 至 32 的整数")
                obj = source
                for i in range(1, int(count)):
                    if op == "linear_pattern":
                        delta = vec(a["step"])
                        other = source.translate(tuple(i * v for v in delta))
                    else:
                        origin = vec(a.get("axis_origin", [0, 0, 0]))
                        axis = vec(a.get("axis_direction", [0, 0, 1]))
                        other = source.rotate(origin, tuple(x + y for x, y in zip(origin, axis)), i * n(a.get("angle", 360)) / int(count))
                    obj = obj.union(other)
            else:
                raise CADFailure(f"未知操作: {op}")
            if "translate" in a:
                obj = obj.translate(vec(a["translate"]))
            if "rotate" in a:
                rotation = a["rotate"]
                obj = obj.rotate(vec(rotation["start"]), vec(rotation["end"]), n(rotation["angle"]))
            shape = obj.val()
            if not isinstance(shape, cq.Shape) or not shape.isValid() or shape.Volume() <= 1e-8 or not shape.Solids():
                raise CADFailure("建模结果不是有效的非空实体")
            exact_box = Bnd_Box()
            BRepBndLib.AddOptimal_s(shape.wrapped, exact_box, False, False)
            bounds = list(exact_box.Get())
            size = [bounds[i + 3] - bounds[i] for i in range(3)]
            if max(size) > 10000:
                raise CADFailure("零件尺寸超过 10000 mm")
            objects[fid] = obj
            current = obj
            metrics = {"volume": shape.Volume(), "area": shape.Area(), "solids": len(shape.Solids()),
                       "bounds": bounds, "size": size, "valid": True}
            dimension_keys = {"width": "宽度", "depth": "深度", "height": "高度", "radius": "半径", "diameter": "孔径", "distance": "距离", "angle": "角度"}
            metrics["dimensions"] = [{"label": label, "value": n(a[key]), "unit": "deg" if key == "angle" else "mm"}
                                     for key, label in dimension_keys.items() if key in a and a[key] is not None]
            if op == "gear":
                metrics["dimensions"].extend([
                    {"label": "模数", "value": module, "unit": "mm"},
                    {"label": "齿数", "value": teeth, "unit": "count"},
                    {"label": "压力角", "value": pressure_angle, "unit": "deg"},
                    {"label": "基圆直径", "value": 2 * base_radius, "unit": "mm"},
                    {"label": "齿顶圆直径", "value": 2 * outer_radius, "unit": "mm"},
                ])
            if a.get("profile", {}).get("type") == "circle":
                metrics["dimensions"].append({"label": "轮廓直径", "value": n(a["profile"]["radius"]) * 2, "unit": "mm"})
            yield feature, obj, metrics
        except Exception as exc:
            raise CADFailure(f"特征 {fid} ({feature['name']}, {op}): {exc}") from exc
    unused = set(params) - used
    if unused:
        raise CADFailure("设计未完成：这些参数没有被任何几何操作引用，可能遗漏了孔、槽等特征：" + ", ".join(sorted(unused)) + "。请补全特征并通过参数名引用尺寸，不要删除参数。")
    for axis, expected in enumerate(design.get("expected_size") or []):
        if expected is not None and abs(metrics["size"][axis] - n(expected)) > 1e-4:
            raise CADFailure(f"最终外形尺寸不符合目标：{'XYZ'[axis]} 实测 {metrics['size'][axis]:g} mm，要求 {n(expected):g} mm。请检查各特征的 origin、height、distance 和布尔合并；不要修改目标尺寸。")
