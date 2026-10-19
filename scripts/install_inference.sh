#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-source}" == "wheel" ]]; then
  python -m pip install 'llama-cpp-python==0.3.36' --only-binary=:all: --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
else
  : "${CONDA_PREFIX:?Please activate the T2CAD Conda environment first}"
  CONDA_BIN="${CONDA_EXE:-$HOME/miniconda3/bin/conda}"
  "$CONDA_BIN" install -p "$CONDA_PREFIX" -y --override-channels -c nvidia/label/cuda-12.4.1 -c conda-forge cuda-nvcc cuda-cudart-dev cuda-cudart-static libcublas-dev cuda-driver-dev
  CMAKE_ARGS="-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86 -DCUDAToolkit_ROOT=$CONDA_PREFIX -DCMAKE_CUDA_COMPILER=$CONDA_PREFIX/bin/nvcc" \
    CMAKE_BUILD_PARALLEL_LEVEL=2 python -m pip install --no-binary=llama-cpp-python 'llama-cpp-python==0.3.36'
fi
LD_LIBRARY_PATH="${CONDA_PREFIX}/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" python -c 'from llama_cpp import llama_supports_gpu_offload; assert llama_supports_gpu_offload(), "CUDA support missing"; print("CUDA backend available")'
