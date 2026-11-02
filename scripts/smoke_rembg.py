"""Smoke test isolado do rembg: cada iteração roda em um processo separado (um crash nativo
como 0xC0000409 mata só o filho e aparece como código de saída).

Uso: python scripts/smoke_rembg.py [imagem] [--runs 5] [--shared-session]
Sem imagem, gera uma pequena localmente. Sequencial, sem paralelismo, sem rede (exceto 1º download do modelo).
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time

CHILD = r"""
import io, sys, time
from PIL import Image
shared, path, n = sys.argv[1] == "1", sys.argv[2], int(sys.argv[3])
data = open(path, "rb").read()
from rembg import new_session, remove
session = new_session("u2net") if shared else None
for i in range(n):
    t = time.time()
    out = remove(data, session=session) if shared else remove(data)
    img = Image.open(io.BytesIO(out))
    print(f"  call {i + 1}: ok {img.size} {img.mode} {time.time() - t:.1f}s", flush=True)
"""


def sample_image(path: str) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (400, 400), "white")
    ImageDraw.Draw(img).rounded_rectangle((120, 60, 280, 340), 20, fill=(30, 90, 200))
    img.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", nargs="?")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--calls", type=int, default=1, help="chamadas ao remove() por processo")
    ap.add_argument("--shared-session", action="store_true")
    args = ap.parse_args()
    image = args.image
    if not image:
        import tempfile
        image = tempfile.mkstemp(suffix=".png")[1]
        sample_image(image)
    bad = 0
    for run in range(1, args.runs + 1):
        t = time.time()
        proc = subprocess.run(
            [sys.executable, "-I", "-c", CHILD, "1" if args.shared_session else "0", image, str(args.calls)],
            capture_output=True, text=True,
        )
        code = proc.returncode & 0xFFFFFFFF
        print(f"run {run}/{args.runs}: exit=0x{code:08X} {time.time() - t:.1f}s")
        print(proc.stdout.rstrip())
        if proc.returncode:
            bad += 1
            print("  stderr:", proc.stderr.strip()[-300:])
    print(f"falhas: {bad}/{args.runs}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
