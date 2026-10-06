"""Rebuild the documentation index end to end: download -> chunk -> embed + load.

    .venv/Scripts/python.exe docs_index/run_all.py
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

for step in ("download.py", "chunk.py", "embed_load.py"):
    print(f"\n=== {step} ===", flush=True)
    subprocess.run([sys.executable, str(HERE / step)], check=True)
