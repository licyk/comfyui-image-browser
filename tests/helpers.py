"""Temporary ComfyUI folders and images carrying the metadata ComfyUI writes."""

import io
import json
import struct
import zlib
from pathlib import Path

from PIL import Image

PROMPT = "cherry blossoms over a river"


def comfy_png(path: Path, text: str = PROMPT, seed: int = 42) -> Path:
    """A 2×2 PNG carrying the API graph ComfyUI's SaveImage writes."""
    graph = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sdxl.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 20,
                "cfg": 7.0,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "ComfyUI", "images": ["8", 0]}},
    }
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), (200, 100, 50)).save(buffer, "PNG")
    data = buffer.getvalue()
    body = b"prompt\x00" + json.dumps(graph).encode("latin-1")
    chunk = struct.pack(">I", len(body)) + b"tEXt" + body + struct.pack(">I", zlib.crc32(b"tEXt" + body) & 0xFFFFFFFF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data[:33] + chunk + data[33:])
    return path


def comfy_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    output, input, temp = tmp_path / "output", tmp_path / "input", tmp_path / "temp"
    for directory in (output, input, temp):
        directory.mkdir()
    return output, input, temp
