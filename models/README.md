# 本地模型文件

模型权重不提交到 Git。默认模型放置位置：

```text
/home/dlts/CAD系统/models/Qwen3.8-27B-Q4_K_M.gguf
```

在项目根目录、`T2CAD` 环境中下载并校验：

```bash
python scripts/download_model.py --model qwen38 --source modelscope
```

可选来源：

```bash
python scripts/download_model.py --model qwen38 --source huggingface
python scripts/download_model.py --model qwen38 --source mirror
```

脚本会断点续传并校验 SHA256，校验通过后才会生成 `.gguf` 文件。当前 Qwen3.8-27B Q4_K_M 权重约 17.4GB，需要预留足够磁盘空间。

低显存机器可以显式下载旧的 14B 权重，但本项目默认配置和课程验收使用 Qwen3.8：

```bash
python scripts/download_model.py --model qwen14 --source modelscope
```

模型路径也可以通过 `T2CAD_MODEL_PATH` 指向其他本地 GGUF 文件。
