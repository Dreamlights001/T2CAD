from copy import deepcopy
import math

import pytest
pytest.importorskip("cadgen", reason="几何测试使用 scripts/test.sh 中的 T2CAD-CAD 环境")
from cadgen import build123d as bd, read_step

from backend.cadgen_engine import build, number, CADFailure
from backend.examples import EXAMPLES, f, p
from backend.schema import Design


@pytest.mark.parametrize("key,size", [("plate", [100, 60, 8]), ("flange", [90, 90, 28]), ("sleeve", [48, 48, 45]), ("bracket", [80, 50, 61]), ("housing", [100, 70, 35])])
def test_examples_and_step_roundtrip(key, size, tmp_path):
    design = Design.model_validate(EXAMPLES[key]).model_dump()
    steps = list(build(design))
    assert len(steps) == len(design["features"])
    _, model, metrics = steps[-1]
    assert metrics["size"] == pytest.approx(size)
    assert metrics["solids"] == 1
    path = tmp_path / "part.step"
    bd.export_step(model, path)
    restored = read_step(path)
    assert restored.is_valid
    assert restored.volume == pytest.approx(metrics["volume"], rel=1e-7)


def test_hole_diameter_has_correct_volume_effect():
    design = deepcopy(EXAMPLES["plate"])
    before = list(build(design))[-1][2]["volume"]
    next(p for p in design["parameters"] if p["name"] == "hole_d")["value"] = 8
    after = list(build(design))[-1][2]["volume"]
    assert before - after == pytest.approx(4 * math.pi * (4**2 - 3**2) * 8)


def test_tessellated_history_does_not_inflate_measurements(tmp_path):
    for feature, model, metrics in build(EXAMPLES["flange"]):
        bd.export_stl(model, tmp_path / (feature["id"] + ".stl"))
    assert metrics["size"] == pytest.approx([90, 90, 28], abs=1e-6)


def test_new_combination_polygon_rib():
    design = deepcopy(EXAMPLES["bracket"])
    design["features"] += [
        f("rib", "三角加强筋", "extrude", plane="XZ", origin=[0, 3, 6], profile={"type": "polygon", "points": [[-34, 0], [-34, 45], [5, 0]]}, distance=6),
        f("rib_join", "连接加强筋", "union", target="hole_b", tool="rib"),
    ]
    assert list(build(design))[-1][2]["solids"] == 1


def test_revolve_and_patterns():
    design = {"name": "旋转轴套", "parameters": [], "features": [f("shaft", "旋转", "revolve", plane="XZ", profile={"type": "polygon", "points": [[10, 0], [20, 0], [20, 30], [10, 30]]}, angle=360)]}
    assert list(build(design))[-1][2]["volume"] == pytest.approx(math.pi * 300 * 30)
    for op, args in [("linear_pattern", {"step": [15, 0, 0]}), ("polar_pattern", {"angle": 360})]:
        design["features"] = [f("pin", "圆柱", "cylinder", radius=2, height=5, origin=[10, 0, 0]), f("pattern", "阵列", op, source="pin", count=4, **args)]
        assert list(build(design))[-1][2]["solids"] == 4


@pytest.mark.parametrize("expr", ["__import__('os').system('true')", "x.__class__", "2**10000", "1/0", "nan", "[1]*9999999"])
def test_expression_rejects_code(expr):
    with pytest.raises(Exception):
        number(expr, {"x": 1})


def test_invalid_hole_and_fillet():
    for op, args in [("hole", {"diameter": -5}), ("fillet", {"radius": 1000})]:
        design = deepcopy(EXAMPLES["plate"])
        design["features"].append(f("bad", "错误特征", op, **args))
        with pytest.raises(CADFailure, match="bad"):
            list(build(design))


def test_unused_hole_parameters_reveal_missing_feature():
    design = deepcopy(EXAMPLES["plate"])
    design["features"] = design["features"][:1]
    with pytest.raises(CADFailure, match="hole_d"):
        list(build(design))


def test_parametric_hole_layouts():
    design = deepcopy(EXAMPLES["plate"])
    args = design["features"][-1]["args"]
    args.pop("points")
    args["layout"] = {"type": "rect_corners", "margin_x": "margin", "margin_y": "margin"}
    shape = list(build(design))[-1][1]
    for x in (-38, 38):
        for y in (-18, 18):
            assert not shape.is_inside((x, y, 4))
            assert shape.is_inside((x+3.5, y, 4))
    design = {"name": "圆周孔", "parameters": [], "features": [f("disk", "圆盘", "cylinder", radius=45, height=10), f("holes", "螺栓孔", "hole", diameter=7, layout={"type": "bolt_circle", "radius": 33, "count": 4})]}
    shape = list(build(design))[-1][1]
    for x, y in [(33, 0), (-33, 0), (0, 33), (0, -33)]:
        assert not shape.is_inside((x, y, 5))


def test_expected_size_catches_valid_but_short_part():
    design = {"name": "轴套目标尺寸", "parameters": [p("height", "总高", 45)], "expected_size": [36, 36, "height"], "features": [f("body", "短了6毫米", "cylinder", radius=18, height="height-6")]}
    with pytest.raises(CADFailure, match="实测 39 mm，要求 45 mm"):
        list(build(design))


def test_parametric_straight_gear_uses_module_and_teeth():
    design = {
        "name": "模数2直齿轮",
        "expected_size": [None, None, "h"],
        "parameters": [p("m", "模数", 2), p("z", "齿数", 17, "count"), p("h", "厚度", 20)],
        "features": [f("gear", "齿轮主体", "gear", module="m", teeth="z", height="h")],
    }
    feature, model, metrics = list(build(design))[-1]
    assert metrics["size"][0] > 37
    assert metrics["size"][1] > 37
    assert metrics["size"][2] == pytest.approx(20, abs=1e-5)
    assert metrics["solids"] == 1
    design["parameters"][0]["value"] = 3
    changed = list(build(design))[-1][2]
    assert changed["size"][0] > 56
    assert changed["size"][1] > 56
    assert changed["size"][2] == pytest.approx(20, abs=1e-5)


def test_gear_involute_flanks_reach_base_and_addendum_circles():
    design = {
        "name": "渐开线测试齿轮", "expected_size": [None, None, 10],
        "parameters": [p("m", "模数", 2), p("z", "齿数", 20, "count"), p("h", "厚度", 10)],
        "features": [f("gear", "渐开线齿轮", "gear", module="m", teeth="z", height="h")],
    }
    _, model, metrics = list(build(design))[-1]
    pitch = 2 * 20 / 2
    base = pitch * math.cos(math.radians(20))
    outer = pitch + 2
    assert metrics["size"][0] > 2 * (outer - 0.2)
    assert model.is_valid
    assert metrics["volume"] > math.pi * base * base * 10


def test_gear_pitch_tooth_thickness_and_composed_bore():
    design = {
        "name": "带孔直齿轮", "parameters": [p("m", "模数", 2), p("z", "齿数", 17, "count"), p("h", "厚度", 20)],
        "features": [f("gear", "渐开线齿轮", "gear", module="m", teeth="z", height="h")],
    }
    _, gear, before = list(build(design))[-1]
    # The tooth has angular half-thickness pi/(2*z) on the pitch circle.
    for tooth in range(17):
        center = tooth * 2 * math.pi / 17
        for offset, inside in [(0, True), (math.pi / 34 - .003, True), (math.pi / 34 + .003, False)]:
            angle = center + offset
            assert gear.is_inside((17 * math.cos(angle), 17 * math.sin(angle), 10)) == inside
    design["features"].append(f("bore", "中心通孔", "hole", target="gear", diameter=8))
    _, bored, after = list(build(design))[-1]
    assert after["solids"] == 1
    assert not bored.is_inside((0, 0, 10))
    assert not bored.is_inside((0, 3.99, 10))
    assert bored.is_inside((0, 4.01, 10))
    assert before["volume"] - after["volume"] == pytest.approx(math.pi * 4**2 * 20, rel=1e-7)


@pytest.mark.parametrize("beta", [15, -15])
def test_helical_gear_normal_system_flanks_and_axial_bore(beta):
    design = {
        "name": "法向斜齿轮", "expected_size": [None, None, "h"],
        "parameters": [p("m", "法向模数", 2), p("z", "齿数", 17, "count"), p("h", "厚度", 20),
                       p("alpha", "法向压力角", 20, "deg"), p("beta", "螺旋角", beta, "deg"), p("bore_d", "内孔", 12)],
        "features": [f("gear", "斜齿主体", "gear", module="m", teeth="z", height="h", pressure_angle="alpha", helix_angle="beta"),
                     f("bore", "轴向通孔", "hole", target="gear", diameter="bore_d")],
    }
    steps = list(build(design))
    before, gear, metrics = steps[0][2], steps[-1][1], steps[-1][2]
    spec = metrics["gear"]
    pitch_radius = 17/math.cos(math.radians(beta))
    twist = 20*math.tan(math.radians(beta))/pitch_radius
    assert spec["transverse_module"] == pytest.approx(2/math.cos(math.radians(beta)))
    assert spec["transverse_pressure_angle"] == pytest.approx(20.64689648704647)
    assert spec["tip_diameter"] == pytest.approx(2*pitch_radius+4)
    assert spec["twist_angle"] == pytest.approx(math.degrees(twist))
    assert spec["hand"] == ("right" if beta > 0 else "left")
    assert metrics["size"][2] == pytest.approx(20, abs=1e-5)
    assert metrics["solids"] == 1
    assert before["volume"]-metrics["volume"] == pytest.approx(math.pi*6**2*20, rel=1e-6)
    for height in (1, 10, 19):
        assert not gear.is_inside((5.99, 0, height))
        assert gear.is_inside((6.01, 0, height))
        for tooth in range(17):
            center = tooth*2*math.pi/17 + height/20*twist
            for offset, inside in [(0, True), (math.pi/34-.005, True), (math.pi/34+.005, False)]:
                angle = center+offset
                assert gear.is_inside((pitch_radius*math.cos(angle), pitch_radius*math.sin(angle), height)) == inside


def test_helical_transverse_system_matches_converted_normal_system():
    args = {"module": 2, "teeth": 17, "height": 20, "pressure_angle": 20, "helix_angle": 15}
    design = {"name": "斜齿换算", "parameters": [], "features": [f("gear", "斜齿轮", "gear", **args)]}
    _, normal, metrics = list(build(design))[-1]
    args.update(module_system="transverse", module=metrics["gear"]["transverse_module"], pressure_angle=metrics["gear"]["transverse_pressure_angle"])
    design["features"] = [f("gear", "端面斜齿轮", "gear", **args)]
    _, transverse, converted = list(build(design))[-1]
    assert converted["volume"] == pytest.approx(metrics["volume"], rel=1e-7)
    assert converted["gear"]["normal_module"] == pytest.approx(2)
    assert converted["gear"]["twist_angle"] == pytest.approx(metrics["gear"]["twist_angle"])


@pytest.mark.parametrize("extra", [{"helix_angle": 46}, {"helix_angle": -46}, {"module_system": "unknown"}])
def test_invalid_helical_gear_settings(extra):
    design = {"name": "错误斜齿轮", "parameters": [], "features": [f("gear", "斜齿轮", "gear", module=2, teeth=17, height=20, **extra)]}
    with pytest.raises(CADFailure, match="gear"):
        list(build(design))
