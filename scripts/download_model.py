"""Download the official Qwen quantization with resume and SHA256 verification."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "qwen38": {
        "name": "Qwen3.8-27B-Q4_K_M.gguf",
        "sha256": "880a52af8317974f7b4b064a6bc29ff49e188b91aa218e08eea3078b6b1cc673",
        "repo": "bartowski/Qwen3.8-27B-GGUF",
        "revision": "master",
    },
    "qwen14": {
        "name": "Qwen3-14B-Q4_K_M.gguf",
        "sha256": "500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0",
        "repo": "Qwen/Qwen3-14B-GGUF",
        "revision": "master",
    },
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["modelscope", "huggingface", "mirror"], default="modelscope")
    parser.add_argument("--model", choices=MODELS, default="qwen38")
    args = parser.parse_args()
    selected = MODELS[args.model]
    name, sha256, repo, revision = selected["name"], selected["sha256"], selected["repo"], selected["revision"]
    sources = {
        "modelscope": f"https://modelscope.cn/models/{repo}/resolve/{revision}/{name}",
        "huggingface": f"https://huggingface.co/{repo}/resolve/{revision}/{name}",
        "mirror": f"https://hf-mirror.com/{repo}/resolve/{revision}/{name}",
    }
    folder = ROOT / "models"
    folder.mkdir(exist_ok=True)
    output = folder / name
    temporary = folder / (name + ".part")
    if not output.exists():
        subprocess.run(["curl", "-fL", "--retry", "5", "--connect-timeout", "30", "--speed-time", "90", "--speed-limit", "1024", "-C", "-", "-o", str(temporary), sources[args.source]], check=True)
    path = output if output.exists() else temporary
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != sha256:
        raise RuntimeError("SHA256 mismatch; do not load this file. Remove the incomplete file and retry.")
    if path != output:
        path.rename(output)
    manifest = {"repo": repo, "file": name, "sha256": sha256,
                "bytes": output.stat().st_size, "source": sources[args.source], "verified_at": time.time()}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("Verified:", output)


if __name__ == "__main__":
    main()
