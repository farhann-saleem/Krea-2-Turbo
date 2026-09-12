"""Krea-2-Turbo T2I on RunPod serverless (ComfyUI + R2 fp8 weights).

Ping does not load the model. Generate pulls weights from R2 if missing, starts
ComfyUI once, runs the goldmine graph (4 steps, cfg 1.0, euler/simple).

R2 layout (bucket comfy):
  comfy-models/krea2-turbo/diffusion_models/krea2_turbo_fp8_scaled.safetensors
  comfy-models/krea2-turbo/text_encoders/qwen3vl_4b_fp8_scaled.safetensors
  comfy-models/krea2-turbo/vae/qwen_image_vae.safetensors
"""
from __future__ import annotations

import sys
print(">>> handler.py starting", flush=True)
print(f">>> Python {sys.version}", flush=True)

import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

try:
    import boto3
    print(">>> boto3 ok", flush=True)
except Exception as e:
    print(f">>> boto3 FAILED: {e}", flush=True)
    sys.exit(1)

try:
    import requests
    print(">>> requests ok", flush=True)
except Exception as e:
    print(f">>> requests FAILED: {e}", flush=True)
    sys.exit(1)

try:
    import runpod
    print(f">>> runpod ok (version={getattr(runpod, '__version__', '?')})", flush=True)
except Exception as e:
    print(f">>> runpod FAILED: {e}", flush=True)
    sys.exit(1)

from botocore.config import Config

WORKER = "krea"
COMFY_DIR = Path(os.environ.get("COMFY_DIR", "/workspace/ComfyUI"))
COMFY_URL = "http://127.0.0.1:8188"
UNET = "krea2_turbo_fp8_scaled.safetensors"
CLIP = "qwen3vl_4b_fp8_scaled.safetensors"
VAE = "qwen_image_vae.safetensors"
R2_PREFIX = "comfy-models/krea2-turbo"
USD_PER_HOUR = float(os.environ.get("RUNPOD_GPU_USD_PER_HR", "0.69"))

_comfy_proc: subprocess.Popen | None = None


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return default


def _volume_root() -> Path:
    vol = Path("/runpod-volume")
    # An empty /runpod-volume dir can exist without a volume. Only use it if mounted.
    if vol.is_dir() and os.path.ismount(str(vol)):
        return vol / "krea2-turbo"
    return COMFY_DIR / "models"


def _assert_disk(path: Path, need_gb: float = 22) -> None:
    path.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(path).free
    if free < need_gb * 1e9:
        mounted = os.path.ismount("/runpod-volume")
        raise RuntimeError(
            f"Need {need_gb:.0f}GB free, have {free / 1e9:.1f}GB at {path}. "
            f"/runpod-volume mounted={mounted}. "
            "Attach a network volume (same DC), then STOP old workers so a new "
            "worker actually mounts it."
        )


def _r2():
    account = _env("R2_ACCOUNT_ID")
    endpoint = _env("R2_ENDPOINT") or (f"https://{account}.r2.cloudflarestorage.com" if account else "")
    access = _env("R2_ACCESS_KEY")
    secret = _env("R2_SECRET_KEY")
    bucket = _env("R2_BUCKET_NAME", "R2_BUCKET", default="comfy")
    if not (endpoint and access and secret and bucket):
        raise RuntimeError("Missing R2 env (R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY, R2_BUCKET_NAME).")
    client = boto3.client(
        "s3",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        endpoint_url=endpoint,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )
    return bucket, client


def _download(key: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _assert_disk(dest.parent)
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"cached {dest.name} ({dest.stat().st_size} bytes)", flush=True)
        return
    bucket, client = _r2()
    print(f"downloading s3://{bucket}/{key} -> {dest}", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    client.download_file(bucket, key, str(tmp))
    tmp.replace(dest)
    print(f"ok {dest.name} ({dest.stat().st_size} bytes)", flush=True)


def ensure_weights() -> dict[str, Path]:
    root = _volume_root()
    files = {
        "unet": (f"{R2_PREFIX}/diffusion_models/{UNET}", root / "diffusion_models" / UNET),
        "clip": (f"{R2_PREFIX}/text_encoders/{CLIP}", root / "text_encoders" / CLIP),
        "vae": (f"{R2_PREFIX}/vae/{VAE}", root / "vae" / VAE),
    }
    t0 = time.time()
    for _kind, (key, dest) in files.items():
        _download(key, dest)
    # ComfyUI reads from COMFY_DIR/models — symlink if we stored on the volume.
    for sub, dest in (
        ("diffusion_models", files["unet"][1]),
        ("text_encoders", files["clip"][1]),
        ("vae", files["vae"][1]),
    ):
        target_dir = COMFY_DIR / "models" / sub
        target_dir.mkdir(parents=True, exist_ok=True)
        link = target_dir / dest.name
        if dest.resolve() != link.resolve():
            if link.exists() or link.is_symlink():
                link.unlink()
            try:
                link.symlink_to(dest)
            except OSError:
                shutil.copy2(dest, link)
    return {"download_ms": int((time.time() - t0) * 1000)}


def _comfy_up() -> bool:
    try:
        r = requests.get(f"{COMFY_URL}/system_stats", timeout=3)
        return r.status_code == 200
    except requests.RequestException:
        return False


def ensure_comfy() -> None:
    global _comfy_proc
    if _comfy_up():
        return
    log = Path("/tmp/comfy.log")
    log.write_text("")
    _comfy_proc = subprocess.Popen(
        [
            sys.executable,
            "main.py",
            "--listen",
            "127.0.0.1",
            "--port",
            "8188",
            "--highvram",
            "--disable-auto-launch",
        ],
        cwd=str(COMFY_DIR),
        stdout=open(log, "ab"),
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 180
    while time.time() < deadline:
        if _comfy_up():
            print("ComfyUI ready", flush=True)
            return
        if _comfy_proc.poll() is not None:
            raise RuntimeError(f"ComfyUI exited: {log.read_text()[-2000:]}")
        time.sleep(2)
    raise RuntimeError(f"ComfyUI did not start: {log.read_text()[-2000:]}")


def build_workflow(prompt: str, width: int, height: int, seed: int, steps: int) -> dict:
    return {
        "1": {
            "class_type": "UNETLoader",
            "inputs": {"unet_name": UNET, "weight_dtype": "fp8_e4m3fn"},
        },
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": CLIP, "type": "krea2"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {
            "class_type": "EmptySD3LatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "5": {
            "class_type": "KSampler",
            "inputs": {
                "model": ["1", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["4", 0],
                "seed": seed,
                "steps": steps,
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
            },
        },
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": ""}},
        "8": {"class_type": "VAEDecode", "inputs": {"vae": ["3", 0], "samples": ["5", 0]}},
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "ms_krea"},
        },
    }


def _queue(workflow: dict, timeout_s: int = 240) -> bytes:
    resp = requests.post(f"{COMFY_URL}/prompt", json={"prompt": workflow}, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Comfy queue {resp.status_code}: {resp.text[:1500]}")
    data = resp.json()
    if data.get("node_errors"):
        raise RuntimeError(f"Comfy node_errors: {json.dumps(data['node_errors'])[:2000]}")
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"no prompt_id: {data}")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        hist = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=15).json()
        if prompt_id in hist:
            outputs = hist[prompt_id].get("outputs") or {}
            for node in outputs.values():
                for img in node.get("images") or []:
                    params = {
                        "filename": img["filename"],
                        "subfolder": img.get("subfolder", ""),
                        "type": img.get("type", "output"),
                    }
                    raw = requests.get(f"{COMFY_URL}/view", params=params, timeout=60)
                    raw.raise_for_status()
                    return raw.content
        time.sleep(1)
    raise TimeoutError(f"Comfy timed out after {timeout_s}s for {prompt_id}")


def generate(inp: dict) -> dict:
    prompt = (inp.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    width = int(inp.get("width") or 1280)
    height = int(inp.get("height") or 720)
    steps = int(inp.get("steps") or 4)
    seed = int(inp.get("seed") or int(time.time()) % 2_147_483_647)
    t0 = time.time()
    dl = ensure_weights()
    ensure_comfy()
    png = _queue(build_workflow(prompt, width, height, seed, steps))
    duration_ms = int((time.time() - t0) * 1000)
    estimated_usd = round((duration_ms / 1000 / 3600) * USD_PER_HOUR, 6)
    return {
        "ok": True,
        "worker": WORKER,
        "width": width,
        "height": height,
        "steps": steps,
        "seed": seed,
        "duration_ms": duration_ms,
        "download_ms": dl["download_ms"],
        "estimated_usd": estimated_usd,
        "usd_per_hour_assumed": USD_PER_HOUR,
        "png_b64": base64.b64encode(png).decode(),
    }


def handler(job):
    inp = job.get("input") or {}
    prompt = (inp.get("prompt") or "").strip()
    op = str(inp.get("op") or ("generate" if prompt else "ping")).lower()
    if op == "ping":
        vol = Path("/runpod-volume")
        root = _volume_root()
        try:
            free_gb = round(shutil.disk_usage(root if root.exists() else Path("/")).free / 1e9, 2)
        except OSError:
            free_gb = None
        return {
            "ok": True,
            "worker": WORKER,
            "comfy_up": _comfy_up(),
            "volume_mounted": os.path.ismount(str(vol)),
            "weight_root": str(root),
            "free_gb": free_gb,
        }
    if op in {"generate", "sample"}:
        try:
            return generate(inp)
        except Exception as exc:
            return {"ok": False, "worker": WORKER, "error": f"{type(exc).__name__}: {exc}"}
    return {"error": f"unknown op {op}. Use ping or generate."}


# --- Worker init: download weights + start ComfyUI BEFORE accepting jobs ---
print(">>> worker init: downloading weights", flush=True)
try:
    ensure_weights()
    print(">>> weights ready, starting ComfyUI", flush=True)
    ensure_comfy()
    print(">>> ComfyUI ready, accepting jobs", flush=True)
except Exception as e:
    print(f">>> init warning (will retry on first job): {e}", flush=True)

runpod.serverless.start({"handler": handler})
