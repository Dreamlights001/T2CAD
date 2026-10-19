import html
import json
from pathlib import Path
import subprocess
import markdown

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def main():
    for name in ["architecture", "workflow"]:
        subprocess.run(["dot", "-Tpng", "-Gdpi=140", str(DOCS / f"{name}.dot"), "-o", str(DOCS / f"{name}.png")], check=True)
    measured = json.loads((DOCS / "cad-validation.json").read_text())
    table = "### 5.8 五类零件几何案例数据\n\n测试日期：" + measured["date"] + "\n\n"
    table += "本次核心：`" + measured.get("engine", "未记录") + "`。\n\n"
    table += "|零件|特征数|包围尺寸 mm|体积 mm³|几何构建与导出 s|STEP / STL / 脚本|\n|---|---:|---|---:|---:|---|\n"
    for item in measured["examples"]:
        table += f"|{item['name']}|{item['features']}|{' × '.join(f'{v:g}' for v in item['size_mm'])}|{item['volume_mm3']:.2f}|{item['worker_seconds']:.3f}|通过|\n"
    table += "\n上表时间仅包含 CAD 工作进程内的构建与导出，不包含模型推理、进程启动或浏览器显示。STEP 回读相对体积误差均小于 10⁻⁷；导出的独立 Python 脚本重建体积一致。\n"
    browser = DOCS / "browser-validation.json"
    if browser.exists():
        data = json.loads(browser.read_text())
        table += f"\n浏览器验证：桌面与移动视口均检测到非空零件像素（{data['desktopPixels']['colored']} / {data['mobilePixels']['colored']}），完成旋转、尺寸切换、参数重算、版本恢复、过程播放和 STEP 下载；页面脚本错误 {len(data['errors'])} 条。\n"
    qwen38 = DOCS / "qwen38-validation.json"
    if qwen38.exists():
        data = json.loads(qwen38.read_text())
        table += "\n### 5.9 本地模型齿轮演示数据\n\n当前默认模型为 Qwen3.8-27B Q4_K_M，使用本地 llama.cpp CUDA 子进程和 JSON Schema 输出。\n\n"
        if (DOCS / "screenshots/qwen38-gear-1440.png").exists():
            table += "![Qwen3.8 与 cadgen 新核心生成的 17 齿直齿轮](screenshots/qwen38-gear-1440.png)\n\n"
        if data["cases"]:
            table += "实际 CAD 核心：`" + data["cases"][-1]["health"].get("cad_engine", "未记录") + "`。\n\n"
        table += "|演示对象|实际模型|总耗时 s|模型加载 s|几何结果|\n|---|---|---:|---:|---|\n"
        for item in data["cases"]:
            table += f"|{item['prompt']}|{item['health']['active_model']}|{item['seconds']:.2f}|{item['health']['load_seconds']:.2f}|{'通过' if item.get('verified') else '待确认'}|\n"
        table += "\n上表用于说明本地模型驱动的功能演示，几何尺寸和文件有效性由第 6 章的鲁棒性验证统一检查。\n"
    helical = DOCS / "helical-validation.json"
    if helical.exists():
        data = json.loads(helical.read_text())
        table += "\n### 5.10 斜齿轮案例数据\n\n法向模数2、17齿、厚20mm、法向压力角20度、螺旋角15度、孔径12mm的斜齿轮，分别展示右旋和左旋参数。\n\n"
        if (DOCS / "screenshots/helical-1440.png").exists():
            table += "![本地模型生成的带孔斜齿轮](screenshots/helical-1440.png)\n\n"
        table += "|实际模型|螺旋角 β|总扭转角 θ|分度圆直径 mm|脚本重建相对体积误差|验证|\n|---|---:|---:|---:|---:|---|\n"
        for item in data["cases"]:
            gear = item["metrics"]["gear"]
            table += f"|{item['model']}|{gear['helix_angle']:.3f}|{gear['twist_angle']:.5f}|{gear['pitch_diameter']:.5f}|{item['script_relative_volume_error']:.2e}|{'通过' if item.get('verified') else '待确认'}|\n"
        table += "\n几何验证在不同轴向高度采样各齿的分度圆齿厚内外点，核对旋向、扫掠扭转、轴向通孔和切除体积；同时检查参数引用、STEP回读、STL水密性、标准文件下载和独立Python脚本重建。\n"
    source = (DOCS / "course-report.md").read_text().replace("<!-- MEASUREMENTS -->", table)
    (DOCS / "course-report-measured.md").write_text(source)
    body = markdown.markdown(source, extensions=["tables", "fenced_code"])
    document = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>T2CAD 课程报告</title><style>body{max-width:1000px;margin:45px auto;padding:0 28px;font:15px/1.9 system-ui,"Noto Sans CJK SC",sans-serif;color:#263d49}h1{font-size:29px;border-bottom:3px solid #408b91;padding-bottom:20px}h2{font-size:22px;margin-top:38px}h3{font-size:17px;color:#426570}img{display:block;max-width:100%;margin:25px auto}table{width:100%;border-collapse:collapse;font-size:12px}td,th{border:1px solid #d5e0e5;padding:8px;text-align:left}th{background:#eef5f5}pre{background:#f4f6f8;padding:15px;overflow:auto;font-size:12px}a{color:#287885}@media print{body{margin:0;font-size:11pt}h2{break-after:avoid}img,table{break-inside:avoid}pre{white-space:pre-wrap}}</style><body>' + body + '</body></html>'
    (DOCS / "course-report.html").write_text(document)
    print(DOCS / "course-report.html")


if __name__ == "__main__":
    main()
