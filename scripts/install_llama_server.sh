#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${CONDA_PREFIX:?Activate the T2CAD environment first}"
T2CAD_LLAMA_REV=31288c9c66e59377f7788d920678a565bb89dd37
T2CAD_LLAMA_SRC="$PWD/runtime/llama-source"
if [[ ! -d "$T2CAD_LLAMA_SRC/.git" ]]; then
  mkdir -p "$T2CAD_LLAMA_SRC"
  git init "$T2CAD_LLAMA_SRC"
  git -C "$T2CAD_LLAMA_SRC" remote add origin https://github.com/ggml-org/llama.cpp
fi
git -C "$T2CAD_LLAMA_SRC" fetch --depth 1 origin "$T2CAD_LLAMA_REV"
git -C "$T2CAD_LLAMA_SRC" checkout --detach "$T2CAD_LLAMA_REV"
cmake -S "$T2CAD_LLAMA_SRC" -B "$T2CAD_LLAMA_SRC/build" \
  -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86 \
  -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON \
  -DCUDAToolkit_ROOT="$CONDA_PREFIX" -DCMAKE_CUDA_COMPILER="$CONDA_PREFIX/bin/nvcc" \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_SERVER=ON \
  -DCMAKE_EXE_LINKER_FLAGS="-L$CONDA_PREFIX/lib -Wl,-rpath,$CONDA_PREFIX/lib -lcublas -lcudart"
cmake --build "$T2CAD_LLAMA_SRC/build" --target llama-server -j2
mkdir -p runtime/llama.cpp/bin
cp -a "$T2CAD_LLAMA_SRC/build/bin/." runtime/llama.cpp/bin/
cp "$T2CAD_LLAMA_SRC/LICENSE" runtime/llama.cpp/LICENSE
git -C "$T2CAD_LLAMA_SRC" rev-parse HEAD > runtime/llama.cpp/REVISION
echo "Qwen3.8 CUDA runtime installed in runtime/llama.cpp/bin"
