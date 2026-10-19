import asyncio
import importlib.util
import json
import multiprocessing as mp
import os
from pathlib import Path
import time

from backend.store import ROOT
from backend.llama_server import LlamaServer

MODEL_DIR = ROOT / "models"


class InferenceUnavailable(RuntimeError):
    """Runtime setup failures cannot be repaired by regenerating CAD plans."""


def model_path():
    configured = os.getenv("T2CAD_MODEL_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    files = sorted(MODEL_DIR.rglob("*Qwen3.8*Q4_K_M*.gguf")) if MODEL_DIR.exists() else []
    if files:
        return files[0]
    return MODEL_DIR / "Qwen3.8-27B-Q4_K_M.gguf"


SYSTEM = """你是 T2CAD 机械零件设计规划师。只输出符合 schema 的 JSON 对象，不输出思考或 Markdown。
所有长度单位 mm，角度 deg。为用户创建可重建的完整设计，或基于当前设计修改。保持用户未要求改变的参数、特征、ID。
action=build 时给出完整 design；action=clarify 时给出需要用户补充的关键问题，design=null。
design.expected_size 必须填写最终零件的目标XYZ包围尺寸，使用参数表达式，未知轴填JSON空值null，不要写字符串"null"。例如矩形板["length","width","thickness"]；有底缘轴套["flange_d","flange_d","total_h"]；法兰["outer_d","outer_d","disk_h+neck_h"]。这是用户目标尺寸，不能根据错误几何结果降低要求。外形尺寸由工具独立测量并验证。
参数表每项 {name:英文标识,label:中文,value:数值,unit:mm/deg/count}。所有关键尺寸都应引用参数名，args 中允许数值或参数的 + - * / 表达式。
features 是顺序特征列表，每项 {id:英文唯一标识,name:中文,op:操作,args:对象}。
坐标采用右手系，Z向上。XY局部坐标=x,y，法向+Z；YZ局部坐标=y,z，法向+X；XZ局部坐标=x,z，法向-Y。
box: {width,depth,height,origin:[x,y,z]}，XY宽沿X、深沿Y，宽深居中，从origin沿正Z生长。
重要：box(width=L,depth=W) 的边界是 x=-L/2…L/2、y=-W/2…W/2。孔距边m时坐标应为[±(L/2-m),±(W/2-m)]，不是m或L-m。
具体算例：长80、宽40的板，孔中心距边10，则孔坐标是(±30,±10)，因为80/2-10=30、40/2-10=10。孔坐标不能直接写成(±10,±10)。必须先计算半长减边距、半宽减边距。
cylinder: {radius,height,origin:[x,y,z]}，从origin沿+Z生长。
gear: {module,teeth,height,pressure_angle:可选,helix_angle:可选,module_system:normal/transverse,origin:[x,y,z]}，支持圆柱直齿轮和圆柱斜齿轮。helix_angle=0为直齿，非零为真正螺旋扫掠的斜齿，范围-45至45度；正值右旋、负值左旋。pressure_angle是压力角alpha，helix_angle是螺旋角beta；用户说alpha20、beta15时必须分别创建deg单位的参数并引用它们，不能省略beta或改为直齿轮。
module_system默认normal：module和pressure_angle按法向模数mn、法向压力角alpha_n解释；若用户没说明法向/端面，在summary中明确采用法向制即可。用户明确指定端面值时用transverse。工具内部自动转换端面模数mt=mn/cos(beta)、端面压力角，并根据分度圆计算真实螺旋导程与扭转，不要在参数表达式里写三角函数，也不要把beta直接当总扭转角。默认压力角20度。
斜齿轮完整示例：parameters包含m=2,z=17,h=20,alpha=20(deg),beta=15(deg),bore_d=12；features先{"id":"gear_body","name":"斜齿轮主体","op":"gear","args":{"module":"m","teeth":"z","height":"h","pressure_angle":"alpha","helix_angle":"beta","module_system":"normal"}}，再{"id":"bore","name":"中心通孔","op":"hole","args":{"target":"gear_body","face":">Z","diameter":"bore_d","points":[[0,0]]}}。内孔沿齿轮轴贯通，不随齿扭转；工具保持真实轴心。
齿轮m和z必须分别作为module和teeth的参数引用。需要内孔时，在gear之后对gear的结果使用hole。expected_size 的XY使用JSON空值，写[null,null,"h"]（h替换为实际厚度参数名），界面显示实际包围盒；齿顶圆直径不是XY包围盒边长，禁止把它填入expected_size。直齿轮的齿顶圆直径为module*(teeth+2)，法向斜齿轮为module*teeth/cos(beta)+2*module，均由工具计算，不要在expected_size中写三角函数。
origin 是绝对坐标，省略时永远为[0,0,0]，不会自动接在上一零件上。上下叠加时上段 origin.z 必须等于下段高度。若主体总高包含底缘，也可以从同一底面生成 height=总高 的细圆柱及较矮底缘，再 union。
extrude: {plane:XY/XZ/YZ,origin:[x,y,z],profile:草图,distance}。生成独立实体，不自动合并。
草图为 {type:rect,width,height} 或 {type:circle,radius} 或 {type:polygon,points:[[u,v],...]}。矩形与圆在局部原点居中。
revolve: {plane:XZ,origin:[x,y,z],profile:草图,angle:360,axis_start:[u,v],axis_end:[u,v]}。轴是草图局部坐标，避免轮廓跨越旋转轴。
cut_extrude: {target:已有ID,plane,origin,profile,distance}，用草图拉伸切掉target材料，适合侧孔、槽和内腔。
hole: {target,face:">Z",diameter,points:[[u,v],...],depth:可选}，孔位置相对于选中平面的包围盒中心；depth省略为通孔。要求唯一平面，跨多高度或复杂形状建议用cut_extrude。
对于矩形四角孔，必须优先使用hole的layout来精确计算孔位，不要手算points：{"target":"base","diameter":"hole_d","layout":{"type":"rect_corners","margin_x":"margin","margin_y":"margin"}}。margin是孔中心距相邻边的距离，工具自动基于实际板宽长放置四孔。
对于均布螺栓孔，优先使用{"target":"body","diameter":"hole_d","layout":{"type":"bolt_circle","radius":"pcd/2","count":4,"start_angle":0}}，其中pcd是分布圆直径。layout和points互斥，不能同时出现。
关键坐标规则：box的XY原点在板中心，不是左下角！例如160×80板的XY范围为[-80,80]×[-40,40]，距边10的四孔中心是(±70,±30)。一般公式为±(length/2-margin)、±(width/2-margin)。
多个相同孔优先用一个hole特征的points一次给出所有位置。如果拆成多个加工特征，target必须引用上一个加工结果，不能每次都引用最初毛坯，否则前面的孔会丢失。所有特征返回新几何，不会原地修改target。
同一直径的多个孔应在同一个hole的points里列出全部孔坐标。若拆成多个切除特征，后一个target必须指向前一个切除结果，不能每次重新指向毛坯，否则之前的孔会丢失。
union/cut/intersect: {target:已有ID,tool:已有ID}。两个引用都必须存在。新建实体不会自动连接，必须明确union。
阶梯体的推荐顺序：创建各实体 → union合并 → 在合并后的整体上钻贯通孔。若先单独钻孔，union必须引用钻孔结果，不能引用钻孔前的毛坯。每个需要保留的分支都必须进入最后特征的依赖链。
fillet: {target,edges:"|Z",radius}；chamfer: {target,edges:">Z",distance}。边选择器可用|X/|Y/|Z或>X/<X/>Y/<Y/>Z/<Z。
linear_pattern: {source:已有ID,count,step:[dx,dy,dz]}；polar_pattern: {source:已有ID,count,angle:360,axis_origin:[0,0,0],axis_direction:[0,0,1]}。阵列生成多个实体，可随后作为布尔工具。
所有操作可附加translate:[dx,dy,dz]和rotate:{start:[x,y,z],end:[x,y,z],angle}。
target省略时指向上一特征。最后一个特征必须是完整零件。不要把独立工具留作最后特征。
必须完整覆盖用户要求的每一个结构。参数表中声明孔径不等于已经建孔，必须有hole或cut_extrude特征实际切除材料。不要只输出毛坯后结束。
输出前核对 features 已包含所有孔、槽、凸台和轮廓；多轮修改必须输出包含所有原有结构的完整特征序列。
输出格式示例（仅示范工具组合，实际尺寸和结构必须取自本轮需求）：
{"action":"build","summary":"合并阶梯圆柱并钻中心孔。","design":{"name":"阶梯体","expected_size":["base_d","base_d","total_h"],"parameters":[{"name":"base_d","label":"底座直径","value":60,"unit":"mm"},{"name":"body_d","label":"主体直径","value":30,"unit":"mm"},{"name":"total_h","label":"总高","value":40,"unit":"mm"},{"name":"base_h","label":"底座厚度","value":8,"unit":"mm"},{"name":"hole_d","label":"通孔直径","value":12,"unit":"mm"}],"features":[{"id":"base","name":"底座","op":"cylinder","args":{"radius":"base_d/2","height":"base_h"}},{"id":"body","name":"主体","op":"cylinder","args":{"radius":"body_d/2","height":"total_h"}},{"id":"joined","name":"合并","op":"union","args":{"target":"base","tool":"body"}},{"id":"bore","name":"整体通孔","op":"hole","args":{"target":"joined","diameter":"hole_d","points":[[0,0]]}}]}}
没有依据时不要擅自添加圆角、孔或装饰。缺少非关键尺寸可选合理默认，但必须在summary里明确。结构歧义必须clarify。
收到几何错误时修正失败特征，保持用户明确指定的尺寸不变；无法兼容时clarify。摘要简短中文，说明设计和修改结果。
/no_think"""

RESPONSE_SCHEMA = {
    "type": "object", "properties": {
        "action": {"type": "string", "enum": ["build", "clarify"]},
        "summary": {"type": "string"},
        "design": {"anyOf": [{"type": "null"}, {"type": "object", "properties": {
            "name": {"type": "string"},
            "expected_size": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"anyOf": [{"type": "string"}, {"type": "number"}, {"type": "null"}]}},
            "parameters": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string"}, "label": {"type": "string"}, "value": {"type": "number"},
                "unit": {"type": "string", "enum": ["mm", "deg", "count"]}}, "required": ["name", "label", "value", "unit"], "additionalProperties": False}},
            "features": {"type": "array", "items": {"type": "object", "properties": {
                "id": {"type": "string"}, "name": {"type": "string"}, "op": {"type": "string", "enum": ["box", "cylinder", "gear", "extrude", "revolve", "cut_extrude", "hole", "union", "cut", "intersect", "fillet", "chamfer", "linear_pattern", "polar_pattern"]},
                "args": {"type": "object"}}, "required": ["id", "name", "op", "args"], "additionalProperties": False}}},
            "required": ["name", "parameters", "features", "expected_size"], "additionalProperties": False}]}},
    "required": ["action", "summary", "design"], "additionalProperties": False,
}


def worker(pipe, path):
    ready = False
    try:
        from backend.runtime import load_cuda_runtime
        load_cuda_runtime()
        from llama_cpp import Llama, llama_supports_gpu_offload, LlamaGrammar
        if not llama_supports_gpu_offload():
            raise RuntimeError("安装的 llama-cpp-python 没有 GPU 支持，请执行 scripts/install_inference.sh")
        start = time.monotonic()
        llm = Llama(model_path=path, n_gpu_layers=-1, n_ctx=int(os.getenv("T2CAD_CONTEXT", "8192")),
                    n_batch=256, n_threads=4, use_mmap=True, use_mlock=False, flash_attn=True, verbose=True)
        grammar = LlamaGrammar.from_json_schema(json.dumps(RESPONSE_SCHEMA), verbose=False)
        ready = True
        pipe.send({"type": "ready", "load_seconds": round(time.monotonic() - start, 2)})
        while True:
            messages = pipe.recv()
            if messages is None:
                break
            # Qwen non-thinking prefix prevents the grammar from colliding with <think> tokens.
            prompt = "".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages)
            repair = messages[-1]["content"].startswith("执行错误:")
            planning_tokens = 0
            start = time.monotonic()
            if repair:
                thinking_prompt = prompt.replace("/no_think", "/think") + "<|im_start|>assistant\n<think>\n"
                analysis = llm.create_completion(thinking_prompt, max_tokens=768, temperature=0.6,
                                                 top_p=0.95, stop=["</think>", "<|im_end|>"])
                planning_tokens = analysis["usage"]["completion_tokens"]
                prompt = thinking_prompt + analysis["choices"][0]["text"] + "\n</think>\n\n"
            else:
                prompt += "<|im_start|>assistant\n<think>\n\n</think>\n\n"
            tokens = llm.tokenize(prompt.encode(), add_bos=False)
            if len(tokens) > llm.n_ctx() - 2048:
                raise ValueError("当前设计超过上下文预算，请减少特征或增大 T2CAD_CONTEXT")
            output = llm.create_completion(prompt, max_tokens=min(4096, llm.n_ctx() - len(tokens) - 16),
                                           temperature=0.3, top_p=0.85, repeat_penalty=1.08,
                                           grammar=grammar, stop=["<|im_end|>"])
            text = output["choices"][0]["text"]
            pipe.send({"type": "result", "response": json.loads(text), "seconds": round(time.monotonic() - start, 2),
                       "usage": output["usage"], "planning_tokens": planning_tokens})
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        try:
            pipe.send({"type": "error", "message": str(exc), "unavailable": not ready})
        except (EOFError, BrokenPipeError):
            pass
    finally:
        pipe.close()


class Inference:
    def __init__(self):
        self.process = None
        self.pipe = None
        self.loaded = False
        self.load_seconds = None
        self.server = LlamaServer()
        self.active_model = None

    def close(self):
        self.server.close()
        if self.process and self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=5)
            if self.process.is_alive():
                self.process.kill()
                self.process.join()
        if self.pipe:
            self.pipe.close()
        self.process = self.pipe = None
        self.loaded = False
        self.active_model = None

    async def receive(self, cancel, timeout):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if cancel.is_set():
                self.close()
                raise asyncio.CancelledError()
            if self.pipe.poll():
                try:
                    data = self.pipe.recv()
                except EOFError as exc:
                    self.close()
                    raise RuntimeError("推理进程意外退出，请检查 logs/backend.log") from exc
                if data["type"] == "error":
                    self.close()
                    if data.get("unavailable"):
                        raise InferenceUnavailable("本地推理初始化失败：" + data["message"])
                    raise RuntimeError(data["message"])
                return data
            if not self.process.is_alive():
                self.close()
                raise RuntimeError("推理进程退出，请检查模型文件、内存和 GPU 状态")
            await asyncio.sleep(0.15)
        self.close()
        raise TimeoutError("本地模型加载或推理超时")

    async def generate(self, messages, cancel, notify):
        path = model_path()
        if "Qwen3.8" in path.name:
            if not path.is_file():
                raise InferenceUnavailable("Qwen3.8 模型不存在，请执行 python scripts/download_model.py")
            try:
                result = await self.server.generate(path, messages, RESPONSE_SCHEMA, cancel, notify)
                self.loaded = True
                self.active_model = path.name
                self.load_seconds = self.server.load_seconds
                return result
            except asyncio.CancelledError:
                self.close()
                raise
            except Exception as exc:
                self.close()
                raise InferenceUnavailable(str(exc)) from exc
        if not self.process or not self.process.is_alive():
            if importlib.util.find_spec("llama_cpp") is None:
                raise InferenceUnavailable("当前后端环境未安装 llama-cpp-python，请激活 T2CAD 后执行 bash scripts/install_inference.sh。")

            async def start_model(path: Path):
                notify("model_loading", {"message": "正在将 GGUF 权重加载到 GPU", "filename": path.name})
                ctx = mp.get_context("spawn")
                self.pipe, child = ctx.Pipe()
                self.process = ctx.Process(target=worker, args=(child, str(path)), daemon=True)
                self.process.start()
                child.close()
                ready = await self.receive(cancel, int(os.getenv("T2CAD_MODEL_LOAD_TIMEOUT", "120")))
                self.loaded = True
                self.load_seconds = ready["load_seconds"]
                self.active_model = path.name
                notify("model_ready", {**ready, "model": path.name})

            path = model_path()
            if not path.is_file():
                raise FileNotFoundError("模型尚未下载，请运行 python scripts/download_model.py；也可以先运行内置 CAD 示例。")
            try:
                await start_model(path)
            except (TimeoutError, RuntimeError, InferenceUnavailable) as first_error:
                fallback = next(iter(sorted(MODEL_DIR.glob("Qwen3-14B*Q4_K_M*.gguf"))), None)
                if not fallback or fallback == path:
                    raise
                self.close()
                notify("model_fallback", {"from": path.name, "to": fallback.name, "message": str(first_error)})
                await start_model(fallback)
        self.pipe.send(messages)
        notify("planning", {"message": "本地模型正在规划参数与建模特征"})
        return await self.receive(cancel, 300)


inference = Inference()
