"""Resolve Conda CUDA runtime libraries for direct Python binding imports."""
import ctypes
from pathlib import Path
import sys


def load_cuda_runtime():
    library_dir = Path(sys.prefix) / "lib"
    for name in ("libcudart.so.12", "libcublasLt.so.12", "libcublas.so.12"):
        library = library_dir / name
        if library.exists():
            ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL)
