"""Structured feature compiler for earthtojake/text-to-cad's build123d runtime.

This source is embedded in downloadable model.py files; keep it standalone.
"""
import ast
import math
import operator


class CADFailure(ValueError):
    pass


def number(value, parameters, used=None):
    if type(value) in (float, int):
        result = float(value)
    elif isinstance(value, str) and len(value) <= 160:
        ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}

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


def shape_metrics(shape):
    from cadgen.geometry import is_sound
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    if not shape.solids() or not is_sound(shape) or shape.volume <= 1e-8:
        raise CADFailure("建模结果不是有效的非空实体")
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    bounds = list(box.Get())
    size = [bounds[i+3] - bounds[i] for i in range(3)]
    if max(size) > 10000:
        raise CADFailure("零件尺寸超过 10000 mm")
    return {"volume": shape.volume, "area": shape.area, "solids": len(shape.solids()),
            "bounds": bounds, "size": size, "valid": True}


def build(design):
    from cadgen import build123d as bd

    params = {p["name"]: p["value"] for p in design["parameters"]}
    used = set()
    n = lambda value: number(value, params, used)
    objects = {}
    datums = {}
    gear_specs = {}
    current = None
    current_id = None
    alignment = (bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)

    def vector(value):
        if not isinstance(value, list) or len(value) != 3:
            raise CADFailure("向量必须包含三个坐标")
        return tuple(n(v) for v in value)

    def select(items, selector):
        if not isinstance(selector, str) or len(selector) != 2 or selector[0] not in "|<>" or selector[1] not in "XYZ":
            raise CADFailure("选择器仅支持 |X/|Y/|Z 和 >X/<X/>Y/<Y/>Z/<Z")
        axis = getattr(bd.Axis, selector[1])
        if selector[0] == "|":
            return items.filter_by(axis)
        return items.group_by(axis)[-1 if selector[0] == ">" else 0]

    for feature in design["features"]:
        fid, op, a = feature["id"], feature["op"], feature.get("args", {})
        try:
            datum = datums.get(a.get("target", current_id)) if op in ("hole", "cut_extrude", "union", "cut", "intersect", "fillet", "chamfer") else None
            gear_spec = gear_specs.get(a.get("target", current_id)) if datum is not None else None
            def positive(key, default=None):
                value = n(a.get(key, default))
                if value <= 0:
                    raise CADFailure(f"{key} 必须大于零")
                return value

            def base():
                target = objects.get(a["target"]) if "target" in a else current
                if target is None:
                    raise CADFailure("操作需要已有的 target 实体")
                return target

            def plane():
                name = a.get("plane", "XY")
                if name not in ("XY", "XZ", "YZ"):
                    raise CADFailure("plane 必须为 XY/XZ/YZ")
                default = getattr(bd.Plane, name)
                return bd.Plane(origin=vector(a.get("origin", [0, 0, 0])), x_dir=default.x_dir, z_dir=default.z_dir)

            def profile():
                p = a.get("profile", {"type": "rect", "width": a.get("width"), "height": a.get("height")})
                kind = p.get("type")
                if kind == "rect":
                    w, h = n(p["width"]), n(p["height"])
                    if min(w, h) <= 0:
                        raise CADFailure("草图宽高必须大于零")
                    sketch = bd.Rectangle(w, h)
                elif kind == "circle":
                    radius = n(p["radius"])
                    if radius <= 0:
                        raise CADFailure("半径必须大于零")
                    sketch = bd.Circle(radius)
                elif kind == "polygon":
                    if not 3 <= len(p["points"]) <= 100:
                        raise CADFailure("多边形需要 3 至 100 个点")
                    sketch = bd.Polygon(*[(n(x), n(y)) for x, y in p["points"]], align=None)
                else:
                    raise CADFailure("profile.type 必须为 rect/circle/polygon")
                return plane() * sketch

            gear_dimensions = []
            if op == "box":
                obj = plane() * bd.Box(positive("width"), positive("depth"), positive("height"), align=alignment)
            elif op == "cylinder":
                obj = plane() * bd.Cylinder(positive("radius"), positive("height"), align=alignment)
            elif op == "gear":
                from bd_warehouse.gear import SpurGearPlan
                module, teeth, height = positive("module"), n(a["teeth"]), positive("height")
                pressure = n(a.get("pressure_angle", 20))
                beta = n(a.get("helix_angle", 0))
                system = a.get("module_system", "normal")
                if teeth != int(teeth) or not 4 <= teeth <= 200:
                    raise CADFailure("齿数必须是 4 至 200 的整数")
                if not 14 <= pressure <= 30:
                    raise CADFailure("压力角必须在 14 至 30 度之间")
                if abs(beta) > 45:
                    raise CADFailure("螺旋角必须在 -45 至 45 度之间；正值右旋，负值左旋")
                if system not in ("normal", "transverse"):
                    raise CADFailure("module_system 必须为 normal（法向）或 transverse（端面）")
                cosine = math.cos(math.radians(beta))
                mt = module/cosine if system == "normal" else module
                mn = module if system == "normal" else module*cosine
                at = math.degrees(math.atan(math.tan(math.radians(pressure))/cosine)) if system == "normal" else pressure
                an = pressure if system == "normal" else math.degrees(math.atan(math.tan(math.radians(pressure))*cosine))
                pitch = mt*teeth
                twist = math.degrees(2*height*math.tan(math.radians(beta))/pitch)
                if abs(twist) > 360:
                    raise CADFailure("单次斜齿扫掠总扭转角不能超过360度，请减小厚度或螺旋角")
                # Odd tooth counts have asymmetric bounds; preserve the rotational axis.
                gear = SpurGearPlan(module=mt, tooth_count=int(teeth), pressure_angle=at,
                                    addendum=mn, dedendum=1.25*mn, align=None)
                if abs(twist) < 1e-8:
                    solid = bd.extrude(gear, amount=height)
                else:
                    solid = bd.Solid.extrude_linear_with_rotation(gear.faces()[0], (0, 0, 0), (0, 0, height), twist)
                obj = plane() * solid
                datum = bd.Vector(plane().origin)
                gear_spec = {"module_system": system, "module": module, "normal_module": mn, "transverse_module": mt,
                             "pressure_angle": pressure, "normal_pressure_angle": an, "transverse_pressure_angle": at,
                             "teeth": int(teeth), "height": height, "helix_angle": beta, "twist_angle": twist,
                             "hand": "right" if beta > 0 else "left" if beta < 0 else "spur",
                             "pitch_diameter": pitch, "base_diameter": pitch*math.cos(math.radians(at)),
                             "tip_diameter": pitch+2*mn, "root_diameter": pitch-2.5*mn,
                             "lead": math.pi*pitch/abs(math.tan(math.radians(beta))) if beta else None}
            elif op in ("extrude", "cut_extrude"):
                depth = n(a["distance"])
                if abs(depth) < 1e-6:
                    raise CADFailure("拉伸距离不能为零")
                tool = bd.extrude(profile(), amount=depth)
                obj = base() - tool if op == "cut_extrude" else tool
                if op == "cut_extrude" and abs(obj.volume-base().volume) < 1e-6:
                    raise CADFailure("切除未移除材料，请检查轮廓和位置")
            elif op == "revolve":
                start, end = a.get("axis_start", [0, 0]), a.get("axis_end", [0, 1])
                p = plane()
                s = p.from_local_coords((n(start[0]), n(start[1]), 0))
                e = p.from_local_coords((n(end[0]), n(end[1]), 0))
                obj = bd.revolve(profile(), axis=bd.Axis(s, e-s), revolution_arc=positive("angle", 360))
            elif op == "hole":
                target = base()
                selected = select(target.faces(), a.get("face", ">Z"))
                if len(selected) != 1 or selected[0].geom_type != bd.GeomType.PLANE:
                    raise CADFailure("钻孔面必须为唯一平面，请明确 face 或使用 cut_extrude")
                face = selected[0]
                normal = face.normal_at()
                x_dir = (0, 1, 0) if abs(normal.X) > 0.99 else (1, 0, 0)
                center = face.center(bd.CenterOf.BOUNDING_BOX)
                if datum is not None:
                    center = datum + normal * (center-datum).dot(normal)
                p = bd.Plane(origin=center, x_dir=x_dir, z_dir=normal)
                local = p.to_local_coords(face).bounding_box()
                extent = [local.min.X, local.max.X, local.min.Y, local.max.Y]
                diameter = positive("diameter")
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
                depth = positive("depth") if a.get("depth") is not None else target.bounding_box().diagonal*2+1
                tools = [p * bd.Pos(n(x), n(y), 1e-5) * bd.Cylinder(diameter/2, depth+1e-5, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MAX)) for x, y in points]
                obj = target.cut(*tools)
                if abs(obj.volume-target.volume) < 1e-6:
                    raise CADFailure(f"钻孔未移除材料；孔位以面中心为原点，工作平面范围 {extent}，当前孔位 {points}")
            elif op in ("union", "cut", "intersect"):
                tool = objects[a["tool"]]
                obj = {"union": lambda: base()+tool, "cut": lambda: base()-tool,
                       "intersect": lambda: base() & tool}[op]()
            elif op in ("fillet", "chamfer"):
                edges = select(base().edges(), a.get("edges", "|Z"))
                if not edges:
                    raise CADFailure("未选中可加工边")
                obj = bd.fillet(edges, positive("radius")) if op == "fillet" else bd.chamfer(edges, positive("distance"))
            elif op in ("linear_pattern", "polar_pattern"):
                source = objects[a["source"]]
                count = n(a["count"])
                if count != int(count) or not 1 <= count <= 32:
                    raise CADFailure("阵列数量必须是 1 至 32 的整数")
                obj = source
                for i in range(1, int(count)):
                    if op == "linear_pattern":
                        other = source.moved(bd.Pos(*(i*v for v in vector(a["step"]))))
                    else:
                        axis = bd.Axis(vector(a.get("axis_origin", [0, 0, 0])), vector(a.get("axis_direction", [0, 0, 1])))
                        other = source.rotate(axis, i*n(a.get("angle", 360))/count)
                    obj = obj + other
            else:
                raise CADFailure(f"未知操作: {op}")
            if "translate" in a:
                offset = vector(a["translate"])
                obj = obj.moved(bd.Pos(*offset))
                if datum is not None:
                    datum = datum + bd.Vector(offset)
            if "rotate" in a:
                r = a["rotate"]
                start, end = bd.Vector(vector(r["start"])), bd.Vector(vector(r["end"]))
                obj = obj.rotate(bd.Axis(start, end-start), n(r["angle"]))
                if datum is not None:
                    datum = bd.Vertex(datum).rotate(bd.Axis(start, end-start), n(r["angle"])).center()
            obj.label = feature["name"]
            metrics = shape_metrics(obj)
            if gear_spec is not None:
                metrics["gear"] = gear_spec
                gear_dimensions = [{"label": key, "value": value, "unit": unit} for key, value, unit in [
                    ("法向模数" if gear_spec["module_system"] == "normal" and gear_spec["helix_angle"] else "模数", gear_spec["module"], "mm"),
                    ("齿数", gear_spec["teeth"], "count"), ("压力角", gear_spec["pressure_angle"], "deg"),
                    ("基圆直径", gear_spec["base_diameter"], "mm"), ("齿顶圆直径", gear_spec["tip_diameter"], "mm")]]
                if gear_spec["helix_angle"] or "helix_angle" in a:
                    # Keep angle callouts clear of the viewport's bounding dimensions.
                    gear_dimensions = [
                        {"label": "法向压力角" if gear_spec["module_system"] == "normal" else "端面压力角",
                         "value": gear_spec["pressure_angle"], "unit": "deg"},
                        {"label": "螺旋角", "value": gear_spec["helix_angle"], "unit": "deg"},
                    ]
                gear_specs[fid] = gear_spec
            labels = {"width": "宽度", "depth": "深度", "height": "高度", "radius": "半径", "diameter": "孔径", "distance": "距离", "angle": "角度"}
            metrics["dimensions"] = [{"label": label, "value": n(a[key]), "unit": "deg" if key == "angle" else "mm"} for key, label in labels.items() if key in a and a[key] is not None] + gear_dimensions
            objects[fid] = obj
            if datum is not None:
                datums[fid] = datum
            current = obj
            current_id = fid
            yield feature, obj, metrics
        except Exception as exc:
            raise CADFailure(f"特征 {fid} ({feature['name']}, {op}): {exc}") from exc
    unused = set(params) - used
    if unused:
        raise CADFailure("设计未完成：这些参数未被几何操作使用：" + ", ".join(sorted(unused)))
    for axis, expected in enumerate(design.get("expected_size") or []):
        if expected is not None and abs(metrics["size"][axis]-n(expected)) > 1e-4:
            raise CADFailure(f"最终外形尺寸不符合目标：{'XYZ'[axis]} 实测 {metrics['size'][axis]:g} mm，要求 {n(expected):g} mm")
