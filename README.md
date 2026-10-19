# T2CAD 本地参数化 CAD 工作台

Python 后端、独立 React 前端、Qwen3.8 GGUF 权重直载。全部新建模任务使用 [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad) 的 **cadgen 0.7.24 + build123d / OpenCascade** 执行与导出；支持多轮对话、参数重算、过程回放、历史版本与 STEP / STL / GLB 导出。此次核心迁移保持前端和默认 Qwen3.8 模型不变。

## 在本机启动

```bash
cd /home/dlts/CAD系统
source ~/miniconda3/etc/profile.d/conda.sh
conda activate T2CAD
python scripts/start.py
```

默认工作台 <http://127.0.0.1:5173>，API 文档 <http://127.0.0.1:8000/docs>。端口占用时脚本自动寻找可用端口并打印真实地址；地址也写入 `logs/runtime.json`。按 Ctrl+C 同时停止前后端和推理子进程。

重复运行启动脚本会显示已有服务地址。后台服务可用 `python scripts/stop.py` 停止。

首次对话需要加载约 17.4GB Qwen3.8 Q4_K_M 权重，后续请求复用常驻 GPU 模型。界面打开不立即加载大模型；示例库和参数重算不需要推理。所有模型、对话与生成文件都保存在本机。

## 从零安装

基础环境：Ubuntu 24.04、NVIDIA 驱动、Miniconda、Node.js 20.19+ 或 22.12+、npm、curl。当前机器已有 Node.js 24 和支持 CUDA 12.4 的驱动，不需要重新安装显卡驱动，也不要求启动 FreeCAD 或 Blender。

新系统如缺少编译工具或报告绘图工具，先安装：

```bash
sudo apt update
sudo apt install -y build-essential cmake curl graphviz fonts-noto-cjk
```

```bash
cd /home/dlts/CAD系统
source ~/miniconda3/etc/profile.d/conda.sh
conda create -n T2CAD python=3.11 pip -y --override-channels -c conda-forge
conda activate T2CAD
python -m pip install -r requirements.txt
bash scripts/install_inference.sh
bash scripts/install_llama_server.sh
bash scripts/install_cad.sh
npm --prefix frontend ci
python scripts/download_model.py
python scripts/check_environment.py
python scripts/start.py
```

也可执行 `bash scripts/install.sh` 完成安装与下载。已存在的 `T2CAD` 环境会复用。模型文件下载到 `models/`，支持续传，完成后校验 SHA256；默认从 ModelScope 的 Qwen 仓库下载同一官方量化文件。其他来源：

```bash
python scripts/download_model.py --source huggingface
python scripts/download_model.py --source mirror
python scripts/download_model.py --model qwen14 --source modelscope  # 低显存回退
```

下载遇到超时，可重试相同命令。只有校验成功的文件才更名为 `.gguf`，部分下载文件以 `.part` 结尾。国内 PyPI/npm 网络慢时，可以显式选择镜像：

```bash
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
npm --prefix frontend ci --registry=https://registry.npmmirror.com
```

### Python 与前端库

|用途|库|
|---|---|
|API 与校验|FastAPI、Uvicorn、Pydantic|
|CAD 核心（独立 T2CAD-CAD 环境）|cadgen 0.7.24、build123d 0.11.1、OpenCascade 7.9.3.1.1|
|渐开线直齿轮 / 斜齿轮|bd-warehouse 0.3.0 齿廓 + build123d 直线 / 螺旋扫掠，保留真实轴心，可继续组合钻孔和布尔特征|
|网格与 GLB|trimesh、NumPy|
|模型推理|Qwen3.8 使用固定版本的 llama.cpp CUDA server；旧模型可使用 llama-cpp-python 0.3.36|
|状态与工具|psutil、huggingface-hub；SQLite 使用 Python 标准库|
|前端|React、TypeScript、Vite、Three.js、Lucide|
|验证与报告|pytest、httpx、Playwright、Markdown|

API 和推理依赖见 `requirements.txt`，CAD 依赖见 `requirements-cad.txt`；前端锁定文件为 `frontend/package-lock.json`。旧 `requirements-lock.txt` 保留早期主环境记录，不是新 CAD 环境的安装清单。CUDA 推理库通过专用脚本安装。

已有本工程环境时，只需安装新 CAD 环境并重启服务：

```bash
conda activate T2CAD
bash scripts/install_cad.sh
python scripts/check_environment.py
python scripts/stop.py
python scripts/start.py
```

安装脚本创建 `T2CAD-CAD`，避免新旧 OpenCascade Python 绑定相互冲突。等效手动命令为 `conda create -n T2CAD-CAD python=3.11 pip -y`，然后 `conda run -n T2CAD-CAD python -m pip install -r requirements-cad.txt`。主服务仍在 `T2CAD` 中启动，由后端自动调用独立 CAD Python。

### CUDA 安装方式

本机实测 GitHub 大型预编译包下载较慢，因此安装脚本默认使用 Conda 的 CUDA 12.4 开发库编译 RTX 3090 的 sm_86 内核。网络通畅时也可以执行 `bash scripts/install_inference.sh wheel` 安装官方预编译包。手动编译命令如下：

```bash
conda install -n T2CAD -y --override-channels -c nvidia/label/cuda-12.4.1 -c conda-forge cuda-nvcc cuda-cudart-dev cuda-cudart-static libcublas-dev cuda-driver-dev
conda activate T2CAD
CMAKE_ARGS="-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86 -DCUDAToolkit_ROOT=$CONDA_PREFIX -DCMAKE_CUDA_COMPILER=$CONDA_PREFIX/bin/nvcc" CMAKE_BUILD_PARALLEL_LEVEL=2 python -m pip install --force-reinstall --no-cache-dir --no-binary=llama-cpp-python llama-cpp-python==0.3.36
python scripts/check_environment.py
```

## 分别启动前后端

后端终端：

```bash
conda activate T2CAD
cd /home/dlts/CAD系统
env -u PYTHONPATH python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

前端终端：

```bash
cd /home/dlts/CAD系统/frontend
npm run dev -- --port 5173 --strictPort
```

前端通过 Vite 代理访问后端。自定义后端端口时设置 `T2CAD_API_PORT` 后启动前端。不要使用多个后端 worker；单机单 GPU 运行一个推理模型即可。启动脚本已隔离本机 ROS 注入的 `PYTHONPATH`。

## 使用与演示

1. 在“示例库”运行法兰、安装板、轴套、支架或壳体，先检查 CAD 与界面。这些标记为“内置示例”，不消耗模型推理。
2. 在对话框输入自己的设计需求，或选择示例旁的对话图标填入需求，再发送，由真实本地模型规划新设计。
3. 特征历史和底部滑块可查看每一步实际生成的几何；右侧“参数”编辑尺寸并重新计算。
4. 继续提出“中心孔改为 28mm，其他尺寸不变”等修改；成功后保存新版本。“版本”中可以回到任意成功版本继续设计。
5. 导出 STEP、STL、GLB、参数 JSON 或 Python 脚本。新脚本内嵌完整参数与特征执行代码，使用 cadgen 官方 `@step/@stl/@glb` 导出接口，可通过 `python scripts/run_cad.py /绝对路径/model.py` 重建同名文件，也可直接用 `T2CAD-CAD` 的 Python 执行。
6. 左侧“项目浏览器”旁的列表按钮打开项目管理。可直接重命名项目；删除前需要确认，删除会清理该项目的对话、版本、任务和生成文件。正在生成的项目必须先停止任务才能重命名或删除。

STEP 和 STL 使用毫米坐标、Z 轴向上；GLB 按 glTF 约定转换为米、Y 轴向上。STL 格式本身不记录单位，导入其他软件时选择毫米。

示例需求：

```text
生成一个长100、宽60、厚8毫米的安装板，四角圆角4毫米。
四个直径6毫米的通孔，孔中心距相邻两边均12毫米。
```

连续修改：

```text
把孔径改为8毫米，其他不变。
板厚增加到10毫米，保留孔位置和圆角。
把长度改为120毫米，仍保持孔中心距两侧边12毫米。
```

## 存储与配置

|位置 / 环境变量|内容|
|---|---|
|`models/`|GGUF、校验清单|
|`data/t2cad.sqlite3`|项目、对话、版本、任务、事件|
|`data/artifacts/<job>/<attempt>/`|每次尝试的参数、过程 STL、STEP、GLB、脚本与日志|
|`data/validation/`|五类零件的几何验收文件|
|`logs/`|前后端运行日志与实际地址|
|`T2CAD_MODEL_PATH`|自定义本地 Qwen3 GGUF 路径|
|`T2CAD_CONTEXT`|上下文长度，默认 8192|
|`T2CAD_MODEL_LOAD_TIMEOUT`|Qwen3.8 加载超时，默认 600 秒，支持取消|
|`T2CAD_LLAMA_SERVER`|自定义 CUDA llama-server 可执行文件路径|
|`T2CAD_DATA`|自定义数据根目录|
|`T2CAD_CAD_MEMORY_MB`|CAD 子进程地址空间上限，默认 6144MB|
|`T2CAD_CAD_PYTHON`|自定义 cadgen 环境 Python，默认同级 `T2CAD-CAD/bin/python`|

默认模型为 Qwen3.8-27B Q4_K_M，使用项目管理的本地 llama.cpp CUDA server，固定源码版本 `31288c9c66e59377f7788d920678a565bb89dd37`。Python 后端通过仅监听回环地址、带随机密钥的本地接口访问它；不依赖 Ollama 或云服务。首次请求加载权重，后续请求复用模型。

## Git 与大文件

仓库不提交模型权重、CUDA 运行时、数据库、日志和生成缓存。克隆仓库后，先在项目根目录执行 `bash scripts/install_llama_server.sh`，运行时会安装到 `runtime/llama.cpp/bin/`；再执行 `python scripts/download_model.py --model qwen38 --source modelscope`，权重会放到 `models/Qwen3.8-27B-Q4_K_M.gguf`。具体校验和与备用下载源见 `models/README.md`。这些目录被 `.gitignore` 排除，Git 上传只包含源代码、安装脚本、依赖锁定文件和报告源文件。

加载使用 `--load-mode none` 顺序读取权重，避免 17.4GB 文件大于 16GB 内存时 mmap 导致大量换页。默认 8K 上下文、单任务、不启用思考输出。冷启动需要读完整个权重文件，当前机器应预留数分钟，模型加载和生成都可取消。Qwen3.8 失败会明确报错，不自动替换成 14B；要使用旧模型必须显式设置 `T2CAD_MODEL_PATH`。健康接口同时报告默认文件和实际加载模型。安装/重建运行时执行 `bash scripts/install_llama_server.sh`。

所有新任务（示例、自然语言生成、参数重算）统一经 `cad_worker` 在独立环境运行 cadgen 模型程序。草图、拉伸、旋转、布尔、孔布局、倒角及阵列使用 build123d；渐开线齿轮使用 bd-warehouse 的齿廓实现。最终 STEP/STL/GLB 来自同一实体，保存后独立回读 STEP 验证体积并检查 STL 水密性。中间特征仍逐步发送给原有前端。

目标包围尺寸的未知轴使用 JSON `null`，设计校验入口兼容模型误写的字符串 `"null"`。模数 2、17 齿的齿顶圆直径是 38mm，但实际 XY 包围盒约为 37.79×37.94mm；规划器不得把齿顶圆直径当作矩形包围尺寸。此类规划错误在锁定纠错约束前检查，已知目标尺寸仍受保护。

斜齿轮沿用 `gear` 工具，增加 `helix_angle`（beta，-45 至 45 度，正值右旋、负值左旋）和 `module_system`（`normal` 法向制或 `transverse` 端面制）。默认法向制，规划摘要应说明此约定。`pressure_angle` 为所选制式的压力角 alpha。内孔用独立 `hole` 特征加工，为沿真实轴心的直通孔。改变 beta 后会重新生成齿廓与螺旋扫掠；beta 不是上下端面的总扭转角。单次扫掠总扭转角限制为 360 度。

例如“模数2、17齿、厚20、alpha20度、beta15度、孔12”的法向制斜齿轮：端面模数约 2.07055、端面压力角约 20.64690 度、分度圆直径约 35.19939mm、总扭转角约 17.44616 度。最终指标保存法向/端面参数、导程和旋向，原有界面显示螺旋角及孔径。换算依据见 [KHK 齿轮尺寸计算，第4.3节](https://khkgears.net/new/gear_knowledge/gear_technical_reference/calculation_gear_dimensions.html)。本原型不包含滚刀齿根包络、变位、修缘或制造精度认证。

真实模型斜齿轮与多轮旋向修改验收：`python scripts/validate_helical.py`，结果保存为 `docs/helical-validation.json`，同时检查独立 Python 脚本重建与导出一致。

本机检测到 FreeCAD 时额外把 STEP 导入并保存为 FCStd，以兼容现有导出菜单；这是交换实体文档，不包含原生 FreeCAD 参数特征树。可通过 `FREECAD_CMD` 指定 freecadcmd。CAD 主建模不依赖 FreeCAD 或 Blender。cadgen 遥测、更新检查和后台 daemon 在运行环境中关闭。

已有项目、历史文件和对话保留；旧版本的结果不会自动重写。重新计算参数或继续对话会生成采用新核心的新版本。旧 MLYengineering runner 和 CadQuery 源文件仅保留历史参考，不在当前新建模调用链上，`T2CAD_CAD_ENGINE` 不再控制路由。

## 测试与课程材料

```bash
conda activate T2CAD
bash scripts/test.sh
python scripts/run_cad.py scripts/validate_cad.py
npm --prefix frontend run build
cd frontend
npx playwright install chromium
npx playwright test
```

课程报告见 `docs/course-report.md` 和 `docs/course-report.html`；演示步骤见 `docs/demo.md`。报告中的几何与浏览器实测结果由相应 JSON 文件生成，不将固定示例的成功率当作大模型成功率。

带实测数据的 Markdown 为 `docs/course-report-measured.md`，可直接打印的 PDF 为 `docs/course-report.pdf`。重新生成报告：

```bash
python scripts/render_report.py
node frontend/scripts/capture-report.mjs --pdf
```

真实模型验收命令为 `python scripts/validate_llm.py`。本机记录表明，安装板及三轮修改可直接完成；阶梯轴套和法兰的原始描述可能失败，需要通过下一轮对话补充明确定位与建模顺序。`--resume` 会保留失败记录并演示这类补充后修正，不应把最终通过案例当作一次生成成功率。

Qwen3.8 与新核心的单独验收命令为 `python scripts/validate_qwen38.py`，最新记录保存在 `docs/qwen38-validation.json`。先生成模数 2、17 齿、20mm 厚直齿轮，再通过下一轮对话修改为 15mm；检查实际模型身份、新引擎标记、参数保持、实体厚度与文件存在。首次加载应预留数分钟；这些检查不构成齿轮制造精度认证。

## 已知范围

这是单用户本地课程原型，支持通用机械零件的基础特征组合。几何有效不等于完全满足所有自然语言要求，关键尺寸与外观仍应核对；暂不支持复杂曲面、装配约束、自由手绘草图约束求解、图片识别或模型微调。STEP 不携带本系统的参数历史，继续参数化编辑应保留项目数据库、JSON 或 Python 脚本。FreeCAD 可以打开 STEP，Blender 可以导入 STL/GLB。

## 参考与许可说明

当前核心实际安装并调用 earthtojake/text-to-cad 发布的 cadgen 包，来源、上游提交和 wheel 校验信息见 `vendor/earthtojake_text_to_cad/SOURCE.json`，MIT 许可随工程保留。此仓库与论文 Text2CAD、MLYengineering/Text2CAD 是不同项目。复用其本地 CAD Python 运行与导出接口，规划器使用本地 Qwen3.8，工作台保留本工程前端。

- [earthtojake/text-to-cad](https://github.com/earthtojake/text-to-cad)：MIT，cadgen 0.7.24。
- [build123d](https://github.com/gumyr/build123d)：Apache-2.0。
- [bd-warehouse](https://github.com/gumyr/bd_warehouse)：Apache-2.0，渐开线齿轮。
- [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B)：Apache-2.0。
- [Qwen3.8-27B-GGUF](https://www.modelscope.cn/models/bartowski/Qwen3.8-27B-GGUF)：Apache-2.0。
- [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)：MIT。
- [MLYengineering/Text2CAD](https://github.com/MLYengineering/Text2CAD)：MIT；历史 runner 保存在 `vendor/text2cad/`，当前不调用。
