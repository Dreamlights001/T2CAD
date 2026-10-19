def p(name, label, value, unit="mm"):
    return {"name": name, "label": label, "value": value, "unit": unit}


def f(id, name, op, **args):
    return {"id": id, "name": name, "op": op, "args": args}


EXAMPLES = {
    "plate": {"name": "四孔安装板", "parameters": [p("length", "长度", 100), p("width", "宽度", 60), p("thickness", "厚度", 8), p("hole_d", "孔径", 6), p("margin", "孔边距", 12)], "features": [
        f("base", "板坯", "box", width="length", depth="width", height="thickness"),
        f("corners", "四角圆角", "fillet", radius=4, edges="|Z"),
        f("mounts", "四个安装孔", "hole", diameter="hole_d", points=[["-length/2+margin", "-width/2+margin"], ["length/2-margin", "-width/2+margin"], ["length/2-margin", "width/2-margin"], ["-length/2+margin", "width/2-margin"]])]},
    "flange": {"name": "带颈法兰", "parameters": [p("diameter", "外径", 90), p("thickness", "法兰厚度", 10), p("neck_d", "凸台外径", 44), p("neck_h", "凸台高度", 18), p("bore", "中心孔径", 24), p("hole_d", "螺栓孔径", 7), p("pcd", "孔分布圆直径", 66)], "features": [
        f("disk", "法兰盘", "cylinder", radius="diameter/2", height="thickness"),
        f("neck", "连接凸台", "cylinder", radius="neck_d/2", height="neck_h", origin=[0, 0, "thickness"]),
        f("join", "合并凸台", "union", target="disk", tool="neck"),
        f("bore_cut", "中心通孔", "hole", diameter="bore"),
        f("bolts", "第一螺栓孔", "cut_extrude", profile={"type": "circle", "radius": "hole_d/2"}, origin=["pcd/2", 0, -1], distance="thickness+2"),
        f("bolt2", "第二螺栓孔", "cut_extrude", profile={"type": "circle", "radius": "hole_d/2"}, origin=["-pcd/2", 0, -1], distance="thickness+2"),
        f("bolt3", "第三螺栓孔", "cut_extrude", profile={"type": "circle", "radius": "hole_d/2"}, origin=[0, "pcd/2", -1], distance="thickness+2"),
        f("bolt4", "第四螺栓孔", "cut_extrude", profile={"type": "circle", "radius": "hole_d/2"}, origin=[0, "-pcd/2", -1], distance="thickness+2")]},
    "sleeve": {"name": "阶梯轴套", "parameters": [p("outer_d", "外径", 36), p("inner_d", "内径", 20), p("height", "总高", 45), p("flange_d", "底缘外径", 48), p("flange_h", "底缘厚度", 6)], "features": [
        f("body", "轴套外形", "cylinder", radius="outer_d/2", height="height"),
        f("flange", "底缘", "cylinder", radius="flange_d/2", height="flange_h"),
        f("join", "合并底缘", "union", target="body", tool="flange"),
        f("bore", "贯通轴孔", "hole", diameter="inner_d"),
        f("edge", "入口倒角", "chamfer", edges=">Z", distance=1)]},
    "bracket": {"name": "L 形安装支架", "parameters": [p("length", "底板长度", 80), p("width", "支架宽度", 50), p("height", "立板高度", 55), p("wall", "板厚", 6), p("hole_d", "安装孔径", 7)], "features": [
        f("foot", "水平底板", "box", width="length", depth="width", height="wall"),
        f("wall", "垂直立板", "box", width="wall", depth="width", height="height", origin=["-length/2+wall/2", 0, "wall"]),
        f("join", "连接两板", "union", target="foot", tool="wall"),
        f("hole_a", "底板孔 A", "cut_extrude", profile={"type": "circle", "radius": "hole_d/2"}, origin=[20, -15, -1], distance="wall+2"),
        f("hole_b", "底板孔 B", "cut_extrude", profile={"type": "circle", "radius": "hole_d/2"}, origin=[20, 15, -1], distance="wall+2")]},
    "housing": {"name": "开口仪器壳体", "parameters": [p("length", "长度", 100), p("width", "宽度", 70), p("height", "高度", 35), p("wall", "壁厚", 3)], "features": [
        f("outer", "壳体毛坯", "box", width="length", depth="width", height="height"),
        f("round", "外壁圆角", "fillet", radius=4, edges="|Z"),
        f("cavity", "内部腔体", "cut_extrude", profile={"type": "rect", "width": "length-2*wall", "height": "width-2*wall"}, origin=[0, 0, "wall"], distance="height"),
        f("slot", "接线开口", "cut_extrude", plane="YZ", origin=["length/2-wall-1", 0, 18], profile={"type": "rect", "width": 20, "height": 10}, distance="wall+2")]},
}

PROMPTS = {
    "plate": "生成一个长100、宽60、厚8毫米的安装板，四角圆角4毫米。四个直径6毫米的通孔，孔中心距相邻两边均12毫米。",
    "flange": "生成带颈法兰：盘外径90毫米、厚10毫米；同心凸台外径44毫米、高18毫米；中心通孔直径24毫米；分布圆直径66毫米上均匀布置4个直径7毫米的螺栓孔。",
    "sleeve": "生成阶梯轴套：外径36、内径20、总高45毫米，底缘外径48、厚6毫米，顶端倒角1毫米。",
    "bracket": "生成L形支架：底板80×50×6毫米，左端立板厚6毫米、宽50毫米、从底板顶面向上高55毫米。底板上两个直径7毫米的通孔，位置为(20,-15)和(20,15)毫米。",
    "housing": "生成一个开口壳体，外形100×70×35毫米，壁厚和底厚均3毫米，外侧四条竖边圆角4毫米。右侧壁中心高度18毫米处开20×10毫米接线矩形孔。",
}
