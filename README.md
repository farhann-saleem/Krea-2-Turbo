<div align="center">
  <h1 align="center">Krea-2-Turbo</h1>
  <p align="center"><i>Text → image for Marketing Studio</i></p>

  [![Python](https://img.shields.io/badge/Python-3.11-blue.svg?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
  [![RunPod](https://img.shields.io/badge/RunPod-Serverless%20GPU-7B2FF7.svg?style=for-the-badge)](https://runpod.io)
  [![ComfyUI](https://img.shields.io/badge/ComfyUI-0.35.1-black.svg?style=for-the-badge)](https://github.com/comfyanonymous/ComfyUI)
</div>

---

> Prompt in. PNG out. Zero idle weight downloads once the volume is warm.

**Krea-2-Turbo** is the text-to-image leg of [Marketing Studio](https://github.com/farhann-saleem/sixeyes). One RunPod serverless GPU endpoint runs ComfyUI + Krea-2-Turbo fp8; ~18 GB of weights stream from Cloudflare R2 onto a network volume. Cold starts pay once — warm images are ~$0.002.

| | |
| --- | --- |
| **Endpoint** | `i3fvrhucaici89` · **EU-RO-1 only** |
| **Stack** | ComfyUI v0.35.1 · PyTorch 2.7.0 · CUDA 12.8 |
| **Defaults** | 4 steps · cfg 1.0 · euler/simple · 1280×720 |

---

## Architecture

1. **The Core** — Docker image with ComfyUI. Weights are *not* baked in; they live on R2 under `comfy-models/krea2-turbo/`.
2. **The Mount** — On boot, if `/runpod-volume` is a real mount, cache to `/runpod-volume/krea2-turbo`, symlink into Comfy, start Comfy, *then* `runpod.serverless.start()`.
3. **The Delivery** — `generate` returns one inline `png_b64` (fine for a single still). Use async `/run` + poll — never `/runsync`.

```
Marketing Studio backend ──► THIS WORKER (GPU)
                          ├── Qwen-and-QwenEdit (I2I)
                          ├── Faceswap-and-FF (CPU)
                          └── Modal LTX-2.5
```

---

## One request

```bash
# 1) health (no GPU) — stop if throttled > 0
# 2) ping
curl -s https://api.runpod.ai/v2/i3fvrhucaici89/runsync \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{"op":"ping"}}'
```

```json
{
  "input": {
    "op": "generate",
    "prompt": "a rain-slick Dublin street at dusk, neon reflections, cinematic",
    "width": 1280,
    "height": 720,
    "steps": 4
  }
}
```

Send that to `/run`, then poll `/status/{id}`.

---

## Setup

Build, deploy, env names, smoke sequence: **[SETUP.md](SETUP.md)**  
Graph + boot: **[ARCHITECTURE.md](ARCHITECTURE.md)** · Weights + params: **[MODELS.md](MODELS.md)**

Siblings: [sixeyes](https://github.com/farhann-saleem/sixeyes) · [Qwen-and-QwenEdit](https://github.com/farhann-saleem/Qwen-and-QwenEdit) · [Faceswap-and-FF](https://github.com/farhann-saleem/Faceswap-and-FF)

<div align="center">
  <i>Four steps. One image. Scale to zero.</i>
</div>
